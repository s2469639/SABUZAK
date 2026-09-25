import re
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(db.Model, UserMixin):
    __bind_key__ = "app_data"  # instance/app_data.db (로그인/유저 데이터 전용)
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    company = db.Column(db.String(150))
    position = db.Column(db.String(120))  # 바이어 메일 서명용 직급 (예: 해외영업 대리)
    product_description = db.Column(db.Text)  # 바이어 메일 AI 생성에 쓰이는 제품/사업 설명
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 바이어 메일 발송용 Gmail 연동 (본인 Gmail API로 팔로업 메일을 보내기 위한 것으로,
    # 이메일/비밀번호 로그인과는 별개로 /buyers/gmail/connect 에서 선택적으로 연결한다)
    google_email = db.Column(db.String(255))
    google_refresh_token = db.Column(db.Text)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self):
        return f"<User {self.email}>"


class Product(db.Model):
    __bind_key__ = "app_data"  # instance/app_data.db (로그인/유저 데이터 전용)
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    hs_code = db.Column(db.String(20), nullable=False)
    ingredients = db.Column(db.Text)
    target_price = db.Column(db.String(100))  # 목표 소매 가격대/단위중량 (예: "4.99 GBP / 350g")
    certifications = db.Column(db.String(200))  # 보유 인증 (예: "비건, 코셔, HACCP")
    strengths = db.Column(db.Text)  # 식감/가공 메커니즘
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
    image_url = db.Column(db.Text)
    hero_image_url = db.Column(db.Text)
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

    _DETAIL_URL_FAIR_ID_RE = re.compile(r"-M(\d+)/")

    @staticmethod
    def duplicate_ids():
        """tradefairdates.com이 같은 박람회를 도시 페이지만 다르게 두 번 올려두는
        경우가 있다 (예: Café & Brasserie Expo Indonesia가 detail_url의 박람회
        번호는 같은 "M2727"인데 /Jakarta.html, /Tangerang.html로 각각 따로 등록됨).

        이름만으로 묶으면 안 된다 — "Aux Vignobles!"처럼 여러 도시에서 열리는
        진짜 별개의 지역 박람회 시리즈가 이름을 공유하는 경우가 많아서, 이름
        기준으로 중복 판정하면 서로 다른 박람회를 잘못 지워버린다. 대신
        detail_url 안의 "-M<번호>/" 부분(tradefairdates.com이 매기는 박람회 고유
        번호)이 같은 것끼리만 진짜 중복으로 보고, 그중 가장 완성도 높은(분류·번역
        완료된, 그중 id가 가장 작은) 것 하나만 남기고 나머지 id를 돌려준다."""
        rows = (
            db.session.query(Exhibition.id, Exhibition.detail_url, Exhibition.classified_at)
            .filter(Exhibition.is_active == 1)
            .all()
        )
        groups = {}
        for expo_id, detail_url, classified_at in rows:
            m = Exhibition._DETAIL_URL_FAIR_ID_RE.search(detail_url or "")
            if not m:
                continue
            groups.setdefault(m.group(1), []).append((classified_at is None, expo_id))

        dup_ids = []
        for items in groups.values():
            if len(items) < 2:
                continue
            items.sort()
            dup_ids.extend(expo_id for _, expo_id in items[1:])
        return dup_ids


class HsCodeMaster(db.Model):
    """scripts/market/load_excel.py, make_db.py 로 관세청 HS부호 엑셀을 적재한
    hs0code_master 테이블. 명시적 PK 컬럼이 없어 SQLite의 암시적 rowid를 PK로 사용."""

    __bind_key__ = "hscode_data"  # instance/hscode.db (HS코드·관세 데이터 전용)
    __tablename__ = "hs0code_master"

    rowid = db.Column("rowid", db.Integer, primary_key=True)
    hscode = db.Column(db.Text)
    hsk_name = db.Column(db.Text)
    name_ko = db.Column(db.Text)

    def __repr__(self):
        return f"<HsCodeMaster {self.hscode} {self.name_ko}>"


class NtmMeasure(db.Model):
    """macmap.org 의 ntm-measures API 결과를 캐싱하는 테이블.
    scripts/market/sync_ntm_cache.py 가 배치로 채워넣고, 웹앱은 이 테이블만 읽는다
    (macmap을 페이지 로드마다 직접 호출하지 않음)."""

    __bind_key__ = "hscode_data"  # instance/hscode.db (HS코드·관세 데이터 전용)
    __tablename__ = "ntm_measures"

    id = db.Column(db.Integer, primary_key=True)
    reporter = db.Column(db.String(10), nullable=False)  # 수입국 UN M49 코드
    partner = db.Column(db.String(10), nullable=False)  # 수출국(한국=410)
    product = db.Column(db.String(20), nullable=False)  # 조회에 사용한 HS 코드
    measure_code = db.Column(db.Text)
    measure_section = db.Column(db.Text)
    measure_title = db.Column(db.Text)
    measure_summary = db.Column(db.Text)
    legislation_title = db.Column(db.Text)
    legislation_summary = db.Column(db.Text)
    implementation_authority = db.Column(db.Text)
    start_date = db.Column(db.Text)
    end_date = db.Column(db.Text)
    web_link = db.Column(db.Text)
    data_source = db.Column(db.Text)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<NtmMeasure {self.reporter}/{self.product} {self.measure_title}>"


class ConceptDraft(db.Model):
    """부스 컨셉 기획 초안. '부스 컨셉 기획' 버튼을 누르면 박람회당 1개씩 생성되고,
    사이드바 '작성 중인 박람회'에서 진행 상태를 확인/이어서 작성한다."""

    __bind_key__ = "app_data"  # instance/app_data.db (유저 데이터 전용)
    __tablename__ = "concept_drafts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    exhibition_id = db.Column(db.Integer, nullable=False)  # raw_exhibitions.id (다른 DB라 FK 불가)
    exhibition_name = db.Column(db.String(255))  # 목록 표시용 스냅샷 (다른 DB 조인 불가하므로 복제 저장)
    exhibition_country = db.Column(db.String(100))
    status = db.Column(db.String(20), default="concept", nullable=False)  # concept | proposal | done
    theme = db.Column(db.Text)
    slogan = db.Column(db.Text)
    description = db.Column(db.Text)
    selling_points = db.Column(db.Text)  # JSON: [{badge, title, description}, ...]
    events = db.Column(db.Text)  # JSON: [{id, tag, title, schedule, description}, ...]
    target_buyers = db.Column(db.Text)  # JSON: ["...", ...]
    image_prompt = db.Column(db.Text)  # 3D 렌더링용 완성형 영문 프롬프트
    image_path = db.Column(db.Text)  # 생성된 이미지의 static 상대경로 (예: generated/concept/12.png)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("concept_drafts", lazy=True))

    def __repr__(self):
        return f"<ConceptDraft {self.exhibition_name} ({self.status})>"


class EmailTemplate(db.Model):
    """로그인한 사용자 본인에게만 귀속되는 바이어 팔로업 메일 템플릿. 사용자마다 버전 1~3을
    따로 가지며, 그중 하나만 그 사용자의 발송에 쓰이는 활성(is_active) 버전이 된다."""

    __bind_key__ = "app_data"  # instance/app_data.db (유저 데이터 전용)
    __tablename__ = "email_templates"
    __table_args__ = (db.UniqueConstraint("user_id", "version", name="uq_user_template_version"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(60))  # 예: 캐주얼 버전, 정중 버전
    subject = db.Column(db.String(255))
    body = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("email_templates", lazy=True))

    @property
    def display_name(self):
        return self.label or f"버전 {self.version}"


class Contact(db.Model):
    """박람회에서 만난 바이어 연락처."""

    __bind_key__ = "app_data"  # instance/app_data.db (유저 데이터 전용)
    __tablename__ = "buyer_contacts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    exhibition_id = db.Column(db.Integer, nullable=False)  # raw_exhibitions.id (다른 DB라 FK 불가)
    exhibition_name = db.Column(db.String(255))  # 목록 표시용 스냅샷 (다른 DB 조인 불가하므로 복제 저장)

    name = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255))
    position = db.Column(db.String(120))  # 예: 해외영업팀 대리
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(200))  # 여러 번호가 있으면 세미콜론으로 구분해 모두 저장
    address = db.Column(db.String(255))
    remarks = db.Column(db.Text)  # 자유 입력 비고
    preferred_template_version = db.Column(db.Integer)  # 이 바이어에게 쓸 템플릿 버전 (미지정 시 발송용 버전 사용)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("buyer_contacts", lazy=True))
    followup = db.relationship(
        "FollowupEmail", backref="contact", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Contact {self.name} ({self.email})>"


class FollowupEmail(db.Model):
    __bind_key__ = "app_data"  # instance/app_data.db (유저 데이터 전용)
    __tablename__ = "followup_emails"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("buyer_contacts.id"), nullable=False)

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


class FollowupAttachment(db.Model):
    """팔로업 메일에 첨부한 파일. 실제 파일은 instance/attachments/<followup_id>/ 아래에
    (웹으로 직접 접근 불가한 위치) 저장하고, 여기엔 원본 파일명과 저장된 이름만 기록한다."""

    __bind_key__ = "app_data"  # instance/app_data.db (유저 데이터 전용)
    __tablename__ = "followup_attachments"

    id = db.Column(db.Integer, primary_key=True)
    followup_id = db.Column(db.Integer, db.ForeignKey("followup_emails.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)  # 원본 파일명 (한글 가능, 메일에 이 이름으로 첨부)
    stored_name = db.Column(db.String(100), nullable=False)  # 디스크에 저장된 이름 (uuid)
    content_type = db.Column(db.String(150))
    size = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    followup = db.relationship(
        "FollowupEmail",
        backref=db.backref("attachments", cascade="all, delete-orphan", order_by="FollowupAttachment.id"),
    )

    @property
    def size_label(self):
        if self.size >= 1024 * 1024:
            return f"{self.size / (1024 * 1024):.1f}MB"
        return f"{max(1, round(self.size / 1024))}KB"


# ProposalDraft 등 나머지 모델은
# 각 기능 구현 시 이 파일에 이어서 추가합니다.
