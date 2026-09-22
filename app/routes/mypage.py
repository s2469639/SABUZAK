from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Product

bp = Blueprint("mypage", __name__, url_prefix="/mypage")

# 빠른 선택용 HS코드 프리셋 (README 제품군 기준)
HS_CODE_PRESETS = [
    {"name": "약과", "hs_code": "1905.90"},
    {"name": "유과", "hs_code": "1904.10"},
    {"name": "누룽지칩", "hs_code": "1904.10"},
    {"name": "김부각", "hs_code": "2106.90"},
    {"name": "고구마스틱", "hs_code": "2005.99"},
]


@bp.route("/")
@login_required
def index():
    products = (
        Product.query.filter_by(user_id=current_user.id)
        .order_by(Product.created_at.desc())
        .all()
    )
    return render_template(
        "mypage/mypage.html", products=products, hs_presets=HS_CODE_PRESETS
    )


@bp.route("/products", methods=["POST"])
@login_required
def add_product():
    name = request.form.get("name", "").strip()
    hs_code = request.form.get("hs_code", "").strip()
    ingredients = request.form.get("ingredients", "").strip()

    if name and hs_code:
        product = Product(
            user_id=current_user.id,
            name=name,
            hs_code=hs_code,
            ingredients=ingredients or None,
        )
        db.session.add(product)
        db.session.commit()

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
