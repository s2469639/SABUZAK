from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    company = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self):
        return f"<User {self.email}>"


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    hs_code = db.Column(db.String(20), nullable=False)
    ingredients = db.Column(db.Text)
    is_checked = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("products", lazy=True))

    def __repr__(self):
        return f"<Product {self.name} ({self.hs_code})>"


class Exhibition(db.Model):
    __tablename__ = "raw_exhibitions"

    id = db.Column(db.Integer, primary_key=True)
    detail_url = db.Column(db.Text, nullable=False)
    name = db.Column(db.Text)
    start_date = db.Column(db.Integer)  # YYYYMMDD
    end_date = db.Column(db.Integer)  # YYYYMMDD
    country = db.Column(db.Text)
    city = db.Column(db.Text)
    venue = db.Column(db.Text)
    audience_note = db.Column(db.Text)
    audience_type = db.Column(db.Text)
    website = db.Column(db.Text)
    intro = db.Column(db.Text)
    category = db.Column(db.Text)
    continent = db.Column(db.Text)
    food_yn = db.Column(db.Integer)
    scale = db.Column(db.Text)
    keywords = db.Column(db.Text)
    intro_ko = db.Column(db.Text)
    classified_at = db.Column(db.Text)
    is_active = db.Column(db.Integer, default=1)
    last_updated_at = db.Column(db.Text)
    country_ko = db.Column(db.Text)

    def __repr__(self):
        return f"<Exhibition {self.name}>"


# ConceptDraft, ProposalDraft, Buyer 등 나머지 모델은
# 각 기능 구현 시 이 파일에 이어서 추가합니다.
