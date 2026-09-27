import io
import re

import openpyxl
from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, url_for
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
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
    # 체크된 제품을 위로 모으고, 각 그룹 안에서는 최근 등록순
    products = (
        Product.query.filter_by(user_id=current_user.id)
        .order_by(Product.is_checked.desc(), Product.created_at.desc())
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
    brand = request.form.get("brand", "").strip()
    product_form = request.form.get("product_form", "").strip()
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
                .order_by(Product.is_checked.desc(), Product.created_at.desc())
                .all()
            )
            return render_template(
                "mypage/mypage.html",
                products=products,
                form_error=error,
                form_name=name,
                form_hs_code=hs_code,
                form_brand=brand,
                form_product_form=product_form,
                form_ingredients=ingredients,
                form_target_price=target_price,
                form_certifications=certifications,
                form_strengths=strengths,
            )

        product = Product(
            user_id=current_user.id,
            name=name,
            hs_code=hs_code,
            brand=brand or None,
            product_form=product_form or None,
            ingredients=ingredients or None,
            target_price=target_price or None,
            certifications=certifications or None,
            strengths=strengths or None,
            is_checked=not _has_selected_product(),
        )
        db.session.add(product)
        db.session.commit()

    return _next_redirect()


# 엑셀 일괄등록 헤더 -> Product 필드. 한글 헤더 이름으로 매칭해서, 사용자가
# 엑셀 첫 행에 이 이름 그대로(순서 무관) 컬럼을 두면 자동 인식한다.
_BULK_UPLOAD_COLUMNS = {
    "제품명": "name",
    "hs코드": "hs_code",
    "hs 코드": "hs_code",
    "hs code": "hs_code",
    "hscode": "hs_code",
    "hs_code": "hs_code",
    "hs-code": "hs_code",
    "브랜드명": "brand",
    "브랜드": "brand",
    "제품 형태": "product_form",
    "제품형태": "product_form",
    "원재료": "ingredients",
    "원료": "ingredients",
    "주요 원료": "ingredients",
    "주요원료": "ingredients",
    "성분": "ingredients",
    "성분표": "ingredients",
    "보유 인증": "certifications",
    "보유인증": "certifications",
    "인증": "certifications",
    "가격": "target_price",
    "목표 소매 가격대/단위중량": "target_price",
    "제품 강점": "strengths",
    "강점": "strengths",
}

# 엑셀 양식 다운로드의 열 제목. 위 _BULK_UPLOAD_COLUMNS가 인식하는 이름과
# 같아야 받은 양식을 채워서 그대로 올릴 수 있다 ("제품명 *"처럼 표시를 붙이면
# 인식이 안 되므로 필수 항목은 제목 칸 색으로만 구분).
_BULK_TEMPLATE_HEADERS = ["제품명", "HS코드", "브랜드명", "제품 형태", "원재료", "보유 인증", "가격", "제품 강점"]
_BULK_TEMPLATE_REQUIRED = {"제품명", "HS코드"}
_BULK_TEMPLATE_WIDE = {"원재료", "제품 강점"}
_BULK_TEMPLATE_ROWS = 500  # HS코드 텍스트 형식을 미리 지정해둘 행 수


@bp.route("/products/bulk-template")
@login_required
def download_bulk_template():
    """엑셀 일괄등록용 빈 양식(열 제목만 채움)을 그 자리에서 만들어 내려준다."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "제품 목록"
    ws.append(_BULK_TEMPLATE_HEADERS)
    for col, header in enumerate(_BULK_TEMPLATE_HEADERS, start=1):
        cell = ws.cell(row=1, column=col)
        is_required = header in _BULK_TEMPLATE_REQUIRED
        cell.font = Font(bold=True, color="FFFFFF" if is_required else "374151")
        cell.fill = PatternFill("solid", fgColor="EA580C" if is_required else "F3F4F6")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = 36 if header in _BULK_TEMPLATE_WIDE else 18
    # 엑셀이 1902.30을 숫자로 보고 1902.3으로 끝자리 0을 지우지 않게 HS코드 칸은 텍스트 형식
    hs_col = _BULK_TEMPLATE_HEADERS.index("HS코드") + 1
    for row in range(2, _BULK_TEMPLATE_ROWS + 2):
        ws.cell(row=row, column=hs_col).number_format = "@"
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="제품_일괄등록_양식.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/products/bulk-upload", methods=["POST"])
@login_required
def bulk_upload_products():
    file = request.files.get("bulk_file")
    if not file or not file.filename:
        flash("업로드할 엑셀 파일을 선택해주세요.", "danger")
        return redirect(url_for("mypage.index"))

    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        flash("엑셀(.xlsx) 파일만 업로드할 수 있습니다.", "danger")
        return redirect(url_for("mypage.index"))

    try:
        wb = openpyxl.load_workbook(file, data_only=True, read_only=True)
        ws = wb[wb.sheetnames[0]]
        rows_iter = ws.iter_rows(values_only=True)
        header = next(rows_iter, None)
    except Exception as e:
        flash(f"엑셀 파일을 읽는 중 오류가 발생했습니다: {e}", "danger")
        return redirect(url_for("mypage.index"))

    if not header:
        flash("엑셀 파일에 데이터가 없습니다.", "danger")
        return redirect(url_for("mypage.index"))

    col_map = {}  # 컬럼 인덱스 -> Product 필드명
    for i, cell in enumerate(header):
        key = str(cell or "").strip().lower()
        field = _BULK_UPLOAD_COLUMNS.get(key)
        if field:
            col_map[i] = field

    if "name" not in col_map.values() or "hs_code" not in col_map.values():
        flash(
            "엑셀 첫 행에 '제품명'과 'HS코드' 컬럼이 있어야 합니다. "
            "(인식된 컬럼: " + ", ".join(str(header[i]) for i in col_map) + ")",
            "danger",
        )
        return redirect(url_for("mypage.index"))

    added, skipped = 0, []
    has_selected = _has_selected_product()  # 분석 제품이 없으면 첫 번째로 등록되는 제품만 선택
    for row_num, row in enumerate(rows_iter, start=2):
        values = {field: str(row[i]).strip() if row[i] is not None else "" for i, field in col_map.items()}
        name = values.get("name", "")
        hs_code = values.get("hs_code", "")
        if not name and not hs_code:
            continue  # 빈 행은 조용히 건너뜀
        if not name or not hs_code:
            skipped.append(f"{row_num}행 (제품명/HS코드 누락)")
            continue

        is_valid, error = _validate_hs_code(hs_code)
        if not is_valid:
            skipped.append(f"{row_num}행 '{name}' ({error})")
            continue

        db.session.add(Product(
            user_id=current_user.id,
            name=name,
            hs_code=hs_code,
            brand=values.get("brand") or None,
            product_form=values.get("product_form") or None,
            ingredients=values.get("ingredients") or None,
            target_price=values.get("target_price") or None,
            certifications=values.get("certifications") or None,
            strengths=values.get("strengths") or None,
            is_checked=not has_selected,
        ))
        has_selected = True
        added += 1

    db.session.commit()

    # 성공 시엔 목록에 바로 보이므로 따로 알리지 않고, 문제가 있을 때만 안내한다
    if skipped:
        flash(f"건너뛴 행 {len(skipped)}개: " + " / ".join(skipped[:10]), "danger")
    if not added and not skipped:
        flash("등록할 제품 데이터가 없습니다.", "danger")

    return redirect(url_for("mypage.index"))


@bp.route("/products/<int:product_id>/edit", methods=["POST"])
@login_required
def edit_product(product_id):
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()

    name = request.form.get("name", "").strip()
    hs_code = request.form.get("hs_code", "").strip()
    brand = request.form.get("brand", "").strip()
    product_form = request.form.get("product_form", "").strip()
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
    product.brand = brand or None
    product.product_form = product_form or None
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
    """분석 제품 선택. 시장 분석·트렌드·부스 컨셉은 한 번에 제품 1개만 다루므로,
    이 제품을 고르면 나머지는 해제한다. 이 제품 하나만 분석 제품일 때 다시 누르면
    해제 (예전에 여러 개가 선택된 상태라면 누른 제품 하나만 남긴다)."""
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    others = Product.query.filter(
        Product.user_id == current_user.id, Product.id != product.id, Product.is_checked == True,  # noqa: E712
    )
    if product.is_checked and others.count() == 0:
        product.is_checked = False
    else:
        others.update({"is_checked": False})
        product.is_checked = True
    db.session.commit()
    return redirect(url_for("mypage.index"))


def _has_selected_product():
    """이미 분석 제품이 있으면 새로 등록하는 제품은 선택 안 된 채로 둔다
    (Product.is_checked의 DB 기본값이 True라서 등록 코드에서 직접 정한다)."""
    return Product.query.filter_by(user_id=current_user.id, is_checked=True).first() is not None


@bp.route("/products/bulk-delete", methods=["POST"])
@login_required
def bulk_delete_products():
    """'전체 선택'/삭제용 체크박스로 고른 내 제품들을 한 번에 삭제한다. 하나씩
    지워야 연결된 트렌드 조사 기록(TrendResult)도 delete_product와 똑같이 같이 지워진다."""
    ids = [int(i) for i in request.form.getlist("product_ids") if i.isdigit()]
    if ids:
        for product in Product.query.filter(Product.user_id == current_user.id, Product.id.in_(ids)).all():
            db.session.delete(product)
        db.session.commit()
    return redirect(url_for("mypage.index"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product(product_id):
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for("mypage.index"))
