from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
import sqlite3
from database import get_db

from database import get_db
from security import verify_password, create_access_token, SECRET_KEY, ALGORITHM

router = APIRouter()
templates = Jinja2Templates(directory="templates")

#метод для отримання токена юзера
def get_user_from_cookie(request: Request, db: sqlite3.Connection = Depends(get_db)):
    token = request.cookies.get("session_token")
    if not token:
        return None
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        employee_id = payload.get("sub")
        
        cursor = db.cursor()
        cursor.execute("SELECT id_employee, empl_name, empl_surname, empl_role FROM Employee WHERE id_employee = ?", (employee_id,))
        user = cursor.fetchone()
        
        if user:
            return {
                "id": user["id_employee"],
                "name": f"{user['empl_surname']} {user['empl_name'][0]}.",
                "role": user["empl_role"]
            }
    except JWTError:
        return None
        
    return None

#точка входу
@router.get("/", response_class=RedirectResponse)
def root_redirect(current_user: dict = Depends(get_user_from_cookie)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

#ендпоінт віпдравки форми авторизації
@router.post("/login", response_class=HTMLResponse)
def login_post(
    request: Request, 
    username: str = Form(...),
    password: str = Form(...), 
    db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM Employee WHERE id_employee = ?", (username,))
    user = cursor.fetchone()

    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            request=request, 
            name="login.html", 
            context={"user": None, "error": "Неправильний ID або пароль!"}
        )
    
    access_token = create_access_token(
        data={"sub": user["id_employee"], "role": user["empl_role"]}
    )

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    
    response.set_cookie(
        key="session_token", 
        value=access_token, 
        httponly=True,
        max_age=1 * 3600
    )
    
    return response

#ендпоінт сторінки авторизації
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="login.html", context={"user": None, "error": None}
    )

#ендпоінт на вихід з акаунта
@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response

#ендпоінт дашборду (головна сторінка)
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(
    request: Request, 
    current_user: dict = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    cursor = db.cursor()
    context={"user": current_user}

    #дані менеджера
    if current_user["role"] == "Менеджер":
        
        #крі за сьогодні
        cursor.execute("""
            SELECT 
                COUNT(check_number) as today_checks, 
                SUM(sum_total) as today_revenue
            FROM Check_AIS 
            WHERE DATE(print_date) = DATE('now', 'localtime')
        """)
        kpi = cursor.fetchone()
        
        context["today_checks"] = kpi["today_checks"] if kpi["today_checks"] else 0
        context["today_revenue"] = round(kpi["today_revenue"], 2) if kpi["today_revenue"] else 0.0
        
        #перегляд товарів, що закінчуються (менше 10 штук на полиці)
        cursor.execute("""
            SELECT p.product_name, sp.UPC, sp.products_number 
            FROM Store_Product sp
            JOIN Product p ON sp.id_product = p.id_product
            WHERE sp.products_number < 10
            ORDER BY sp.products_number ASC
            LIMIT 5
        """)

        context["low_stock_items"] = cursor.fetchall()
        
        #беремо станні 5 транзакцій
        cursor.execute("""
            SELECT ch.check_number, ch.print_date, e.empl_surname, ch.sum_total
            FROM Check_AIS ch
            JOIN Employee e ON ch.id_employee = e.id_employee
            ORDER BY ch.print_date DESC
            LIMIT 5
        """)
        context["recent_checks"] = cursor.fetchall()

    #дані касира
    elif current_user["role"] == "Касир":
        #перегляд чеків за сьогодні
        cursor.execute("""
            SELECT COUNT(check_number) as my_checks, SUM(sum_total) as my_revenue
            FROM Check_AIS
            WHERE id_employee = ? AND DATE(print_date) = DATE('now', 'localtime')
        """, (current_user["id"],))
        
        my_kpi = cursor.fetchone()
        context["my_checks"] = my_kpi["my_checks"] if my_kpi["my_checks"] else 0
        context["my_revenue"] = round(my_kpi["my_revenue"], 2) if my_kpi["my_revenue"] else 0.0

    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html",
        context=context
    )

#api-ендпоінт для швидкого сканера
@router.get("/api/quick-scan/{upc}")
def api_quick_scan(upc: str, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        SELECT 
            sp.UPC, 
            sp.selling_price, 
            sp.products_number, 
            sp.promotional_product,
            p.product_name
        FROM Store_Product sp
        JOIN Product p ON sp.id_product = p.id_product
        WHERE sp.UPC = ?
    """, (upc,))
    
    product = cursor.fetchone()
    
    if not product:
        return JSONResponse(status_code=404, content={"detail": "Товар не знайдено"})
        
    return {
        "upc": product["UPC"],
        "name": product["product_name"],
        "price": round(product["selling_price"], 2),
        "stock": product["products_number"],
        "is_promo": bool(product["promotional_product"])
    }

#ендпоінт для сторінки профіля
@router.get("/profile", response_class=HTMLResponse)
def ui_profile(request: Request, current_user: dict = Depends(get_user_from_cookie)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        
    return templates.TemplateResponse(
        request=request, 
        name="profile.html", 
        context={"user": current_user}
    )

#ендпоінт сторінки клієнтів
@router.get("/customers", response_class=HTMLResponse)
def ui_customers(
    request: Request, 
    surname: str | None = None,
    percent: str | None = None,
    sort_by: str = "surname",
    current_user: dict = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db)
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        
    db.create_function("py_lower", 1, lambda x: x.lower() if x else x)
    cursor = db.cursor()
    
    query = "SELECT * FROM Customer_Card"
    conds = []
    params = []
    
    # Фільтри пошуку
    if surname:
        conds.append("py_lower(cust_surname) LIKE ?")
        params.append(f"%{surname.lower()}%")

    parsed_percent = None
    if percent and percent.strip() != "":
        try:
            parsed_percent = int(percent)
            conds.append("percent = ?")
            params.append(parsed_percent)
        except ValueError:
            pass
        
    if conds:
        query += " WHERE " + " AND ".join(conds)
        
    if sort_by == "card_number":
        query += " ORDER BY card_number"
    elif sort_by == "percent":
        query += " ORDER BY percent DESC, cust_surname" 
    else:
        query += " ORDER BY cust_surname"

    cursor.execute(query, params)
    cards = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse(
        request=request, 
        name="customers.html", 
        context={
            "user": current_user, 
            "cards": cards, 
            "search_surname": surname or "", 
            "search_percent": percent or "",
            "sort_by": sort_by
        }
    )

#ендпоінт сторінки працівників
@router.get("/employees", response_class=HTMLResponse)
def ui_employees(
    request: Request, 
    role: str | None = None,
    surname: str | None = None,
    sort_by: str = "surname",
    current_user: dict = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db)
):
    if not current_user or current_user["role"] != "Менеджер":
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    db.create_function("py_lower", 1, lambda x: x.lower() if x else x)   
    cursor = db.cursor()
    query = """
        SELECT id_employee, empl_surname, empl_name, empl_patronymic, 
               empl_role, salary, date_of_birth, date_of_start, 
               phone_number, city, street, zip_code 
        FROM Employee
    """
    conds = []
    params = []
    
    if role:
        conds.append("empl_role = ?")
        params.append(role)
    if surname:
        conds.append("py_lower(empl_surname) LIKE ?")
        params.append(f"{surname}%")
        
    if conds:
        query += " WHERE " + " AND ".join(conds)

    if sort_by == "id":
        query += " ORDER BY id_employee"
    elif sort_by == "role":
        query += " ORDER BY empl_role, empl_surname"
    else:
        query += " ORDER BY empl_surname"
        
    cursor.execute(query, params)
    
    employees = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse(
        request=request, 
        name="employees.html", 
        context={
            "user": current_user, 
            "employees": employees,
            "search_role": role or "",
            "search_surname": surname or "",
            "sort_by": sort_by
        }
    )

#ендпоінт для сторінки чеків
@router.get("/receipts", response_class=HTMLResponse)
def ui_receipts(
    request: Request,
    check_number: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    id_employee: str | None = None,
    current_user: dict = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db)
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        
    db.create_function("py_lower", 1, lambda x: x.lower() if x else x)
    cursor = db.cursor()

    query = 'SELECT * FROM "Check_AIS" WHERE 1=1'
    params = []
    
    if check_number:
        query += " AND check_number LIKE ?"
        params.append(f"%{check_number}%")

    if current_user["role"] == "Касир":
        query += " AND id_employee = ?"
        params.append(current_user["id"])
    elif id_employee:
        query += " AND py_lower(id_employee) LIKE ?"
        params.append(f"%{id_employee.lower()}%")
        
    if start_date and end_date:
        query += " AND DATE(print_date) BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    elif start_date:
        query += " AND DATE(print_date) = ?"
        params.append(start_date)
        
    query += " ORDER BY print_date DESC"
    cursor.execute(query, params)
    
    raw_checks = cursor.fetchall()
    checks_history = []
    for c in raw_checks:
        check_dict = dict(c) 
        cursor.execute("""
            SELECT p.product_name, s.product_number, s.selling_price 
            FROM Sale s
            JOIN Store_Product sp ON s.UPC = sp.UPC
            JOIN Product p ON sp.id_product = p.id_product
            WHERE s.check_number = ?
        """, (c["check_number"],))
        check_dict["items"] = [dict(row) for row in cursor.fetchall()]
        checks_history.append(check_dict)

    return templates.TemplateResponse(
        request=request,
        name="receipts.html",
        context={
            "user": current_user,
            "checks": checks_history,
            "search_check": check_number or "",
            "start_date": start_date or "",
            "end_date": end_date or "",
            "search_emp": id_employee or ""
        }
    )

#ендпоінт для касового апарату
@router.get("/cash-register", response_class=HTMLResponse)
def ui_cash_register(
    request: Request, 
    current_user: dict = Depends(get_user_from_cookie)
):
    # Касовий апарат доступний ТІЛЬКИ касирам
    if not current_user or current_user["role"] != "Касир":
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
        
    return templates.TemplateResponse(
        request=request, 
        name="cash_register.html", 
        context={"user": current_user}
    )

#ендпоінт сторінки звітів та аналітики (лише менеджер: М-19, М-20, М-21)
@router.get("/reports", response_class=HTMLResponse)
def ui_reports(
    request: Request,
    r: str | None = None,                # який звіт рахуємо: "sales" | "product"
    start_date: str | None = None,
    end_date: str | None = None,
    id_employee: str | None = None,      # для звіту з продажів (необов'язково)
    upc: str | None = None,              # для звіту по товару
    cat_from: str | None = None,         # параметри аналітики «дохід за категоріями»
    cat_to: str | None = None,
    cat_min: str | None = None,
    vip_percent: str | None = None,      # параметр аналітики «VIP-касири»
    g_from: str | None = None,           # продажі касир×категорія: період + касир
    g_to: str | None = None,
    g_emp: str | None = None,
    ac_from: str | None = None,          # клієнти, що купували в усіх категоріях: період
    ac_to: str | None = None,
    au_cat: str | None = None,           # аудит продажів касирами: категорія + період
    au_from: str | None = None,
    au_to: str | None = None,
    ic_from: str | None = None,          # «ідеальні» категорії (усі товари продано): період
    ic_to: str | None = None,
    reg: str | None = None,              # який реєстр показати/друкувати (М-4)
    current_user: dict = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db),
):
    # Звіти — функція менеджера
    if not current_user or current_user["role"] != "Менеджер":
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    cursor = db.cursor()

    # довідники для зручних випадайок (без ручного вводу кодів)
    cursor.execute("""
        SELECT id_employee, empl_surname, empl_name
        FROM Employee WHERE empl_role = 'Касир'
        ORDER BY empl_surname, empl_name
    """)
    cashiers = [dict(x) for x in cursor.fetchall()]

    cursor.execute("""
        SELECT sp.UPC, p.product_name, sp.promotional_product
        FROM Store_Product sp
        JOIN Product p ON sp.id_product = p.id_product
        ORDER BY p.product_name
    """)
    store_products = [dict(x) for x in cursor.fetchall()]

    # ── Аналітика (рахується завжди, параметри мають значення за замовчуванням) ──

    # Параметр відсотка знижки: порожнє поле → усі клієнти (будь-яка знижка)
    vip_all = vip_percent in (None, "")
    if vip_all:
        vip_pct = None
    else:
        try:
            vip_pct = int(vip_percent)
        except ValueError:
            vip_pct = 20
        vip_pct = max(0, min(100, vip_pct))  # коректний діапазон знижки 0..100
    # наявні відсотки знижок — як підказки (datalist)
    cursor.execute("SELECT DISTINCT percent FROM Customer_Card ORDER BY percent DESC")
    percents = [x["percent"] for x in cursor.fetchall()]

    # Поріг доходу (HAVING) для аналітики за категоріями (за замовчуванням 0)
    try:
        cat_min_val = float(cat_min) if cat_min not in (None, "") else 0.0
    except ValueError:
        cat_min_val = 0.0
    # Валідація періоду: дата «від» не може бути пізнішою за «до»
    cat_err = None
    cat_period_on = False
    if cat_from and cat_to:
        if cat_from <= cat_to:
            cat_period_on = True
        else:
            cat_err = "Дата «від» не може бути пізнішою за дату «до» — період не застосовано"

    # (1) Касири, які обслужили ВСІХ клієнтів — ПАРАМЕТРИЧНИЙ (подвійне заперечення).
    #     vip_all=True  → усі клієнти з карткою (будь-яка знижка);
    #     vip_all=False → лише клієнти зі знижкою vip_pct%.
    if vip_all:
        cursor.execute("SELECT COUNT(*) AS n FROM Customer_Card")
        # WHERE-умова для підзапиту: усі картки
        client_cond, client_params = "WHERE NOT EXISTS", []
    else:
        cursor.execute("SELECT COUNT(*) AS n FROM Customer_Card WHERE percent = ?", (vip_pct,))
        client_cond, client_params = "WHERE cc.percent = ? AND NOT EXISTS", [vip_pct]
    vip_count = cursor.fetchone()["n"]

    if vip_count == 0:
        cashiers_all_vip = []
    else:
        cursor.execute(f"""
            SELECT e.id_employee, e.empl_surname, e.empl_name
            FROM Employee e
            WHERE e.empl_role = 'Касир'
              AND NOT EXISTS (
                  SELECT cc.card_number
                  FROM Customer_Card cc
                  {client_cond} (
                        SELECT 1
                        FROM "Check_AIS" ch
                        WHERE ch.id_employee = e.id_employee
                          AND ch.card_number = cc.card_number
                  )
              )
            ORDER BY e.empl_surname, e.empl_name
        """, client_params)
        cashiers_all_vip = [dict(x) for x in cursor.fetchall()]

    # (2) Дохід за категоріями — групування, ПАРАМЕТРИЧНИЙ (період + поріг доходу).
    #     Багатотабличний (5 таблиць): Category, Product, Store_Product, Sale, Check_AIS.
    cat_query = """
        SELECT c.category_name,
               COUNT(DISTINCT p.id_product) AS unique_products,
               SUM(s.product_number) AS total_units,
               SUM(s.product_number * s.selling_price) AS total_revenue
        FROM Category c
        JOIN Product p ON c.category_number = p.category_number
        JOIN Store_Product sp ON p.id_product = sp.id_product
        JOIN Sale s ON sp.UPC = s.UPC
        JOIN "Check_AIS" ch ON s.check_number = ch.check_number
    """
    cat_params = []
    if cat_period_on:
        cat_query += " WHERE DATE(ch.print_date) BETWEEN ? AND ?"
        cat_params += [cat_from, cat_to]
    cat_query += """
        GROUP BY c.category_number, c.category_name
        HAVING SUM(s.product_number * s.selling_price) >= ?
        ORDER BY total_revenue DESC
    """
    cat_params.append(cat_min_val)
    cursor.execute(cat_query, cat_params)
    category_revenue = [dict(x) for x in cursor.fetchall()]

    # (3) Продажі за касиром і категорією — ГРУПУВАННЯ, ПАРАМЕТРИЧНИЙ (касир + період).
    #     Багатотабличний (6 таблиць): Employee, Check_AIS, Sale, Store_Product, Product, Category.
    #     Для кожного касира і категорії — скільки одиниць продав і на яку суму.
    g_err = None
    g_period_on = False
    if g_from and g_to:
        if g_from <= g_to:
            g_period_on = True
        else:
            g_err = "Дата «від» не може бути пізнішою за дату «до» — період не застосовано"
    g_query = """
        SELECT e.id_employee, e.empl_surname, e.empl_name,
               c.category_name,
               SUM(s.product_number) AS units,
               SUM(s.product_number * s.selling_price) AS revenue
        FROM Employee e
        JOIN "Check_AIS" ch ON ch.id_employee = e.id_employee
        JOIN Sale s ON s.check_number = ch.check_number
        JOIN Store_Product sp ON sp.UPC = s.UPC
        JOIN Product p ON p.id_product = sp.id_product
        JOIN Category c ON c.category_number = p.category_number
        WHERE e.empl_role = 'Касир'
    """
    g_params = []
    if g_emp:
        g_query += " AND e.id_employee = ?"
        g_params.append(g_emp)
    if g_period_on:
        g_query += " AND DATE(ch.print_date) BETWEEN ? AND ?"
        g_params += [g_from, g_to]
    g_query += """
        GROUP BY e.id_employee, e.empl_surname, e.empl_name, c.category_number, c.category_name
        ORDER BY e.empl_surname, e.empl_name, c.category_name
    """
    cursor.execute(g_query, g_params)
    cashier_cat_sales = [dict(x) for x in cursor.fetchall()]

    # (4) Клієнти, що купували товари в УСІХ категоріях — ПОДВІЙНЕ ЗАПЕРЕЧЕННЯ, ПАРАМЕТРИЧНИЙ (період).
    #     Багатотабличний: Customer_Card, Category, Check_AIS, Sale, Store_Product, Product.
    #     Немає жодної категорії, в якій у клієнта не було б покупки.
    ac_err = None
    ac_period_on = False
    if ac_from and ac_to:
        if ac_from <= ac_to:
            ac_period_on = True
        else:
            ac_err = "Дата «від» не може бути пізнішою за дату «до» — період не застосовано"
    ac_date_cond = ""
    ac_params = []
    if ac_period_on:
        ac_date_cond = " AND DATE(ch.print_date) BETWEEN ? AND ?"
        ac_params = [ac_from, ac_to]
    cursor.execute(f"""
        SELECT cc.card_number, cc.cust_surname, cc.cust_name
        FROM Customer_Card cc
        WHERE NOT EXISTS (
            SELECT 1 FROM Category cat
            WHERE NOT EXISTS (
                SELECT 1
                FROM "Check_AIS" ch
                JOIN Sale s ON s.check_number = ch.check_number
                JOIN Store_Product sp ON sp.UPC = s.UPC
                JOIN Product p ON p.id_product = sp.id_product
                WHERE ch.card_number = cc.card_number
                  AND p.category_number = cat.category_number
                  {ac_date_cond}
            )
        )
        ORDER BY cc.cust_surname, cc.cust_name
    """, ac_params)
    customers_all_cat = [dict(x) for x in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) AS n FROM Category")
    total_categories = cursor.fetchone()["n"]

    # список категорій для випадайки (аудит)
    cursor.execute("SELECT category_number, category_name FROM Category ORDER BY category_name")
    categories_list = [dict(x) for x in cursor.fetchall()]

    # (5) Аудит продажів за касиром і категорією — ГРУПУВАННЯ, ПАРАМЕТРИЧНИЙ (категорія + період).
    #     Багатотабличний (6 таблиць): Employee, Check_AIS, Sale, Store_Product, Product, Category.
    #     Хто з касирів найкраще продає товари певної категорії (виручка, к-сть чеків, одиниці).
    au_err = None
    au_period_on = False
    if au_from and au_to:
        if au_from <= au_to:
            au_period_on = True
        else:
            au_err = "Дата «від» не може бути пізнішою за дату «до» — період не застосовано"
    au_cat_id = int(au_cat) if (au_cat and au_cat.strip().isdigit()) else None
    au_query = """
        SELECT e.empl_surname, e.empl_name, c.category_name,
               COUNT(DISTINCT ch.check_number) AS checks_cnt,
               SUM(s.product_number) AS units,
               SUM(s.product_number * s.selling_price) AS revenue
        FROM Employee e
        JOIN "Check_AIS" ch ON e.id_employee = ch.id_employee
        JOIN Sale s ON ch.check_number = s.check_number
        JOIN Store_Product sp ON s.UPC = sp.UPC
        JOIN Product p ON sp.id_product = p.id_product
        JOIN Category c ON p.category_number = c.category_number
        WHERE e.empl_role = 'Касир'
    """
    au_params = []
    if au_cat_id:
        au_query += " AND p.category_number = ?"
        au_params.append(au_cat_id)
    if au_period_on:
        au_query += " AND DATE(ch.print_date) BETWEEN ? AND ?"
        au_params += [au_from, au_to]
    au_query += """
        GROUP BY e.id_employee, e.empl_surname, c.category_number, c.category_name
        ORDER BY revenue DESC, e.empl_surname
    """
    cursor.execute(au_query, au_params)
    cashier_audit = [dict(x) for x in cursor.fetchall()]

    # (6) «Ідеальні» категорії: усі базові товари категорії продано хоча б раз —
    #     ПОДВІЙНЕ ЗАПЕРЕЧЕННЯ, ПАРАМЕТРИЧНИЙ (період). Багатотабличний:
    #     Category, Product, Store_Product, Sale, Check_AIS.
    #     Немає жодного товару категорії, який ніколи не продавався.
    ic_err = None
    ic_period_on = False
    if ic_from and ic_to:
        if ic_from <= ic_to:
            ic_period_on = True
        else:
            ic_err = "Дата «від» не може бути пізнішою за дату «до» — період не застосовано"
    ic_date_cond = ""
    ic_params = []
    if ic_period_on:
        ic_date_cond = """
                  JOIN "Check_AIS" ch ON s.check_number = ch.check_number
                  AND DATE(ch.print_date) BETWEEN ? AND ?"""
        ic_params = [ic_from, ic_to]
    cursor.execute(f"""
        SELECT c.category_number, c.category_name
        FROM Category c
        WHERE EXISTS (SELECT 1 FROM Product p0 WHERE p0.category_number = c.category_number)
          AND NOT EXISTS (
            SELECT p.id_product
            FROM Product p
            WHERE p.category_number = c.category_number
              AND NOT EXISTS (
                  SELECT 1
                  FROM Store_Product sp
                  JOIN Sale s ON sp.UPC = s.UPC{ic_date_cond}
                  WHERE sp.id_product = p.id_product
              )
        )
        ORDER BY c.category_name
    """, ic_params)
    ideal_categories = [dict(x) for x in cursor.fetchall()]

    # ── Реєстри для друку (М-4): повні переліки сутностей ──
    REGISTRIES = {
        "employees": "Працівники",
        "customers": "Постійні клієнти",
        "categories": "Категорії товарів",
        "products": "Товари",
        "store": "Товари у магазині",
        "checks": "Чеки",
    }
    reg = reg if reg in REGISTRIES else "employees"
    if reg == "employees":
        cursor.execute("""
            SELECT id_employee, empl_surname, empl_name, empl_patronymic, empl_role,
                   salary, date_of_birth, date_of_start, phone_number, city, street, zip_code
            FROM Employee ORDER BY empl_surname, empl_name
        """)
    elif reg == "customers":
        cursor.execute("""
            SELECT card_number, cust_surname, cust_name, cust_patronymic,
                   phone_number, city, street, zip_code, percent
            FROM Customer_Card ORDER BY cust_surname, cust_name
        """)
    elif reg == "categories":
        cursor.execute("SELECT category_number, category_name FROM Category ORDER BY category_name")
    elif reg == "products":
        cursor.execute("""
            SELECT p.id_product, p.product_name, p.producer, p.characteristics, c.category_name
            FROM Product p JOIN Category c ON p.category_number = c.category_number
            ORDER BY p.product_name
        """)
    elif reg == "store":
        cursor.execute("""
            SELECT sp.UPC, p.product_name, c.category_name, sp.selling_price,
                   sp.products_number, sp.promotional_product
            FROM Store_Product sp
            JOIN Product p ON sp.id_product = p.id_product
            JOIN Category c ON p.category_number = c.category_number
            ORDER BY p.product_name
        """)
    elif reg == "checks":
        cursor.execute("""
            SELECT ch.check_number, ch.print_date, e.empl_surname,
                   ch.card_number, ch.sum_total, ch.vat
            FROM "Check_AIS" ch
            JOIN Employee e ON ch.id_employee = e.id_employee
            ORDER BY ch.print_date DESC
        """)
    registry_rows = [dict(x) for x in cursor.fetchall()]

    sales_report = None
    product_report = None
    err = None

    def _valid_period(s, e):
        return bool(s) and bool(e) and s <= e

    # ── Звіт із продажів за період (М-19 / М-20) — логіка /reports/sales ──
    if r == "sales":
        if not _valid_period(start_date, end_date):
            err = "Вкажіть коректний період (дата початку не пізніша за дату кінця)"
        else:
            query = """
                SELECT COUNT(check_number) AS total_checks,
                       COALESCE(SUM(sum_total), 0) AS total_sales_sum
                FROM "Check_AIS"
                WHERE DATE(print_date) BETWEEN ? AND ?
            """
            params = [start_date, end_date]
            if id_employee:
                query += " AND id_employee = ?"
                params.append(id_employee)
            cursor.execute(query, params)
            res = cursor.fetchone()
            emp_label = "усі касири"
            if id_employee:
                cursor.execute("SELECT empl_surname, empl_name FROM Employee WHERE id_employee = ?", (id_employee,))
                e = cursor.fetchone()
                emp_label = f"{e['empl_surname']} {e['empl_name']}" if e else id_employee
            sales_report = {
                "employee": emp_label,
                "period": f"{start_date} — {end_date}",
                "total_checks": res["total_checks"] or 0,
                "total_revenue": round(res["total_sales_sum"], 2),
            }

    # ── Продаж конкретного товару за період (М-21) — логіка /reports/product-sales ──
    elif r == "product":
        if not upc:
            err = "Оберіть товар (UPC)"
        elif not _valid_period(start_date, end_date):
            err = "Вкажіть коректний період (дата початку не пізніша за дату кінця)"
        else:
            cursor.execute("""
                SELECT COALESCE(SUM(s.product_number), 0) AS total_sold
                FROM Sale s
                JOIN "Check_AIS" c ON s.check_number = c.check_number
                WHERE s.UPC = ? AND DATE(c.print_date) BETWEEN ? AND ?
            """, (upc, start_date, end_date))
            total_sold = cursor.fetchone()["total_sold"]
            cursor.execute("""
                SELECT p.product_name FROM Store_Product sp
                JOIN Product p ON sp.id_product = p.id_product WHERE sp.UPC = ?
            """, (upc,))
            pn = cursor.fetchone()
            product_report = {
                "upc": upc,
                "product_name": pn["product_name"] if pn else "—",
                "period": f"{start_date} — {end_date}",
                "total_units": total_sold,
            }

    return templates.TemplateResponse(
        request=request,
        name="reports.html",
        context={
            "user": current_user,
            "active": r,
            "cashiers": cashiers,
            "store_products": store_products,
            "cashiers_all_vip": cashiers_all_vip,
            "category_revenue": category_revenue,
            "cat_err": cat_err,
            "percents": percents,
            "vip_count": vip_count,
            "vip_all": vip_all,
            "cashier_cat_sales": cashier_cat_sales,
            "g_err": g_err,
            "customers_all_cat": customers_all_cat,
            "ac_err": ac_err,
            "total_categories": total_categories,
            "categories_list": categories_list,
            "cashier_audit": cashier_audit,
            "au_err": au_err,
            "ideal_categories": ideal_categories,
            "ic_err": ic_err,
            "reg": reg,
            "registries": REGISTRIES,
            "registry_rows": registry_rows,
            "sales_report": sales_report,
            "product_report": product_report,
            "err": err,
            "f": {
                "start_date": start_date or "",
                "end_date": end_date or "",
                "id_employee": id_employee or "",
                "upc": upc or "",
                "cat_from": cat_from or "",
                "cat_to": cat_to or "",
                "cat_min": cat_min or "",
                "vip_percent": "" if vip_all else vip_pct,
                "g_from": g_from or "",
                "g_to": g_to or "",
                "g_emp": g_emp or "",
                "ac_from": ac_from or "",
                "ac_to": ac_to or "",
                "au_cat": au_cat_id,
                "au_from": au_from or "",
                "au_to": au_to or "",
                "ic_from": ic_from or "",
                "ic_to": ic_to or "",
            },
        },
    )