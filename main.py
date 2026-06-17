from fastapi import FastAPI, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from jose import JWTError, jwt
from security import SECRET_KEY, ALGORITHM
from datetime import date, datetime
import sqlite3
from database import get_db
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from security import verify_password, create_access_token, get_password_hash

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login", auto_error=False)

class ProductCreate(BaseModel):
    category_number: int
    product_name: str
    producer: str
    characteristics: str

class EmployeeCreate(BaseModel):
    id_employee: str
    empl_surname: str
    empl_name: str
    empl_patronymic: str = None
    empl_role: str
    salary: float
    date_of_birth: date
    date_of_start: date
    phone_number: str = Field(..., max_length=13)
    city: str
    street: str
    zip_code: str
    password: str

class CheckItem(BaseModel):
    UPC: str
    product_number: int

class CheckCreate(BaseModel):
    check_number: str
    card_number: str | None = None
    items: list[CheckItem]

class CustomerCardCreate(BaseModel):
    card_number: str
    cust_surname: str
    cust_name: str
    cust_patronymic: str = None
    phone_number: str = Field(..., max_length=13)
    city: str = None
    street: str = None
    zip_code: str = None
    percent: int

class CustomerCardUpdate(BaseModel):
    cust_surname: str
    cust_name: str
    cust_patronymic: str | None = None
    phone_number: str
    city: str = None
    street: str = None
    zip_code: str = None
    percent: int

class StoreProductCreate(BaseModel):
    UPC: str
    UPC_prom: str | None = None
    id_product: int
    selling_price: float
    products_number: int
    promotional_product: bool

class CategoryUpdate(BaseModel):
    category_name: str

class StoreProductUpdate(BaseModel):
    UPC_prom: str | None = None
    id_product: int
    selling_price: float
    products_number: int
    promotional_product: bool

class EmployeeUpdate(BaseModel):
    empl_surname: str
    empl_name: str
    empl_patronymic: str | None = None
    empl_role: str
    salary: float
    phone_number: str
    city: str
    street: str
    zip_code: str
    password: str | None = None

app = FastAPI(title="ZLAGODA Mini-Supermarket")

from fastapi.staticfiles import StaticFiles
from ui_routes import router as ui_router
from products_info_routes import router as products_info_router

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(ui_router)
app.include_router(products_info_router)

class CategoryCreate(BaseModel):
    category_name: str

@app.get("/")
def read_root():
    return {"message": "працює..."}

#api-ендпоінт авторизації
@app.post("/api/login")
def api_login(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM Employee WHERE id_employee = ?", (form_data.username,))
    user = cursor.fetchone()
    
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Неправильний логін або пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    access_token = create_access_token(
        data={"sub": user["id_employee"], "role": user["empl_role"]}
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

#api-ендпоінт для отримання ключа при створенні працівника
@app.get("/api/next-employee-id")
def get_next_emp_id(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id_employee FROM Employee ORDER BY id_employee DESC LIMIT 1")
    result = cursor.fetchone()
    
    if result and result["id_employee"]:
        last_id = result["id_employee"]
        
        num_str = "".join(filter(str.isdigit, last_id))
        
        if num_str:
            next_num = int(num_str) + 1
            next_id = f"EMP{next_num:03d}" 
        else:
            next_id = "EMP001"
    else:
        next_id = "EMP001"
        
    return {"next_id": next_id}

#api-ендпоінт для отримання ключа при створенні чека
@app.get("/api/next-check-id")
def get_next_check_id(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute('SELECT check_number FROM "Check_AIS" ORDER BY check_number DESC LIMIT 1')
    result = cursor.fetchone()
    
    if result and result["check_number"]:
        last_id = result["check_number"]
        num_str = "".join(filter(str.isdigit, last_id))
        next_num = int(num_str) + 1 if num_str else 1
        return {"next_id": f"CHK{next_num:03d}"} # Наприклад: CHK00015
    return {"next_id": "CHK00001"}

#api-ендпоінт для отримання ключа при створенні карти клієнта
@app.get("/api/next-card-id")
def get_next_card_id(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT card_number FROM Customer_Card ORDER BY card_number DESC LIMIT 1")
    result = cursor.fetchone()
    
    if result and result["card_number"]:
        last_id = result["card_number"]
        num_str = "".join(filter(str.isdigit, last_id))
        
        if num_str:
            next_num = int(num_str) + 1
            next_id = f"CARD{next_num:03d}" 
        else:
            next_id = "CARD001"
    else:
        next_id = "CARD001"
        
    return {"next_id": next_id}

#права доступу

#чи дійсний токен
def get_current_user(
    request: Request, 
    token: str = Depends(oauth2_scheme), 
    db: sqlite3.Connection = Depends(get_db)
):
    # 1. Якщо токена немає в заголовку (не Swagger), шукаємо його в куках (Веб-інтерфейс)
    if not token:
        token = request.cookies.get("session_token")
        
    # 2. Якщо токена немає НІДЕ — викидаємо помилку
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не авторизовано",
        )
        
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недійсний токен")
            
        return {"id": user_id, "role": role}
        
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Токен протерміновано або пошкоджено")

#права доступу менеджера
def get_current_manager(current_user: dict = Depends(get_current_user)):
    if current_user["role"] !="Менеджер":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="доступ має лише менеджер"
        )
    return current_user
#права доступу касира (чеки)
def get_current_cashier(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "Касир":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="доступ має лише касир"
        )
    return current_user

# дії з працівниками
@app.post("/employees")
def create_employee(
    employee: EmployeeCreate, 
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_manager) 
):
    #перевірка віку 18+
    today = date.today()
    age = today.year - employee.date_of_birth.year - ((today.month, today.day) < (employee.date_of_birth.month, employee.date_of_birth.day))
    if age<18:
        raise HTTPException(status_code=400, detail="працівник має бути старшим за 18 років")
    
    hashed_pwd = get_password_hash(employee.password)
    
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO Employee (
                id_employee, empl_surname, empl_name, empl_patronymic, empl_role, 
                salary, date_of_birth, date_of_start, phone_number, 
                city, street, zip_code, password_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            employee.id_employee, employee.empl_surname, employee.empl_name, 
            employee.empl_patronymic, employee.empl_role, employee.salary, 
            employee.date_of_birth, employee.date_of_start, employee.phone_number, 
            employee.city, employee.street, employee.zip_code, hashed_pwd
        ))
        db.commit()
        return {"message": f"працівника {employee.empl_name}  найнято"}
        
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="працівник з таким ID вже існує")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка: {str(e)}")
    
#дії з чеками
@app.post("/checks")
def create_check(
    check_data: CheckCreate, 
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_cashier)
):
    cursor = db.cursor()
    
    try:
        cursor.execute('SELECT 1 FROM "Check_AIS" WHERE check_number = ?', (check_data.check_number,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="чек з таким номером вже існує")
        discount_percent = 0
        if check_data.card_number:
            cursor.execute("SELECT percent FROM Customer_Card WHERE card_number = ?", (check_data.card_number,))
            card = cursor.fetchone()
            if not card:
                raise HTTPException(status_code=404, detail="картку клієнта не знайдено")
            discount_percent = card["percent"] #знижка за відсотком на карті
        subtotal_sum = 0.0
        items_to_process = []
        for item in check_data.items:
            #ціна і кількість товарів у магазині
            cursor.execute("SELECT selling_price, products_number FROM Store_Product WHERE UPC = ?", (item.UPC,))
            store_product = cursor.fetchone()
            if not store_product:
                raise HTTPException(status_code=404, detail=f"товар з UPC {item.UPC} не знайдено в магазині")
            if store_product["products_number"] < item.product_number:
                raise HTTPException(
                    status_code=400, 
                    detail=f"товару з UPC {item.UPC} недостатньо, на складі: {store_product['products_number']}"
                )
            item_price = store_product["selling_price"]
            subtotal_sum += item_price * item.product_number 
            #кешування
            items_to_process.append({
                "UPC": item.UPC,
                "product_number": item.product_number,
                "selling_price": item_price,
                "new_stock": store_product["products_number"] -item.product_number
            }) 
        #фінальна сума +знижка
        sum_total = subtotal_sum * (1 - discount_percent / 100)
        #ПДВ
        vat = sum_total * 0.2
        
        print_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO "Check_AIS" (check_number, id_employee, card_number, print_date, sum_total, vat)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (check_data.check_number, current_user["id"], check_data.card_number, print_date, sum_total, vat))
        
        for item in items_to_process:
            #продаж певного товару
            cursor.execute("""
                INSERT INTO Sale (UPC, check_number, product_number, selling_price)
                VALUES (?, ?, ?, ?)
            """, (item["UPC"], check_data.check_number, item["product_number"], item["selling_price"]))
            cursor.execute("""
                UPDATE Store_Product 
                SET products_number = ? 
                WHERE UPC = ?
            """, (item["new_stock"], item["UPC"]))
            
        db.commit()
        
        return {
            "status": "success",
            "message": "продаж зафіксовано, чек створено",
            "check_number": check_data.check_number,
            "sum_total": round(sum_total, 2),
            "vat": round(vat, 2)
        }
    except HTTPException as he:
        db.rollback()
        raise he
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка касової транзакції: {str(e)}")
    
#дії з картками клієнтів
#додати нову картку
@app.post("/customer-cards")
def create_customer_card(
    card: CustomerCardCreate, 
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO Customer_Card (
                card_number, cust_surname, cust_name, cust_patronymic, 
                phone_number, city, street, zip_code, percent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            card.card_number, card.cust_surname, card.cust_name, card.cust_patronymic, 
            card.phone_number, card.city, card.street, card.zip_code, card.percent
        ))
        db.commit()
        return {"message": f"картку для {card.cust_name} {card.cust_surname} додано"}
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="картка з таким номером вже існує")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка: {str(e)}")
    
#редагування
#оновлення даних карти клієнта
@app.put("/customer-cards/{card_number}")
def update_customer_card(
    card_number: str,
    card_data: CustomerCardUpdate,
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Customer_Card WHERE card_number = ?", (card_number,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="картку не знайдено")
            
        cursor.execute("""
            UPDATE Customer_Card 
            SET cust_surname = ?, cust_name = ?, cust_patronymic = ?, 
                phone_number = ?, city = ?, street = ?, zip_code = ?, percent = ?
            WHERE card_number = ?
        """, (
            card_data.cust_surname, card_data.cust_name, card_data.cust_patronymic,
            card_data.phone_number, card_data.city, card_data.street, 
            card_data.zip_code, card_data.percent, card_number
        ))
        db.commit()
        return {"message": f"дані картки {card_number} оновлено"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка сервера: {str(e)}")
#редагування категорії (менеджер)
@app.put("/categories/{category_id}")
def update_category(
    category_id: int, 
    category: CategoryUpdate, 
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_manager)
):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Category WHERE category_number = ?", (category_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="категорію не знайдено")
            
        cursor.execute("UPDATE Category SET category_name = ? WHERE category_number = ?", 
                       (category.category_name, category_id))
        db.commit()
        return {"message": "категорію оновлено"}
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="така назва категорії вже існує")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

#редагування даних працівника
@app.put("/employees/{id_employee}")
def update_employee(
    id_employee: str, 
    employee: EmployeeUpdate, 
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_manager)
):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Employee WHERE id_employee = ?", (id_employee,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="працівника не знайдено")
        
        if employee.password:
            hashed_pwd = get_password_hash(employee.password)
            cursor.execute("""
                UPDATE Employee 
                SET empl_surname = ?, empl_name = ?, empl_patronymic = ?, empl_role = ?, 
                    salary = ?, phone_number = ?, city = ?, street = ?, zip_code = ?, password_hash = ?
                WHERE id_employee = ?
            """, (employee.empl_surname, employee.empl_name, employee.empl_patronymic, employee.empl_role, 
                  employee.salary, employee.phone_number, employee.city, employee.street, employee.zip_code, hashed_pwd, id_employee))
        else:
            cursor.execute("""
                UPDATE Employee 
                SET empl_surname = ?, empl_name = ?, empl_patronymic = ?, empl_role = ?, 
                    salary = ?, phone_number = ?, city = ?, street = ?, zip_code = ?
                WHERE id_employee = ?
            """, (employee.empl_surname, employee.empl_name, employee.empl_patronymic, employee.empl_role, 
                employee.salary, employee.phone_number, employee.city, employee.street, employee.zip_code, id_employee))
        db.commit()
        return {"message": "дані працівника оновлено"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

#видалення
#видалення працівника (менеджер)
@app.delete("/employees/{id_employee}")
def delete_employee(id_employee: str, db: sqlite3.Connection = Depends(get_db), current_user: dict = Depends(get_current_manager)):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Employee WHERE id_employee = ?", (id_employee,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="працівника не знайдено")
        cursor.execute("DELETE FROM Employee WHERE id_employee = ?", (id_employee,))
        db.commit()
        return {"message": "працівника звільнено"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

#видалення картки клієнта (менеджер)
@app.delete("/customer-cards/{card_number}")
def delete_customer_card(card_number: str, db: sqlite3.Connection = Depends(get_db), current_user: dict = Depends(get_current_manager)):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Customer_Card WHERE card_number = ?", (card_number,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="картку не знайдено")
        cursor.execute("DELETE FROM Customer_Card WHERE card_number = ?", (card_number,))
        db.commit()
        return {"message": "картку клієнта видалено"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

#видалення чеку (менеджер)
@app.delete("/checks/{check_number}")
def delete_check(check_number: str, db: sqlite3.Connection = Depends(get_db), current_user: dict = Depends(get_current_manager)):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Check_AIS WHERE check_number = ?", (check_number,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="чек не знайдено")
        cursor.execute("DELETE FROM Check_AIS WHERE check_number = ?", (check_number,))
        db.commit()
        return {"message": "чек видалено"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

#інформація про себе
@app.get("/employees/me")
def get_current_employee_info(
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM Employee WHERE id_employee = ?", (current_user["id"],))
    user_data = cursor.fetchone()
    if not user_data:
        raise HTTPException(status_code=404, detail="працівника не знайдено")
        
    return user_data