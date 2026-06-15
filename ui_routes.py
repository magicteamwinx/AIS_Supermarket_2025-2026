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
def ui_profile(
    request: Request, 
    current_user: dict = Depends(get_user_from_cookie),
    db: sqlite3.Connection = Depends(get_db)
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        
    cursor = db.cursor()
    cursor.execute("SELECT * FROM Employee WHERE id_employee = ?", (current_user["id"],))
    profile_data = cursor.fetchone()

    return templates.TemplateResponse(
        request=request, 
        name="profile.html", 
        context={
            "user": current_user,
            "profile_data": profile_data
        }
    )

@router.get("/customers", response_class=HTMLResponse)
def ui_customers(
    request: Request, 
    surname: str | None = None,
    percent: int | None = None,
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
    if percent is not None:
        conds.append("percent = ?")
        params.append(percent)
        
    if conds:
        query += " WHERE " + " AND ".join(conds)
        
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
            "search_percent": percent or ""
        }
    )