from datetime import date, datetime

from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(160), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    branch = db.Column(db.String(80), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    cgpa = db.Column(db.Float, nullable=False)
    interests = db.Column(db.String(500), nullable=False, default="")
    skills = db.Column(db.String(500), nullable=False, default="")
    career_goal = db.Column(db.String(120), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    saved = db.relationship("Saved", back_populates="user", cascade="all, delete-orphan")
    roadmaps = db.relationship("Roadmap", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def first_name(self):
        return (self.name.split() or [self.name])[0]

    @property
    def is_admin(self):
        return self.email in current_app.config.get("ADMIN_EMAILS", set())


class Opportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(500), nullable=False, default="")
    level = db.Column(db.String(20), nullable=False, default="Beginner")
    mode = db.Column(db.String(20), nullable=False, default="Online")
    cost = db.Column(db.String(20), nullable=False, default="Free")
    duration = db.Column(db.String(60), nullable=True)
    min_cgpa = db.Column(db.Float, nullable=True)
    branches = db.Column(db.String(300), nullable=True)  # comma-separated; blank = any
    min_semester = db.Column(db.Integer, nullable=True)
    deadline = db.Column(db.Date, nullable=True)
    url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def is_open(self):
        return self.deadline is None or self.deadline >= date.today()

    @property
    def days_left(self):
        return None if self.deadline is None else (self.deadline - date.today()).days


class Saved(db.Model):
    """A student's relationship to an opportunity: saved, in progress, completed or dismissed."""
    __table_args__ = (db.UniqueConstraint("user_id", "opportunity_id"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunity.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="saved")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="saved")
    opportunity = db.relationship("Opportunity")


class Roadmap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    goal = db.Column(db.String(120))
    weeks = db.Column(db.Integer, nullable=False)
    hours_per_week = db.Column(db.Integer, nullable=False)
    used_ai = db.Column(db.Boolean, default=False)
    content = db.Column(db.Text, nullable=False)  # JSON
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="roadmaps")
