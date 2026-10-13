"""Shared constants: form choices, goal vocabularies and term aliases."""

BRANCHES = ["AIML", "Computer Engineering", "IT", "ENTC", "Mechanical", "Civil", "Other"]

GOALS = [
    "AI/ML Engineer", "Data Scientist", "Software Developer",
    "Cybersecurity Analyst", "UI/UX Designer", "Researcher", "Not sure yet",
]

CATEGORIES = [
    "Elective", "Course", "Certification", "Internship", "Hackathon",
    "Competition", "Scholarship", "Project", "Research", "Skill Resource",
]
LEVELS = ["Beginner", "Intermediate", "Advanced"]
MODES = ["Online", "Offline", "Hybrid"]
COSTS = ["Free", "Paid", "Varies"]

# status key -> label shown in the UI
STATUSES = {
    "saved": "Saved",
    "in_progress": "In progress",
    "completed": "Completed",
    "dismissed": "Not for me",
}

# Skills a student with this career goal is expected to build.
GOAL_KEYWORDS = {
    "AI/ML Engineer": ["machine learning", "deep learning", "artificial intelligence",
                       "python", "mlops", "large language models", "pytorch"],
    "Data Scientist": ["data science", "machine learning", "python", "sql", "statistics",
                       "data visualization", "pandas"],
    "Software Developer": ["web development", "software development", "data structures algorithms",
                           "git", "databases", "javascript", "flask"],
    "Cybersecurity Analyst": ["cybersecurity", "networking", "linux", "ethical hacking", "security"],
    "UI/UX Designer": ["ui ux", "figma", "design", "prototyping", "user research", "frontend"],
    "Researcher": ["research", "machine learning", "mathematics", "statistics", "academic writing", "deep learning"],
    "Not sure yet": [],
}

# Student-typed shorthand -> canonical term used in the catalogue.
ALIASES = {
    "ml": "machine learning", "ai": "artificial intelligence", "dl": "deep learning",
    "nlp": "natural language processing", "cv": "computer vision",
    "llm": "large language models", "llms": "large language models",
    "genai": "generative ai", "gen ai": "generative ai",
    "ui": "ui ux", "ux": "ui ux", "ui ux design": "ui ux", "ui/ux": "ui ux",
    "js": "javascript", "dsa": "data structures algorithms",
    "data structures": "data structures algorithms", "algorithms": "data structures algorithms",
    "iot": "internet of things", "cyber security": "cybersecurity", "infosec": "cybersecurity",
    "web dev": "web development", "webdev": "web development", "web": "web development",
    "front end": "frontend", "front-end": "frontend",
    "data analytics": "data analysis", "analytics": "data analysis",
    "ds": "data science", "devops": "devops", "k8s": "kubernetes",
    "py": "python", "reactjs": "react", "react.js": "react",
    "oss": "open source", "stats": "statistics", "maths": "mathematics", "math": "mathematics",
}

# Single words too generic to count as a match by containment ("data" in "data science").
GENERIC_TERMS = {"data", "web", "software", "learning", "computer", "design", "development", "engineering", "science"}
