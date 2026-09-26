from datetime import datetime

from flask_login import UserMixin

from app.extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(64), unique=True, nullable=False)
    google_email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    company_name = db.Column(db.String(255))  # 메일 서명용 (예: 사부작)
    position = db.Column(db.String(120))  # 메일 서명용 직급 (예: 해외영업 대리)
    # AI 메일 생성 프롬프트에 쓰이는 제품/사업 설명. 이 앱에는 입력 UI가 없고,
    # 본 사부작 대시보드와 연동되면 그쪽 제품 데이터로 채워질 자리(연동 지점)만 남겨둔 필드.
    product_description = db.Column(db.Text)
    google_refresh_token = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contacts = db.relationship("Contact", backref="user", lazy=True)


class Exhibition(db.Model):
    """지금은 더미 데이터로만 채워둠. 나중에 사부작 본 프로젝트의 실제 박람회 데이터로 교체 예정."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contacts = db.relationship("Contact", backref="exhibition", lazy=True)


class EmailTemplate(db.Model):
    """로그인한 사용자 본인에게만 귀속되는 팔로업 메일 템플릿. 사용자마다 버전 1~3을 따로 가지며,
    그중 하나만 그 사용자의 발송에 쓰이는 활성(is_active) 버전이 된다."""

    __table_args__ = (db.UniqueConstraint("user_id", "version", name="uq_user_template_version"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(60))  # 예: 캐주얼 버전, 정중 버전
    subject = db.Column(db.String(255))
    body = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def display_name(self):
        return self.label or f"버전 {self.version}"


class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    exhibition_id = db.Column(db.Integer, db.ForeignKey("exhibition.id"), nullable=False)

    name = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255))
    position = db.Column(db.String(120))  # 예: 해외영업팀 대리
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(200))  # 여러 번호가 있으면 세미콜론으로 구분해 모두 저장
    address = db.Column(db.String(255))
    remarks = db.Column(db.Text)  # 자유 입력 비고
    preferred_template_version = db.Column(db.Integer)  # 이 바이어에게 쓸 템플릿 버전 (미지정 시 발송용 버전 사용)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    followup = db.relationship(
        "FollowupEmail", backref="contact", uselist=False, cascade="all, delete-orphan"
    )


class FollowupEmail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contact.id"), nullable=False)

    subject = db.Column(db.String(255))
    body = db.Column(db.Text)
    status = db.Column(db.String(20), default="draft")  # draft / edited / sent / failed
    template_version = db.Column(db.Integer)  # 이 내용이 어느 템플릿 버전에서 만들어졌는지
    generated_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)
    dismissed = db.Column(db.Boolean, default=False, nullable=False)  # "N일 경과" 알림을 확인 처리했는지
    # "새 메일 작성"으로 새 초안을 만들어도 언제 마지막으로 발송했는지 기록은 그대로 남겨두기 위한 필드.
    # sent_at/status는 지금 작성 중인 초안 상태를 나타내고, last_sent_at은 발송 이력을 나타낸다.
    last_sent_at = db.Column(db.DateTime)

# 채주현 바보바보