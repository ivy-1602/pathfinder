import hmac
import json
import os
import re
import secrets
import time
from collections import Counter
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import assistant
from constants import BRANCHES, CATEGORIES, COSTS, GOALS, LEVELS, MODES, STATUSES
from models import Opportunity, Roadmap, Saved, User, db
from recommender import recommend, top_skill_gaps
from seed_data import SAMPLE_OPPORTUNITIES

app = Flask(__name__)
Path(app.instance_path).mkdir(parents=True, exist_ok=True)


def load_secret_key():
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    key_file = Path(app.instance_path) / "secret.key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


app.config.update(
    SECRET_KEY=load_secret_key(),
    SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL") or f"sqlite:///{Path(app.instance_path, 'pathfinder.db').as_posix()}",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=64 * 1024,
    ADMIN_EMAILS={e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()},
)
db.init_app(app)

MIN_SCORE = 15  # dashboard hides near-zero matches; Explore still lists everything
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------------ helpers
def clip(value, n=500):
    return (value or "").strip()[:n]


def safe_next(target, fallback):
    if target and target.startswith("/") and not target.startswith("//") and not urlparse(target).netloc:
        return target
    return fallback


_hits = {}


def rate_limited(key, limit=25, window=3600):
    now = time.time()
    recent = [t for t in _hits.get(key, []) if now - t < window]
    if len(recent) >= limit:
        _hits[key] = recent
        return True
    recent.append(now)
    _hits[key] = recent
    return False


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(error="Please log in again."), 401
            flash("Log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not g.user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


@app.before_request
def load_user_and_check_csrf():
    uid = session.get("uid")
    g.user = db.session.get(User, uid) if uid else None
    if request.method == "POST":
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not sent or not hmac.compare_digest(sent.encode(), session.get("csrf", "").encode()):
            abort(400, "Your session expired. Reload the page and try again.")


@app.context_processor
def inject_globals():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return dict(csrf_token=session["csrf"], current_user=g.user,
                STATUSES=STATUSES, CATEGORIES=CATEGORIES, today=date.today())


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def http_error(err):
    return render_template("error.html", error=err), err.code


def parse_profile(form):
    data = {"branch": form.get("branch", "").strip(), "interests": clip(form.get("interests")),
            "skills": clip(form.get("skills")), "career_goal": form.get("career_goal", "").strip()}
    try:
        data["semester"] = int(form.get("semester", ""))
        data["cgpa"] = float(form.get("cgpa", ""))
    except ValueError:
        return data, "Enter a valid semester and CGPA."
    if data["branch"] not in BRANCHES or data["career_goal"] not in GOALS:
        return data, "Choose a branch and career goal from the lists."
    if not data["interests"]:
        return data, "Add at least one interest so we can match you."
    if not (1 <= data["semester"] <= 12) or not (0 <= data["cgpa"] <= 10):
        return data, "Semester must be 1-12 and CGPA must be between 0 and 10."
    return data, None


def popularity_for(user):
    rows = (db.session.query(Saved.opportunity_id, func.count(Saved.id))
            .join(User, User.id == Saved.user_id)
            .filter(User.branch == user.branch, Saved.user_id != user.id,
                    Saved.status.in_(["saved", "in_progress", "completed"]))
            .group_by(Saved.opportunity_id).all())
    return dict(rows)


def compute(user):
    opps = Opportunity.query.order_by(Opportunity.id).all()
    statuses = {s.opportunity_id: s.status for s in Saved.query.filter_by(user_id=user.id)}
    return recommend(user, opps, popularity_for(user)), statuses


def live_recs(recs, statuses):
    return [r for r in recs if r.opportunity.is_open and statuses.get(r.id) not in ("dismissed", "completed")]


# ------------------------------------------------------------------ public pages
@app.route("/")
def index():
    return render_template("index.html", student_count=User.query.count(),
                           opportunity_count=Opportunity.query.count())


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        data, error = parse_profile(request.form)
        name = clip(request.form.get("name"), 100)
        email = clip(request.form.get("email"), 160).lower()
        password = request.form.get("password", "")
        if not error and not (name and EMAIL_RE.match(email)):
            error = "Enter your name and a valid email address."
        if not error and len(password) < 8:
            error = "Use a password with at least 8 characters."
        if not error and password != request.form.get("confirm", ""):
            error = "The two passwords don't match."
        if not error and User.query.filter_by(email=email).first():
            error = "That email already has an account. Log in instead."
        if error:
            flash(error, "error")
            return render_template("register.html", v=request.form), 400
        user = User(name=name, email=email, **data)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("That email already has an account. Log in instead.", "error")
            return render_template("register.html", v=request.form), 400
        session.clear()
        session["uid"] = user.id
        flash(f"Welcome, {user.first_name}. Your recommendations are ready.", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html", v={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = clip(request.form.get("email"), 160).lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password", "")):
            session.clear()
            session["uid"] = user.id
            return redirect(safe_next(request.args.get("next"), url_for("dashboard")))
        flash("Email or password is incorrect.", "error")
        return render_template("login.html"), 401
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


# ------------------------------------------------------------------ student pages
@app.route("/dashboard")
@login_required
def dashboard():
    recs, statuses = compute(g.user)
    live = live_recs(recs, statuses)
    eligible = [r for r in live if r.eligible]
    eligible = [r for r in eligible if r.score >= MIN_SCORE] or eligible[:6]
    near = [r for r in live if not r.eligible and r.near][:4]

    category = request.args.get("category", "")
    sort = request.args.get("sort", "match")
    shown = [r for r in eligible if not category or r.opportunity.category == category]
    if sort == "title":
        shown.sort(key=lambda r: r.opportunity.title.lower())
    elif sort == "deadline":
        shown.sort(key=lambda r: (r.opportunity.deadline is None, r.opportunity.deadline or date.max))

    n_terms = lambda s: len([t for t in (s or "").split(",") if t.strip()])
    completeness = 40 + (20 if n_terms(g.user.interests) >= 3 else 0) + (20 if n_terms(g.user.skills) >= 3 else 0) \
        + (20 if g.user.career_goal != "Not sure yet" else 0)
    counts = Counter(statuses.values())
    return render_template("dashboard.html", recs=shown, near=near, statuses=statuses, category=category, sort=sort,
                           categories=sorted({r.opportunity.category for r in eligible}),
                           gaps=top_skill_gaps(eligible), completeness=completeness, counts=counts,
                           total=len(eligible))


@app.route("/explore")
@login_required
def explore():
    recs, statuses = compute(g.user)
    f = {k: request.args.get(k, "").strip() for k in ("q", "category", "level", "cost", "mode")}
    f["eligible"] = request.args.get("eligible", "")
    q = f["q"].lower()
    shown = []
    for r in recs:
        o = r.opportunity
        if q and q not in f"{o.title} {o.description} {o.tags}".lower():
            continue
        if any(f[k] and getattr(o, k) != f[k] for k in ("category", "level", "cost", "mode")):
            continue
        if f["eligible"] and not r.eligible:
            continue
        shown.append(r)
    return render_template("explore.html", recs=shown, statuses=statuses, f=f, LEVELS=LEVELS, COSTS=COSTS, MODES=MODES)


@app.route("/opportunity/<int:opp_id>")
@login_required
def opportunity(opp_id):
    recs, statuses = compute(g.user)
    rec = next((r for r in recs if r.id == opp_id), None)
    if rec is None:
        abort(404)
    return render_template("opportunity.html", rec=rec, status=statuses.get(opp_id))


@app.route("/opportunity/<int:opp_id>/status", methods=["POST"])
@login_required
def set_status(opp_id):
    opp = db.get_or_404(Opportunity, opp_id)
    status = request.form.get("status", "")
    row = Saved.query.filter_by(user_id=g.user.id, opportunity_id=opp.id).first()
    if status == "remove":
        if row:
            db.session.delete(row)
    elif status in STATUSES:
        if row:
            row.status = status
        else:
            db.session.add(Saved(user_id=g.user.id, opportunity_id=opp.id, status=status))
    else:
        abort(400, "Unknown status.")
    db.session.commit()
    if status == "dismissed":
        flash(f"Hidden “{opp.title}”. You can restore it from My plan.", "info")
    return redirect(safe_next(request.form.get("next"), url_for("opportunity", opp_id=opp.id)))


@app.route("/plan")
@login_required
def plan():
    rows = (Saved.query.filter_by(user_id=g.user.id).join(Opportunity)
            .order_by(Saved.updated_at.desc()).all())
    groups = {key: [r for r in rows if r.status == key] for key in STATUSES}
    return render_template("plan.html", groups=groups)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        data, error = parse_profile(request.form)
        if error:
            flash(error, "error")
            return render_template("profile.html", v=request.form), 400
        for key, value in data.items():
            setattr(g.user, key, value)
        db.session.commit()
        flash("Profile updated. Your matches have been refreshed.", "success")
        return redirect(url_for("dashboard"))
    u = g.user
    return render_template("profile.html", v=dict(branch=u.branch, semester=u.semester, cgpa=u.cgpa,
                           interests=u.interests, skills=u.skills, career_goal=u.career_goal))


@app.route("/roadmap", methods=["GET", "POST"])
@login_required
def roadmap():
    if request.method == "POST":
        if rate_limited(f"roadmap:{g.user.id}", limit=8):
            flash("You've generated several roadmaps this hour. Try again later.", "error")
            return redirect(url_for("roadmap"))
        try:
            weeks = min(24, max(4, int(request.form.get("weeks", 12))))
            hours = min(40, max(2, int(request.form.get("hours", 6))))
        except ValueError:
            abort(400, "Weeks and hours must be numbers.")
        recs, statuses = compute(g.user)
        data, used_ai = assistant.build_roadmap(g.user, live_recs(recs, statuses), weeks, hours)
        db.session.add(Roadmap(user_id=g.user.id, goal=g.user.career_goal, weeks=weeks, hours_per_week=hours,
                               used_ai=used_ai, content=json.dumps(data)))
        db.session.commit()
        return redirect(url_for("roadmap"))
    latest = Roadmap.query.filter_by(user_id=g.user.id).order_by(Roadmap.id.desc()).first()
    data = json.loads(latest.content) if latest else None
    opps = {o.id: o for o in Opportunity.query.all()}
    return render_template("roadmap.html", latest=latest, data=data, opps=opps)


@app.route("/advisor")
@login_required
def advisor():
    return render_template("advisor.html")


# ------------------------------------------------------------------ JSON API
@app.route("/api/opportunity/<int:opp_id>/fit", methods=["POST"])
@login_required
def api_fit(opp_id):
    if rate_limited(f"fit:{g.user.id}"):
        return jsonify(error="Too many AI requests this hour. Please try again later."), 429
    recs, _ = compute(g.user)
    rec = next((r for r in recs if r.id == opp_id), None)
    if rec is None:
        return jsonify(error="Opportunity not found."), 404
    text, used_ai = assistant.explain_fit(g.user, rec)
    return jsonify(text=text, ai=used_ai)


@app.route("/api/advisor", methods=["POST"])
@login_required
def api_advisor():
    if rate_limited(f"advisor:{g.user.id}", limit=40):
        return jsonify(error="Too many messages this hour. Please try again later."), 429
    payload = request.get_json(silent=True) or {}
    history = []
    for m in (payload.get("messages") or [])[-10:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            history.append({"role": m["role"], "content": m["content"][:2000]})
    while history and history[0]["role"] != "user":
        history.pop(0)
    if not history or history[-1]["role"] != "user":
        return jsonify(error="Send a question first."), 400
    recs, statuses = compute(g.user)
    text, used_ai = assistant.advisor_reply(g.user, live_recs(recs, statuses), history)
    return jsonify(reply=text, ai=used_ai)


@app.route("/api/recommendations")
@login_required
def api_recommendations():
    recs, statuses = compute(g.user)
    limit = min(50, max(1, request.args.get("limit", 10, type=int)))
    out = [{"id": r.id, "title": r.opportunity.title, "category": r.opportunity.category, "score": r.score,
            "components": {k: round(v, 2) for k, v in r.components.items()}, "reasons": r.reasons,
            "skills_to_build": r.missing_skills, "url": r.opportunity.url}
           for r in live_recs(recs, statuses) if r.eligible][:limit]
    return jsonify(recommendations=out)


# ------------------------------------------------------------------ admin
@app.route("/admin")
@admin_required
def admin():
    return render_template("admin.html", opportunities=Opportunity.query.order_by(Opportunity.id.desc()).all(),
                           users=User.query.order_by(User.id.desc()).all(), LEVELS=LEVELS, COSTS=COSTS, MODES=MODES)


@app.route("/admin/opportunity", methods=["POST"])
@admin_required
def admin_add_opportunity():
    f = request.form
    try:
        min_cgpa = float(f["min_cgpa"]) if f.get("min_cgpa") else None
        min_sem = int(f["min_semester"]) if f.get("min_semester") else None
        deadline = datetime.strptime(f["deadline"], "%Y-%m-%d").date() if f.get("deadline") else None
    except ValueError:
        flash("Check the CGPA, semester and deadline values.", "error")
        return redirect(url_for("admin"))
    title, desc = clip(f.get("title"), 160), clip(f.get("description"), 2000)
    if not title or not desc or f.get("category") not in CATEGORIES:
        flash("Title, description and category are required.", "error")
        return redirect(url_for("admin"))
    url = clip(f.get("url"), 500)
    if url and not url.startswith(("http://", "https://")):
        flash("The link must start with http:// or https://.", "error")
        return redirect(url_for("admin"))
    db.session.add(Opportunity(
        title=title, description=desc, category=f["category"], tags=clip(f.get("tags")),
        level=f.get("level") if f.get("level") in LEVELS else "Beginner",
        mode=f.get("mode") if f.get("mode") in MODES else "Online",
        cost=f.get("cost") if f.get("cost") in COSTS else "Free",
        duration=clip(f.get("duration"), 60) or None, branches=clip(f.get("branches"), 300),
        min_cgpa=min_cgpa, min_semester=min_sem, deadline=deadline, url=url or None))
    db.session.commit()
    flash(f"Added “{title}”.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/opportunity/<int:opp_id>/delete", methods=["POST"])
@admin_required
def admin_delete_opportunity(opp_id):
    opp = db.get_or_404(Opportunity, opp_id)
    Saved.query.filter_by(opportunity_id=opp.id).delete()
    db.session.delete(opp)
    db.session.commit()
    flash(f"Deleted “{opp.title}”.", "info")
    return redirect(url_for("admin"))


# ------------------------------------------------------------------ startup
def seed_opportunities():
    if Opportunity.query.count():
        return
    db.session.add_all(Opportunity(**row) for row in SAMPLE_OPPORTUNITIES)
    db.session.commit()


with app.app_context():
    db.create_all()
    seed_opportunities()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "1") == "1")
