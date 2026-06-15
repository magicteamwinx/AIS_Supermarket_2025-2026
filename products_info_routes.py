"""
Роутер «Каталог / Асортимент та склад».

Маршрут: /products-info  (саме його очікує меню у base.html — і для менеджера
«Асортимент та Склад», і для касира «Каталог»).

Один екран на дві ролі:
  • Касир   -> лише перегляд і пошук (К-1, К-2, К-4, К-5, К-12, К-13, К-14).
  • Менеджер -> те саме + керування наявністю в залі: виставити / редагувати /
    прибрати товар (Store_Product), що покриває М-9, М-10, М-13, М-14, М-15, М-16.

Список ведеться на рівні асортименту (Product), а наявність — похідний статус
від Store_Product.products_number:
    немає рядка Store_Product           -> "тільки в асортименті"
    є рядок, але SUM(products_number)=0 -> "розкуплено"
    SUM(products_number) > 0            -> "в наявності"

Реєстрація у main.py (додати два рядки):
    from products_info_routes import router as products_info_router
    app.include_router(products_info_router)
"""
import sqlite3

from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import get_db
from ui_routes import get_user_from_cookie  # cookie-based auth, як у dashboard

router = APIRouter()
templates = Jinja2Templates(directory="templates")

BASE_URL = "/products-info"


# ───────────────────────── helpers ─────────────────────────
def _status(sp_count: int, total_qty: int) -> str:
    if sp_count == 0:
        return "assort_only"      # занесено в довідник, але не виставлено в залу
    if total_qty == 0:
        return "sold_out"         # є UPC і ціна, але розкуплено
    return "in_stock"


def _redirect(msg: str | None = None, err: str | None = None) -> RedirectResponse:
    url = BASE_URL
    if msg:
        url += f"?msg={msg}"
    elif err:
        url += f"?err={err}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


# ───────────────────── GET /products-info (обидві ролі) ─────────────────────
@router.get("/products-info", response_class=HTMLResponse)
def catalog_page(
    request: Request,
    q: str | None = None,            # пошук за назвою АБО UPC  (К-4, К-14)
    category: str | None = None,     # фільтр за категорією      (К-5)
    promo: str = "all",              # all | promo | regular     (К-12, К-13)
    avail: str = "all",              # all | instock
    sort: str = "name",              # name | quantity | status
    msg: str | None = None,
    err: str | None = None,
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # порожній рядок із форми ("Усі категорії") -> None
    cat_id = int(category) if (category and category.strip().isdigit()) else None

    db.create_function("py_lower", 1, lambda x: x.lower() if x else x)
    cursor = db.cursor()

    base = """
        SELECT p.id_product, p.product_name, p.characteristics,
               p.category_number, c.category_name,
               COUNT(sp.UPC)                                         AS sp_count,
               COALESCE(SUM(sp.products_number), 0)                  AS total_qty,
               MAX(CASE WHEN sp.promotional_product=1 THEN 1 ELSE 0 END) AS has_promo,
               MIN(sp.selling_price)                                 AS min_price,
               MAX(sp.selling_price)                                 AS max_price
        FROM Product p
        JOIN Category c ON p.category_number = c.category_number
        LEFT JOIN Store_Product sp ON sp.id_product = p.id_product
    """
    where, params = [], []

    if cat_id:
        where.append("p.category_number = ?")
        params.append(cat_id)

    if q:
        where.append(
            "(py_lower(p.product_name) LIKE ? "
            "OR p.id_product IN (SELECT id_product FROM Store_Product WHERE UPC LIKE ?))"
        )
        params.append(f"%{q.lower()}%")
        params.append(f"%{q}%")

    if promo == "promo":
        where.append("p.id_product IN (SELECT id_product FROM Store_Product WHERE promotional_product = 1)")
    elif promo == "regular":
        where.append("p.id_product IN (SELECT id_product FROM Store_Product WHERE promotional_product = 0)")

    if where:
        base += " WHERE " + " AND ".join(where)

    base += " GROUP BY p.id_product"

    if avail == "instock":
        base += " HAVING total_qty > 0"
    elif avail == "out":
        base += " HAVING total_qty = 0"

    if sort == "quantity":
        base += " ORDER BY total_qty DESC, p.product_name"
    elif sort == "status":
        base += (" ORDER BY (CASE WHEN sp_count=0 THEN 2 "
                 "WHEN total_qty=0 THEN 1 ELSE 0 END), p.product_name")
    else:  # name
        base += " ORDER BY p.product_name"

    cursor.execute(base, params)
    rows = cursor.fetchall()

    cursor.execute("""
        SELECT id_product, UPC, UPC_prom, selling_price, products_number, promotional_product
        FROM Store_Product
        ORDER BY id_product, promotional_product
    """)
    details: dict[int, list] = {}
    for sp in cursor.fetchall():
        details.setdefault(sp["id_product"], []).append(dict(sp))

    products = []
    for r in rows:
        d = dict(r)
        d["status"] = _status(d["sp_count"], d["total_qty"])
        d["store_products"] = details.get(d["id_product"], [])
        products.append(d)

    cursor.execute("SELECT category_number, category_name FROM Category ORDER BY category_name")
    categories = cursor.fetchall()

    return templates.TemplateResponse(
        request=request,
        name="products_info.html",
        context={
            "user": current_user,
            "products": products,
            "categories": categories,
            "f": {"q": q or "", "category": cat_id, "promo": promo,
                  "avail": avail, "sort": sort},
            "msg": msg,
            "err": err,
        },
    )


# ───────────────────── менеджер: виставити товар у залу ─────────────────────
@router.post("/products-info/store-product/add")
def add_store_product(
    UPC: str = Form(...),
    id_product: int = Form(...),
    selling_price: float = Form(...),
    products_number: int = Form(...),
    promotional_product: str | None = Form(None),   # чекбокс -> "on"/None
    UPC_prom: str | None = Form(None),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Виставляти товар у залу може лише менеджер")

    is_promo = 1 if promotional_product else 0
    UPC_prom = UPC_prom or None
    cursor = db.cursor()
    try:
        # один товар -> максимум 2 позиції (звичайна + акційна), без дублю типу
        cursor.execute(
            "SELECT promotional_product FROM Store_Product WHERE id_product = ?",
            (id_product,),
        )
        existing = [row["promotional_product"] for row in cursor.fetchall()]
        if len(existing) >= 2:
            return _redirect(err="У товару вже є дві позиції в залі (звичайна та акційна)")
        if is_promo in existing:
            kind = "акційну" if is_promo else "звичайну"
            return _redirect(err=f"У товару вже є {kind} позицію в залі")

        cursor.execute("""
            INSERT INTO Store_Product
                (UPC, UPC_prom, id_product, selling_price, products_number, promotional_product)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (UPC, UPC_prom, id_product, selling_price, products_number, is_promo))
        db.commit()
        return _redirect(msg=f"Товар з UPC {UPC} виставлено в залу")
    except sqlite3.IntegrityError:
        db.rollback()
        return _redirect(err="Такий UPC уже існує або вказано неіснуючий товар")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}")


# ───────────────────── менеджер: редагувати позицію в залі ─────────────────────
@router.post("/products-info/store-product/update")
def update_store_product(
    UPC: str = Form(...),
    selling_price: float = Form(...),
    products_number: int = Form(...),
    promotional_product: str | None = Form(None),
    UPC_prom: str | None = Form(None),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Редагувати наявність може лише менеджер")

    is_promo = 1 if promotional_product else 0
    UPC_prom = UPC_prom or None
    cursor = db.cursor()
    try:
        cursor.execute("SELECT 1 FROM Store_Product WHERE UPC = ?", (UPC,))
        if not cursor.fetchone():
            return _redirect(err="Позицію в залі не знайдено")
        # Переоцінка: ціна зберігається в одному рядку на тип товару,
        # тож зміна selling_price автоматично діє на всі одиниці цього товару.
        cursor.execute("""
            UPDATE Store_Product
            SET selling_price = ?, products_number = ?,
                promotional_product = ?, UPC_prom = ?
            WHERE UPC = ?
        """, (selling_price, products_number, is_promo, UPC_prom, UPC))
        db.commit()
        return _redirect(msg=f"Позицію {UPC} оновлено")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}")


# ───────────────────── менеджер: прибрати позицію із зали ─────────────────────
@router.post("/products-info/store-product/delete")
def delete_store_product(
    UPC: str = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Прибирати товар із зали може лише менеджер")

    cursor = db.cursor()
    try:
        cursor.execute("SELECT 1 FROM Store_Product WHERE UPC = ?", (UPC,))
        if not cursor.fetchone():
            return _redirect(err="Позицію в залі не знайдено")
        cursor.execute("DELETE FROM Store_Product WHERE UPC = ?", (UPC,))
        db.commit()
        return _redirect(msg=f"Позицію {UPC} прибрано із зали")
    except sqlite3.IntegrityError:
        db.rollback()
        return _redirect(err="Не можна прибрати: товар уже фігурує в чеках")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}")