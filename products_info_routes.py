"""
Роутер «Каталог / Асортимент та склад».  Маршрут: /products-info

Три вкладки (= три різні сутності й три вимоги ТЗ):
  • tab=products   -> усі БАЗОВІ товари (Product), відсортовані за назвою      (М-9 / К-1)
                      разом із позначкою, чи виставлено товар у залу
                      (показує й товари, яких ЗАРАЗ немає в магазині)
  • tab=store      -> усі товари В МАГАЗИНІ (Store_Product), сорт. за кількістю (М-10 / К-2)
  • tab=categories -> усі категорії (Category), відсортовані за назвою          (М-8) — лише менеджер

Ролі:
  • Касир   -> лише перегляд і пошук.
  • Менеджер -> те саме + керування наявністю в залі (виставити / змінити / прибрати)
               і вкладка «Категорії».

Реєстрація у main.py:
    from products_info_routes import router as products_info_router
    app.include_router(products_info_router)
"""
import sqlite3

from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import get_db
from ui_routes import get_user_from_cookie

router = APIRouter()
templates = Jinja2Templates(directory="templates")

BASE_URL = "/products-info"


def _redirect(msg: str | None = None, err: str | None = None, tab: str = "store") -> RedirectResponse:
    url = f"{BASE_URL}?tab={tab}"
    if msg:
        url += f"&msg={msg}"
    elif err:
        url += f"&err={err}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/products-info", response_class=HTMLResponse)
def catalog_page(
    request: Request,
    tab: str = "store",              # products | store | categories
    q: str | None = None,            # пошук (назва, а на вкладці "store" — ще й UPC)
    category: str | None = None,     # фільтр за категорією
    promo: str = "all",              # all | promo | regular   (вкладка store)
    avail: str = "all",              # all | instock | out      (вкладка store)
    sort: str | None = None,         # store: quantity | name
    msg: str | None = None,
    err: str | None = None,
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    is_manager = current_user["role"] == "Менеджер"
    # категорії — лише для менеджера; інакше повертаємось на "Наявність"
    if tab == "categories" and not is_manager:
        tab = "store"
    if tab not in ("products", "store", "categories"):
        tab = "store"

    cat_id = int(category) if (category and category.strip().isdigit()) else None
    db.create_function("py_lower", 1, lambda x: x.lower() if x else x)
    cursor = db.cursor()

    # категорії (для випадаючих списків і вкладки "categories"), відсортовані за назвою
    cursor.execute("SELECT category_number, category_name FROM Category ORDER BY category_name")
    categories = [dict(r) for r in cursor.fetchall()]

    # повний перелік товарів для випадаючого списку у формі "виставити в залу"
    cursor.execute("SELECT id_product, product_name FROM Product ORDER BY product_name")
    all_products = cursor.fetchall()

    products, store, cat_rows = [], [], []

    # ── вкладка "Товари" (М-9 / К-1): усі базові товари ──
    if tab == "products":
        if sort not in ("name", "category"):
            sort = "name"
        query = """
            SELECT p.id_product, p.product_name, p.characteristics,
                   p.category_number, c.category_name,
                   (SELECT COUNT(*) FROM Store_Product sp WHERE sp.id_product = p.id_product) AS hall_pos,
                   (SELECT COALESCE(SUM(products_number), 0) FROM Store_Product sp WHERE sp.id_product = p.id_product) AS hall_qty
            FROM Product p
            JOIN Category c ON p.category_number = c.category_number
        """
        conds, params = [], []
        if cat_id:
            conds.append("p.category_number = ?")
            params.append(cat_id)
        if q:
            conds.append("py_lower(p.product_name) LIKE ?")
            params.append(f"%{q.lower()}%")
        if conds:
            query += " WHERE " + " AND ".join(conds)
        if sort == "category":
            query += " ORDER BY c.category_name, p.product_name"
        else:  # name
            query += " ORDER BY p.product_name"
        cursor.execute(query, params)
        products = [dict(r) for r in cursor.fetchall()]

    # ── вкладка "Наявність у залі" (М-10 / К-2): усі Store_Product ──
    elif tab == "store":
        if sort not in ("quantity", "name"):
            sort = "name"   # М-10: за замовчуванням сортуємо за назвою
        query = """
            SELECT sp.UPC, sp.UPC_prom, sp.id_product, sp.selling_price,
                   sp.products_number, sp.promotional_product,
                   p.product_name, p.characteristics, c.category_name, p.category_number
            FROM Store_Product sp
            JOIN Product p ON sp.id_product = p.id_product
            JOIN Category c ON p.category_number = c.category_number
        """
        conds, params = [], []
        if cat_id:
            conds.append("p.category_number = ?")
            params.append(cat_id)
        if q:
            conds.append("(py_lower(p.product_name) LIKE ? OR sp.UPC LIKE ?)")
            params.append(f"%{q.lower()}%")
            params.append(f"%{q}%")
        if promo == "promo":
            conds.append("sp.promotional_product = 1")
        elif promo == "regular":
            conds.append("sp.promotional_product = 0")
        if avail == "instock":
            conds.append("sp.products_number > 0")
        elif avail == "out":
            conds.append("sp.products_number = 0")
        if conds:
            query += " WHERE " + " AND ".join(conds)
        if sort == "name":
            query += " ORDER BY p.product_name"
        else:  # quantity
            query += " ORDER BY sp.products_number DESC, p.product_name"
        cursor.execute(query, params)
        store = [dict(r) for r in cursor.fetchall()]

    # ── вкладка "Категорії" (М-8): усі категорії, пошук + сортування ──
    elif tab == "categories":
        if sort not in ("name", "number"):
            sort = "name"
        query = "SELECT category_number, category_name FROM Category"
        params = []
        if q:
            query += " WHERE py_lower(category_name) LIKE ?"
            params.append(f"%{q.lower()}%")
        query += " ORDER BY category_number" if sort == "number" else " ORDER BY category_name"
        cursor.execute(query, params)
        cat_rows = [dict(r) for r in cursor.fetchall()]

    if sort is None:
        sort = "quantity"

    return templates.TemplateResponse(
        request=request,
        name="products_info.html",
        context={
            "user": current_user,
            "tab": tab,
            "products": products,
            "store": store,
            "cat_rows": cat_rows,
            "all_products": all_products,
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
    promotional_product: str | None = Form(None),
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
        cursor.execute("SELECT promotional_product FROM Store_Product WHERE id_product = ?", (id_product,))
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


# ============================================================================
#                    МЕНЕДЖЕР: CRUD базових товарів (вкладка "Товари")
# ============================================================================
@router.post("/products-info/product/add")
def add_product(
    product_name: str = Form(...),
    category_number: int = Form(...),
    characteristics: str = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Додавати товари може лише менеджер", tab="products")
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO Product (category_number, product_name, characteristics) VALUES (?, ?, ?)",
            (category_number, product_name, characteristics),
        )
        db.commit()
        return _redirect(msg=f"Товар «{product_name}» додано", tab="products")
    except sqlite3.IntegrityError:
        db.rollback()
        return _redirect(err="Вказано неіснуючу категорію", tab="products")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}", tab="products")


@router.post("/products-info/product/update")
def update_product(
    id_product: int = Form(...),
    product_name: str = Form(...),
    category_number: int = Form(...),
    characteristics: str = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Редагувати товари може лише менеджер", tab="products")
    cursor = db.cursor()
    try:
        cursor.execute("SELECT 1 FROM Product WHERE id_product = ?", (id_product,))
        if not cursor.fetchone():
            return _redirect(err="Товар не знайдено", tab="products")
        cursor.execute(
            "UPDATE Product SET category_number = ?, product_name = ?, characteristics = ? WHERE id_product = ?",
            (category_number, product_name, characteristics, id_product),
        )
        db.commit()
        return _redirect(msg=f"Товар «{product_name}» оновлено", tab="products")
    except sqlite3.IntegrityError:
        db.rollback()
        return _redirect(err="Вказано неіснуючу категорію", tab="products")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}", tab="products")


@router.post("/products-info/product/delete")
def delete_product(
    id_product: int = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Видаляти товари може лише менеджер", tab="products")
    cursor = db.cursor()
    try:
        cursor.execute("SELECT 1 FROM Product WHERE id_product = ?", (id_product,))
        if not cursor.fetchone():
            return _redirect(err="Товар не знайдено", tab="products")
        cursor.execute("DELETE FROM Product WHERE id_product = ?", (id_product,))
        db.commit()
        return _redirect(msg="Товар видалено", tab="products")
    except sqlite3.IntegrityError:
        # Store_Product.id_product -> Product (ON DELETE NO ACTION)
        db.rollback()
        return _redirect(err="Спочатку приберіть товар із зали (є позиції у «Наявності»)", tab="products")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}", tab="products")


# ============================================================================
#                    МЕНЕДЖЕР: CRUD категорій (вкладка "Категорії")
# ============================================================================
@router.post("/products-info/category/add")
def add_category(
    category_name: str = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Додавати категорії може лише менеджер", tab="categories")
    cursor = db.cursor()
    try:
        cursor.execute("INSERT INTO Category (category_name) VALUES (?)", (category_name,))
        db.commit()
        return _redirect(msg=f"Категорію «{category_name}» додано", tab="categories")
    except sqlite3.IntegrityError:
        db.rollback()
        return _redirect(err="Така категорія вже існує", tab="categories")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}", tab="categories")


@router.post("/products-info/category/update")
def update_category(
    category_number: int = Form(...),
    category_name: str = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Редагувати категорії може лише менеджер", tab="categories")
    cursor = db.cursor()
    try:
        cursor.execute("SELECT 1 FROM Category WHERE category_number = ?", (category_number,))
        if not cursor.fetchone():
            return _redirect(err="Категорію не знайдено", tab="categories")
        cursor.execute("UPDATE Category SET category_name = ? WHERE category_number = ?",
                       (category_name, category_number))
        db.commit()
        return _redirect(msg="Категорію оновлено", tab="categories")
    except sqlite3.IntegrityError:
        db.rollback()
        return _redirect(err="Така назва категорії вже існує", tab="categories")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}", tab="categories")


@router.post("/products-info/category/delete")
def delete_category(
    category_number: int = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Видаляти категорії може лише менеджер", tab="categories")
    cursor = db.cursor()
    try:
        cursor.execute("SELECT 1 FROM Category WHERE category_number = ?", (category_number,))
        if not cursor.fetchone():
            return _redirect(err="Категорію не знайдено", tab="categories")
        cursor.execute("DELETE FROM Category WHERE category_number = ?", (category_number,))
        db.commit()
        return _redirect(msg="Категорію видалено", tab="categories")
    except sqlite3.IntegrityError:
        # Product.category_number -> Category (ON DELETE NO ACTION)
        db.rollback()
        return _redirect(err="Не можна видалити: у категорії є товари", tab="categories")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}", tab="categories")