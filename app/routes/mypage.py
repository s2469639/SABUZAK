import re

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.models import HsCodeMaster, Product

bp = Blueprint("mypage", __name__, url_prefix="/mypage")

# 4~10자리 숫자, 점(.) 유무나 자릿수 상관없이 허용 (예: 1905, 1905.90, 190590, 1904901000)
HS_CODE_FORMAT_RE = re.compile(r"^\d{2,4}(\.\d{1,4}){0,3}$|^\d{4,10}$")


def _hs_master_query_available():
    """scripts/market/load_excel.py 등을 아직 안 돌려서 hs0code_master 테이블이
    비어있는(또는 아예 없는) 환경에서도 검증을 건너뛰도록 확인한다.
    db.create_all()이 빈 테이블은 미리 만들어두기 때문에 테이블 존재 여부만으론
    부족하고, 실제로 행이 있는지까지 봐야 한다."""
    try:
        return HsCodeMaster.query.first() is not None
    except OperationalError:
        db.session.rollback()
        return False


@bp.route("/")
@login_required
def index():
    products = (
        Product.query.filter_by(user_id=current_user.id)
        .order_by(Product.created_at.desc())
        .all()
    )
    return render_template("mypage/mypage.html", products=products)


@bp.route("/hscode-search")
@login_required
def hscode_search():
    """제품명/HS코드로 관세청 마스터 데이터를 검색해 자동완성 후보를 반환."""
    q = request.args.get("q", "").strip()
    if len(q) < 1 or not _hs_master_query_available():
        return jsonify([])

    like = f"%{q}%"
    rows = (
        HsCodeMaster.query.filter(
            (HsCodeMaster.name_ko.ilike(like)) | (HsCodeMaster.hscode.ilike(like))
        )
        .limit(20)
        .all()
    )
    return jsonify(
        [{"hscode": r.hscode, "name_ko": r.name_ko or r.hsk_name} for r in rows]
    )


def _validate_hs_code(hs_code):
    if not HS_CODE_FORMAT_RE.match(hs_code):
        return False, "HS코드 형식이 올바르지 않습니다. (예: 1905.90)"

    if _hs_master_query_available():
        normalized = hs_code.replace(".", "")
        exists = HsCodeMaster.query.filter(
            HsCodeMaster.hscode.ilike(f"{normalized}%")
        ).first()
        if not exists:
            return False, "관세청 HS코드 목록에서 확인되지 않는 코드입니다. 다시 확인해주세요."

    return True, ""


# "next" 폼 필드로 넘어오는 값 -> 실제 리다이렉트할 엔드포인트.
# 화이트리스트 방식으로만 매핑해서, 임의의 URL로 리다이렉트되는 걸 막는다.
_NEXT_ENDPOINTS = {
    "dashboard": "dashboard.index",
    "mypage": "mypage.index",
}


def _next_redirect(default="mypage.index"):
    endpoint = _NEXT_ENDPOINTS.get(request.form.get("next"), default)
    return redirect(url_for(endpoint))


@bp.route("/products", methods=["POST"])
@login_required
def add_product():
    name = request.form.get("name", "").strip()
    hs_code = request.form.get("hs_code", "").strip()
    ingredients = request.form.get("ingredients", "").strip()
    target_price = request.form.get("target_price", "").strip()
    certifications = request.form.get("certifications", "").strip()
    strengths = request.form.get("strengths", "").strip()
    next_param = request.form.get("next")

    if name and hs_code:
        is_valid, error = _validate_hs_code(hs_code)
        if not is_valid:
            # 대시보드 모달에서 온 요청은 입력값을 그 자리에 다시 채워줄 방법이 없으니
            # (전체 페이지 이동이라) flash로만 에러를 보여주고 원래 페이지로 돌려보낸다.
            if next_param:
                flash(error, "danger")
                return _next_redirect()

            products = (
                Product.query.filter_by(user_id=current_user.id)
                .order_by(Product.created_at.desc())
                .all()
            )
            return render_template(
                "mypage/mypage.html",
                products=products,
                form_error=error,
                form_name=name,
                form_hs_code=hs_code,
                form_ingredients=ingredients,
                form_target_price=target_price,
                form_certifications=certifications,
                form_strengths=strengths,
            )

        product = Product(
            user_id=current_user.id,
            name=name,
            hs_code=hs_code,
            ingredients=ingredients or None,
            target_price=target_price or None,
            certifications=certifications or None,
            strengths=strengths or None,
        )
        db.session.add(product)
        db.session.commit()
        flash(f"'{name}' 제품을 등록했습니다.", "success")

    return _next_redirect()


@bp.route("/products/<int:product_id>/edit", methods=["POST"])
@login_required
def edit_product(product_id):
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()

    name = request.form.get("name", "").strip()
    hs_code = request.form.get("hs_code", "").strip()
    ingredients = request.form.get("ingredients", "").strip()
    target_price = request.form.get("target_price", "").strip()
    certifications = request.form.get("certifications", "").strip()
    strengths = request.form.get("strengths", "").strip()

    if not name or not hs_code:
        flash("제품명과 HS코드는 필수입니다.", "danger")
        return redirect(url_for("mypage.index"))

    is_valid, error = _validate_hs_code(hs_code)
    if not is_valid:
        flash(error, "danger")
        return redirect(url_for("mypage.index"))

    product.name = name
    product.hs_code = hs_code
    product.ingredients = ingredients or None
    product.target_price = target_price or None
    product.certifications = certifications or None
    product.strengths = strengths or None
    db.session.commit()
    flash(f"'{name}' 제품을 수정했습니다.", "success")

    return redirect(url_for("mypage.index"))


@bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@login_required
def toggle_product(product_id):
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    product.is_checked = not product.is_checked
    db.session.commit()
    return redirect(url_for("mypage.index"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product(product_id):
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for("mypage.index"))
