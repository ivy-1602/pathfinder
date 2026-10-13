"""Local assistant: fit explanations, advisor answers and roadmaps. No external APIs, no keys."""
import re

from recommender import semantic_scores, top_skill_gaps


def explain_fit(student, rec):
    item = rec.opportunity
    band = "Strong fit" if rec.score >= 60 else "Decent fit" if rec.score >= 35 else "Loose fit"
    parts = [f"{band} ({rec.score}/100)."]
    parts.append(" ".join(r.rstrip(".") + "." for r in rec.reasons[:2]))
    if rec.matched_skills:
        parts.append(f"You already have: {', '.join(rec.matched_skills)}.")
    if rec.missing_skills:
        parts.append(f"You'd build: {', '.join(rec.missing_skills[:4])}.")
    if rec.blockers:
        parts.append("Not open yet: " + "; ".join(rec.blockers) + ".")
    else:
        focus = rec.missing_skills[0] if rec.missing_skills else item.title
        parts.append(f"This week: open the resource and finish the first lesson on {focus}.")
    return " ".join(parts), False


def _bullets(recs, n=3):
    return "\n".join(f"- {r.opportunity.title} ({r.opportunity.category}, match {r.score}): {r.reasons[0]}"
                     for r in recs[:n])


def advisor_reply(student, recs, history):
    q = history[-1]["content"].lower()
    ok = [r for r in recs if r.eligible]
    if not ok:
        return "Nothing is open to you yet. Try adding interests or skills on your profile.", False

    def of(cats):
        return [r for r in ok if r.opportunity.category in cats]

    if re.search(r"intern|job|placement|hire", q):
        picks = of({"Internship", "Competition", "Hackathon", "Project"}) or ok
        return ("For internships, employers look at proof of work. Best options for you:\n" + _bullets(picks)
                + "\nBuild one public project and put it on your resume."), False
    if re.search(r"skill|learn first|what to learn|gap", q):
        gaps = top_skill_gaps(ok, n=4)
        return ("Skills that would unlock the most of your top matches: " + ", ".join(gaps) + ".\n"
                + "Start with the first one, then pick a matching item:\n" + _bullets(ok, 2)), False
    if re.search(r"certif", q):
        return "Certifications that fit you:\n" + _bullets(of({"Certification"}) or ok), False
    if re.search(r"scholar|fund|money|fee", q):
        return "Funding options in the catalogue:\n" + _bullets(of({"Scholarship"}) or ok), False
    if re.search(r"free|cheap|cost", q):
        free = [r for r in ok if r.opportunity.cost == "Free"]
        return "Best free options for you:\n" + _bullets(free or ok), False
    if re.search(r"hackathon|compet", q):
        return "Good ways to practise under pressure:\n" + _bullets(of({"Hackathon", "Competition"}) or ok), False
    if re.search(r"focus|semester|next|start|plan|roadmap", q):
        gaps = top_skill_gaps(ok, n=3)
        return (f"For semester {student.semester} toward {student.career_goal}, focus on {', '.join(gaps)}.\n"
                + "Top matches:\n" + _bullets(ok, 3) + "\nUse the Roadmap page for a week-by-week plan."), False
    # Fallback: semantic search of the question against the catalogue
    docs = [f"{r.opportunity.title} {r.opportunity.description} {r.opportunity.tags}" for r in ok]
    scores = semantic_scores(q, docs)
    ranked = sorted(zip(scores, ok), key=lambda p: -p[0])
    hits = [r for s, r in ranked if s > 0.05][:3]
    if hits:
        return "These catalogue items are closest to your question:\n" + _bullets(hits), False
    return ("I can help with: what to focus on, which skill to learn first, internships, certifications, "
            "free options, hackathons or scholarships. Try one of those."), False


def build_roadmap(student, recs, weeks, hours):
    pool = [r for r in recs if r.eligible and r.opportunity.is_open][:14]
    gaps = top_skill_gaps(pool, n=6)
    third = max(1, weeks // 3)
    learn = [r for r in pool if r.opportunity.category in ("Course", "Elective", "Skill Resource", "Certification")]
    build = [r for r in pool if r.opportunity.category in ("Project", "Research")]
    show = [r for r in pool if r.opportunity.category in ("Internship", "Hackathon", "Competition", "Scholarship")]
    ids = lambda rs: [r.opportunity.id for r in rs[:3]]
    return {
        "summary": f"A {weeks}-week plan at {hours} h/week towards {student.career_goal}, built from your top matches.",
        "skills_to_build": gaps,
        "phases": [
            {"title": "Build foundations", "weeks": f"Weeks 1-{third}",
             "goal": "Close the biggest skill gaps in your top matches.",
             "tasks": [f"Study {g} for about {max(1, hours // 3)} hours" for g in gaps[:3]]
                      or ["Pick one course below and finish its first module"],
             "milestone": "Finish one structured course or tutorial.", "resource_ids": ids(learn)},
            {"title": "Apply it in a project", "weeks": f"Weeks {third + 1}-{2 * third}",
             "goal": "Turn what you learned into something you can show.",
             "tasks": ["Scope a small project using your new skills", "Publish the code on GitHub with a clear README",
                       "Ask a friend or mentor to review it"],
             "milestone": "A public project with a README.", "resource_ids": ids(build or learn[3:])},
            {"title": "Show your work", "weeks": f"Weeks {2 * third + 1}-{weeks}",
             "goal": "Put your skills in front of others.",
             "tasks": ["Update your resume and LinkedIn with the project",
                       "Enter a hackathon or competition, or apply to a programme",
                       "Write a short post about what you built"],
             "milestone": "One submission or application sent.", "resource_ids": ids(show)},
        ],
    }, False
