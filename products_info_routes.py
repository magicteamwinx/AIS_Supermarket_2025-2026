"""
Роутер «Каталог / Асортимент та склад».  Маршрут: /products-info

Три вкладки (= три різні сутності й три вимоги ТЗ):
  • tab=products   -> усі БАЗОВІ товари (Product), відсортовані за назвою      (М-9 / К-1)
                      разом із позначкою, чи виставлено товар у залу
  • tab=store      -> усі товари В МАГАЗИНІ (Store_Product)                     (М-10 / К-2)
  • tab=categories -> усі категорії (Category), відсортовані за назвою          (М-8) — лише менеджер

Логіка акційного товару (вимога: акційна ціна = звичайна × 0,8):
  • Форма «виставити в залу» створює ЛИШЕ звичайну позицію.
  • Акційна позиція створюється дією /store-product/promote від наявної звичайної:
    ціна обчислюється на сервері (×0,8) і НЕ вводиться вручну; у звичайної проставляється UPC_prom.
  • Кількість акційної ПЕРЕНОСИТЬСЯ зі звичайної (це ті самі фізичні одиниці):
    promote зменшує залишок звичайної, delete акційної повертає одиниці назад,
    зміна кількості акційної переносить різницю між позиціями.
  • Переоцінка: зміна ціни звичайної автоматично перераховує ціну акційної пари.
  • n<=2: у товару щонайбільше одна звичайна + одна акційна позиція.
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
PROMO_RATE = 0.8  # стандартна знижка -20%


def _promo_price(base_price: float) -> float:
    """Похідна акційна ціна від звичайної (округлення до копійок)."""
    return round(float(base_price) * PROMO_RATE, 2)


def _suggest_promo_upc(base: str, existing: set) -> str:
    """Вільний UPC для акційної позиції на основі UPC звичайної (≤12 символів)."""
    cand = base[:11] + "P"
    if cand not in existing:
        return cand
    i = 2
    while True:
        suffix = f"P{i}"
        cand = base[: 12 - len(suffix)] + suffix
        if cand not in existing:
            return cand
        i += 1


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
    tab: str = "store",
    q: str | None = None,
    category: str | None = None,
    promo: str = "all",
    avail: str = "all",
    sort: str | None = None,
    msg: str | None = None,
    err: str | None = None,
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    is_manager = current_user["role"] == "Менеджер"
    if tab == "categories" and not is_manager:
        tab = "store"
    if tab not in ("products", "store", "categories"):
        tab = "store"

    cat_id = int(category) if (category and category.strip().isdigit()) else None
    db.create_function("py_lower", 1, lambda x: x.lower() if x else x)
    cursor = db.cursor()

    cursor.execute("SELECT category_number, category_name FROM Category ORDER BY category_name")
    categories = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT p.id_product, p.product_name
        FROM Product p
        JOIN Category c ON p.category_number = c.category_number
        ORDER BY p.product_name
    """)
    all_products = cursor.fetchall()

    products, store, cat_rows = [], [], []
    taken_upcs = []

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
        query += " ORDER BY c.category_name, p.product_name" if sort == "category" else " ORDER BY p.product_name"
        cursor.execute(query, params)
        products = [dict(r) for r in cursor.fetchall()]

    elif tab == "store":
        # М-10: менеджеру за замовчуванням сортуємо за кількістю; К-2: касиру — за назвою
        if sort not in ("quantity", "name"):
            sort = "quantity" if is_manager else "name"
        query = """
            SELECT sp.UPC, sp.UPC_prom, sp.id_product, sp.selling_price,
                   sp.products_number, sp.promotional_product,
                   p.product_name, p.characteristics, c.category_name, p.category_number,
                   pr.UPC AS prom_UPC
            FROM Store_Product sp
            JOIN Product p ON sp.id_product = p.id_product
            JOIN Category c ON p.category_number = c.category_number
            LEFT JOIN Store_Product pr ON pr.UPC = sp.UPC_prom
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
        query += " ORDER BY p.product_name" if sort == "name" else " ORDER BY sp.products_number DESC, p.product_name"
        cursor.execute(query, params)
        store = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT UPC FROM Store_Product")
        existing_upcs = {r["UPC"] for r in cursor.fetchall()}
        taken_upcs = sorted(existing_upcs)
        for s in store:
            if not s["promotional_product"] and not s["prom_UPC"]:
                s["suggest_prom"] = _suggest_promo_upc(s["UPC"], existing_upcs)
            else:
                s["suggest_prom"] = ""

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
            "taken_upcs": taken_upcs,
            "f": {"q": q or "", "category": cat_id, "promo": promo, "avail": avail, "sort": sort},
            "msg": msg,
            "err": err,
        },
    )


# ───────────────────── менеджер: виставити ЗВИЧАЙНУ позицію у залу ─────────────────────
@router.post("/products-info/store-product/add")
def add_store_product(
    UPC: str = Form(...),
    id_product: int = Form(...),
    selling_price: float = Form(...),
    products_number: int = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Виставляти товар у залу може лише менеджер")
    UPC = UPC.strip()
    if not (1 <= len(UPC) <= 12):
        return _redirect(err="UPC має містити від 1 до 12 символів")
    if selling_price < 0 or products_number < 0:
        return _redirect(err="Ціна та кількість не можуть бути від'ємними")

    cursor = db.cursor()
    try:
        cursor.execute("SELECT 1 FROM Store_Product WHERE id_product = ? AND promotional_product = 0", (id_product,))
        if cursor.fetchone():
            return _redirect(err="У товару вже є звичайна позиція в залі")
        cursor.execute("""
            INSERT INTO Store_Product (UPC, UPC_prom, id_product, selling_price, products_number, promotional_product)
            VALUES (?, NULL, ?, ?, ?, 0)
        """, (UPC, id_product, selling_price, products_number))
        db.commit()
        return _redirect(msg=f"Товар з UPC {UPC} виставлено в залу")
    except sqlite3.IntegrityError:
        db.rollback()
        return _redirect(err="Такий UPC уже існує або вказано неіснуючий товар")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}")


# ───────────────────── менеджер: ПЕРЕВЕСТИ звичайну позицію в АКЦІЮ ─────────────────────
@router.post("/products-info/store-product/promote")
def promote_store_product(
    source_UPC: str = Form(...),
    UPC: str = Form(...),
    products_number: int = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Створювати акційну позицію може лише менеджер")
    UPC = UPC.strip()
    if not (1 <= len(UPC) <= 12):
        return _redirect(err="UPC акційного має містити від 1 до 12 символів")
    if products_number < 0:
        return _redirect(err="Кількість не може бути від'ємною")

    cursor = db.cursor()
    try:
        cursor.execute(
            "SELECT id_product, selling_price, products_number, promotional_product, UPC_prom "
            "FROM Store_Product WHERE UPC = ?", (source_UPC,))
        src = cursor.fetchone()
        if not src:
            return _redirect(err="Звичайну позицію не знайдено")
        if src["promotional_product"]:
            return _redirect(err="Не можна зробити акцію на акційну позицію")
        # реальна наявність акційної позиції (висяче UPC_prom із даних не блокує)
        cursor.execute("SELECT 1 FROM Store_Product WHERE id_product = ? AND promotional_product = 1", (src["id_product"],))
        if cursor.fetchone():
            return _redirect(err="У товару вже є акційна позиція")
        if products_number > src["products_number"]:
            return _redirect(err=f"На акцію не можна виставити більше, ніж є у звичайній позиції (доступно: {src['products_number']})")

        promo_price = _promo_price(src["selling_price"])
        cursor.execute("""
            INSERT INTO Store_Product (UPC, UPC_prom, id_product, selling_price, products_number, promotional_product)
            VALUES (?, NULL, ?, ?, ?, 1)
        """, (UPC, src["id_product"], promo_price, products_number))
        cursor.execute(
            "UPDATE Store_Product SET UPC_prom = ?, products_number = products_number - ? WHERE UPC = ?",
            (UPC, products_number, source_UPC))
        db.commit()
        return _redirect(msg=f"Створено акційну позицію {UPC} за ціною {promo_price:.2f} ₴ ({products_number} шт перенесено зі звичайної)")
    except sqlite3.IntegrityError:
        db.rollback()
        return _redirect(err="Такий UPC акційного уже існує")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}")


# ───────────────────── менеджер: редагувати позицію в залі ─────────────────────
@router.post("/products-info/store-product/update")
def update_store_product(
    UPC: str = Form(...),
    selling_price: float = Form(...),
    products_number: int = Form(...),
    current_user: dict | None = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if current_user["role"] != "Менеджер":
        return _redirect(err="Редагувати наявність може лише менеджер")
    if selling_price < 0 or products_number < 0:
        return _redirect(err="Ціна та кількість не можуть бути від'ємними")

    cursor = db.cursor()
    try:
        cursor.execute("SELECT promotional_product, UPC_prom, products_number FROM Store_Product WHERE UPC = ?", (UPC,))
        row = cursor.fetchone()
        if not row:
            return _redirect(err="Позицію в залі не знайдено")

        if row["promotional_product"]:
            # ціна — похідна від батьківської звичайної; кількість незалежна
            cursor.execute("SELECT selling_price FROM Store_Product WHERE UPC_prom = ?", (UPC,))
            parent = cursor.fetchone()
            price = _promo_price(parent["selling_price"]) if parent else selling_price
            cursor.execute("UPDATE Store_Product SET selling_price = ?, products_number = ? WHERE UPC = ?",
                           (price, products_number, UPC))
        else:
            cursor.execute("UPDATE Store_Product SET selling_price = ?, products_number = ? WHERE UPC = ?",
                           (selling_price, products_number, UPC))
            if row["UPC_prom"]:
                cursor.execute("UPDATE Store_Product SET selling_price = ? WHERE UPC = ?",
                               (_promo_price(selling_price), row["UPC_prom"]))
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
        cursor.execute("SELECT promotional_product, UPC_prom, products_number FROM Store_Product WHERE UPC = ?", (UPC,))
        row = cursor.fetchone()
        if not row:
            return _redirect(err="Позицію в залі не знайдено")

        if row["promotional_product"]:
            # лише обнуляємо посилання у звичайної пари; кількість НЕ повертаємо (списується)
            cursor.execute("UPDATE Store_Product SET UPC_prom = NULL WHERE UPC_prom = ?", (UPC,))
            cursor.execute("DELETE FROM Store_Product WHERE UPC = ?", (UPC,))
        else:
            if row["UPC_prom"]:
                cursor.execute("DELETE FROM Store_Product WHERE UPC = ?", (row["UPC_prom"],))
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
        cursor.execute("INSERT INTO Product (category_number, product_name, characteristics) VALUES (?, ?, ?)",
                       (category_number, product_name, characteristics))
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
        cursor.execute("UPDATE Product SET category_number = ?, product_name = ?, characteristics = ? WHERE id_product = ?",
                       (category_number, product_name, characteristics, id_product))
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
        cursor.execute("UPDATE Category SET category_name = ? WHERE category_number = ?", (category_name, category_number))
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
        cursor.execute("SELECT 1 FROM Product WHERE category_number = ?", (category_number,))
        if cursor.fetchone():
            return _redirect(err="Не можна видалити: у категорії є товари", tab="categories")
        cursor.execute("DELETE FROM Category WHERE category_number = ?", (category_number,))
        db.commit()
        return _redirect(msg="Категорію видалено", tab="categories")
    except sqlite3.IntegrityError:
        db.rollback()
        return _redirect(err="Не можна видалити: у категорії є товари", tab="categories")
    except Exception as e:
        db.rollback()
        return _redirect(err=f"Помилка сервера: {e}", tab="categories")