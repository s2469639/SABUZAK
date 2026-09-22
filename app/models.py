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


# Exhibition, ConceptDraft, ProposalDraft, Buyer 등 나머지 모델은
# 각 기능 구현 시 이 파일에 이어서 추가합니다.
