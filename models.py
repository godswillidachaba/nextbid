import logging
import secrets
from datetime import datetime, timedelta, timezone
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)
db = SQLAlchemy()


class Notice(db.Model):
    __tablename__ = 'notices'
    id = db.Column(db.Integer, primary_key=True)
    notice_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    title = db.Column(db.Text, default='')
    organization = db.Column(db.String(255), default='')
    country = db.Column(db.String(100), default='')
    deadline = db.Column(db.String(100), default='')
    deadline_date = db.Column(db.DateTime, nullable=True)
    reference = db.Column(db.String(100), default='')
    published = db.Column(db.String(100), default='')
    published_date = db.Column(db.DateTime, nullable=True)
    description = db.Column(db.Text, default='')
    url = db.Column(db.String(500), default='')
    source = db.Column(db.String(50), default='UNGM')
    scraped_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    batch_id = db.Column(db.String(30), nullable=True, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'notice_id': self.notice_id,
            'title': self.title,
            'organization': self.organization,
            'country': self.country,
            'deadline': self.deadline,
            'deadline_date': self.deadline_date.isoformat() if self.deadline_date else None,
            'reference': self.reference,
            'published': self.published,
            'published_date': self.published_date.isoformat() if self.published_date else None,
            'description': self.description,
            'url': self.url,
            'source': self.source,
            'scraped_at': self.scraped_at.isoformat() if self.scraped_at else None,
            'batch_id': self.batch_id,
        }


class BidAnalysis(db.Model):
    __tablename__ = 'bid_analyses'
    id = db.Column(db.Integer, primary_key=True)
    notice_id = db.Column(db.String(20), db.ForeignKey('notices.notice_id'), nullable=False, index=True)
    score = db.Column(db.Integer, default=0)
    strategic_fit = db.Column(db.Integer, default=0)
    geographic_fit = db.Column(db.Integer, default=0)
    past_performance_fit = db.Column(db.Integer, default=0)
    win_probability = db.Column(db.Integer, default=0)
    revenue_potential = db.Column(db.Integer, default=0)
    strategic_relationship_value = db.Column(db.Integer, default=0)
    relevant_unit = db.Column(db.String(100), default='')
    suggested_position = db.Column(db.String(50), default='Monitor')
    opportunity_type = db.Column(db.String(100), default='')
    funding_organization = db.Column(db.String(255), default='')
    geography = db.Column(db.String(255), default='')
    submission_deadline = db.Column(db.String(100), default='')
    estimated_budget = db.Column(db.String(100), default='')
    executive_summary = db.Column(db.Text, default='')
    why_it_fits = db.Column(db.Text, default='')
    risks = db.Column(db.Text, default='')
    red_flags = db.Column(db.Text, default='')
    consortium_possible = db.Column(db.Boolean, default=False)
    consortium_role = db.Column(db.String(100), default='')
    analysis_json = db.Column(db.JSON, default=dict)
    model_used = db.Column(db.String(100), default='')
    analyzed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notice = db.relationship('Notice', backref=db.backref('analysis', uselist=False))


class ScrapeRun(db.Model):
    __tablename__ = 'scrape_runs'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default='running')
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)
    notices_found = db.Column(db.Integer, default=0)
    notices_new = db.Column(db.Integer, default=0)
    analyses_completed = db.Column(db.Integer, default=0)
    emails_sent = db.Column(db.Integer, default=0)
    error = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'batch_id': self.batch_id,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'notices_found': self.notices_found,
            'notices_new': self.notices_new,
            'analyses_completed': self.analyses_completed,
            'emails_sent': self.emails_sent,
            'error': self.error,
        }


class EmailRecipient(db.Model):
    __tablename__ = 'email_recipients'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, default='')

    @classmethod
    def get(cls, key, default=''):
        row = db.session.query(cls).filter(cls.key == key).first()
        if row:
            return row.value
        return default

    @classmethod
    def set(cls, key, value):
        row = db.session.query(cls).filter(cls.key == key).first()
        if row:
            row.value = value
        else:
            row = cls(key=key, value=value)
            db.session.add(row)
        db.session.commit()
        return row


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(120), default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self):
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        return self.reset_token

    def clear_reset_token(self):
        self.reset_token = None
        self.reset_token_expires = None

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'name': self.name,
        }
