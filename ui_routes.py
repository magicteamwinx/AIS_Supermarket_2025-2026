from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
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
        
        # 1. KPI за сьогодні (Загальна каса та кількість чеків)
        # DATE('now', 'localtime') бере сьогоднішню дату в SQLite
        cursor.execute("""
            SELECT 
                COUNT(check_number) as today_checks, 
                SUM(sum_total) as today_revenue
            FROM Check_AIS 
            WHERE DATE(print_date) = DATE('now', 'localtime')
        """)
        kpi = cursor.fetchone()
        
        # Якщо чеків ще немає, SUM поверне None, тому робимо перевірку
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
        # Рахуємо, скільки чеків пробив конкретно цей касир за свою поточну зміну
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

#ендпоінт на вихід з акаунта
@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response

