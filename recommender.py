"""Hybrid recommender: TF-IDF semantic similarity + skill/interest/goal/level signals.

Eligibility rules (CGPA, semester, branch) are hard filters. Everything else feeds a
transparent 0-100 score whose components are returned so the UI can explain itself.
"""
import re
from collections import Counter
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from constants import ALIASES, GENERIC_TERMS, GOAL_KEYWORDS, LEVELS

WEIGHTS = {"semantic": 0.35, "interests": 0.20, "skills": 0.15, "goal": 0.20, "level": 0.10}


def norm_term(term):
    term = re.sub(r"\s+", " ", term.strip().lower())
    return ALIASES.get(term, term)


def terms(value):
    """Split free text like 'AI, ML; Python' into canonical, de-duplicated terms."""
    text = (value or "").lower().replace("ui/ux", "ui ux")
    out = []
    for part in re.split(r"[,;\n|]", text):
        t = norm_term(part)
        if t and t not in out:
            out.append(t)
    return out


def term_matches(a, b):
    """Equal, or the shorter phrase appears as whole words inside the longer one."""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 4 or short in GENERIC_TERMS:
        return False
    return re.search(rf"(?<!\w){re.escape(short)}(?!\w)", long_) is not None


def student_level(student):
    if student.semester <= 2:
        return 0
    return 1 if student.semester <= 5 else 2


def eligibility(student, item):
    """Return (eligible, blockers, near) where near means 'close to unlocking'."""
    blockers, near = [], True
    if item.min_cgpa is not None and student.cgpa < item.min_cgpa:
        blockers.append(f"Needs CGPA {item.min_cgpa:.1f}+ (yours is {student.cgpa:.2f})")
        near &= (item.min_cgpa - student.cgpa) <= 0.75
    if item.min_semester is not None and student.semester < item.min_semester:
        blockers.append(f"Opens in semester {item.min_semester} (you're in {student.semester})")
        near &= (item.min_semester - student.semester) <= 2
    allowed = [b.strip().lower() for b in (item.branches or "").split(",") if b.strip()]
    if allowed and student.branch.lower() not in allowed:
        blockers.append("Open to " + ", ".join(b.strip() for b in item.branches.split(",")))
        near = False
    return (not blockers), blockers, (bool(blockers) and near)


def semantic_scores(query, docs):
    if not docs or not query.strip():
        return [0.0] * len(docs)
    try:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        matrix = vec.fit_transform(docs)
        return cosine_similarity(vec.transform([query]), matrix).ravel().tolist()
    except ValueError:  # empty vocabulary
        return [0.0] * len(docs)


@dataclass
class Rec:
    opportunity: object
    score: int
    components: dict
    matched_interests: list = field(default_factory=list)
    matched_skills: list = field(default_factory=list)
    missing_skills: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    eligible: bool = True
    blockers: list = field(default_factory=list)
    near: bool = False
    peers: int = 0

    @property
    def id(self):
        return self.opportunity.id


def recommend(student, opportunities, popularity=None):
    """Score every opportunity for a student. Returns Rec objects sorted by score."""
    popularity = popularity or {}
    interests, skills = terms(student.interests), terms(student.skills)
    goal_kw = GOAL_KEYWORDS.get(student.career_goal, [])
    level_idx = student_level(student)

    student_doc = " ".join([student.interests or ""] * 2 + [student.skills or "", student.career_goal or ""] + goal_kw)
    docs = [" ".join([o.title, o.description, (o.tags + " ") * 2]) for o in opportunities]
    sims = semantic_scores(student_doc, docs)

    results = []
    for item, sim in zip(opportunities, sims):
        tags = terms(item.tags)
        m_int = [t for t in tags if any(term_matches(i, t) for i in interests)]
        m_skill = [t for t in tags if any(term_matches(s, t) for s in skills)]
        m_goal = [t for t in tags if any(term_matches(g, t) for g in goal_kw)]
        missing = [t for t in tags if t not in m_skill]

        cap = max(1, min(len(tags), 3))
        comp = {
            "semantic": min(1.0, sim * 2.5),
            "interests": min(1.0, len(m_int) / cap),
            "skills": min(1.0, len(m_skill) / cap),
            "goal": 0.5 if not goal_kw else min(1.0, len(m_goal) / 2),
        }
        try:
            item_level = LEVELS.index(item.level)
        except ValueError:
            item_level = 0
        comp["level"] = max(0.0, 1 - 0.4 * abs(item_level - level_idx))

        peers = popularity.get(item.id, 0)
        score = 100 * sum(WEIGHTS[k] * v for k, v in comp.items()) + min(5, 2 * peers)
        eligible, blockers, near = eligibility(student, item)

        reasons = []
        if m_int:
            reasons.append("Matches your interests: " + ", ".join(m_int))
        if m_skill:
            reasons.append("Builds on skills you have: " + ", ".join(m_skill))
        if m_goal:
            reasons.append(f"Supports your goal: {student.career_goal}")
        if comp["level"] >= 1:
            reasons.append(f"{item.level} level fits semester {student.semester}")
        elif comp["level"] <= 0.2:
            reasons.append(f"{item.level} level is a stretch for semester {student.semester}")
        if peers:
            reasons.append(f"{peers} other {student.branch} student{'s' if peers > 1 else ''} saved this")
        if not reasons:
            reasons.append("Broad option that may help you explore")

        results.append(Rec(item, min(100, round(score)), comp, m_int, m_skill, missing,
                           reasons, eligible, blockers, near, peers))
    return sorted(results, key=lambda r: (-r.score, r.opportunity.title))


def top_skill_gaps(recs, n=6, top=10):
    """Skills that appear most often across the best eligible matches and the student lacks."""
    counter = Counter()
    for r in [r for r in recs if r.eligible][:top]:
        for t in r.missing_skills:
            counter[t] += r.score
    return [t for t, _ in counter.most_common(n)]
