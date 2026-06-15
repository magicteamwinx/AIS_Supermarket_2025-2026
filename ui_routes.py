from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import jwt, JWTError
import sqlite3

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
def dashboard_page(request: Request, current_user: dict = Depends(get_user_from_cookie)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        
    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html",
        context={"user": current_user}
    )

#ендпоінт на вихід з акаунта
@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_token")
    return response

