from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from jose import JWTError, jwt
from security import SECRET_KEY, ALGORITHM
from datetime import date, datetime
import sqlite3
from database import get_db
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from security import verify_password, create_access_token, get_password_hash
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
class ProductCreate(BaseModel):
    category_number: int
    product_name: str
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
    phone_number: str
    city: str
    street: str
    zip_code: str
    password: str

class CheckItem(BaseModel):
    UPC: str
    product_number: int

class CheckCreate(BaseModel):
    check_number: str
    card_number: str = None
    items: list[CheckItem]

class CustomerCardCreate(BaseModel):
    card_number: str
    cust_surname: str
    cust_name: str
    cust_patronymic: str = None
    phone_number: str
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

app = FastAPI(title="ZLAGODA Mini-Supermarket")


# --- Підключення UI: статика (CSS) та сторінки інтерфейсу ---
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
#авторизація
@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM Employee WHERE id_employee = ?", (form_data.username,))
    user = cursor.fetchone()
    
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=400, 
            detail="Неправильний ID працівника або пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    access_token = create_access_token(
        data={"sub": user["id_employee"], "role": user["empl_role"]}
    )
    #юзер буде мати токен що згорає за годину
    return {"access_token": access_token, "token_type": "bearer"}

#права доступу

#чи дійсний токен
def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="токен не вдалось перевірити",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        #дешифрування токену
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        employee_id: str = payload.get("sub")
        role: str = payload.get("role")
        if employee_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    return {"id_employee": employee_id, "role": role}

#права доступу менеджера
def get_current_manager(current_user: dict = Depends(get_current_user)):
    if current_user["role"] !="Менеджер":
        raise HTTPException(
            status_code=403, 
            detail="доступ має лише менеджер"
        )
    return current_user
#права доступу касира (чеки)
def get_current_cashier(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "Касир":
        raise HTTPException(
            status_code=403, 
            detail="доступ має лише касир"
        )
    return current_user
#всі категорії
@app.get("/categories")
def get_categories(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM Category ORDER BY category_name")
    categories = cursor.fetchall()
    return categories

#додати категорію
@app.post("/categories")
def create_category(category: CategoryCreate, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO Category (category_name) VALUES (?)", 
            (category.category_name,)
        )
        db.commit()
        return {"message": "категорія додана", "id": cursor.lastrowid}
    except sqlite3.IntegrityError:
        #не дозволяє дублювати категорії за назвою
        db.rollback()
        raise HTTPException(status_code=400, detail="така категорія вже є")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка сервера: {str(e)}")

#видалити категорію за ключем (менеджер)
@app.delete("/categories/{category_id}")
def delete_category(
    category_id: int, 
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_manager) 
    ):
    cursor = db.cursor()
    try:
        #чи існує категорія
        cursor.execute("SELECT * FROM Category WHERE category_number = ?", (category_id,))
        category = cursor.fetchone()
        if not category:
            raise HTTPException(status_code=404, detail="такої категорії немає")
        cursor.execute("DELETE FROM Category WHERE category_number = ?", (category_id,))
        db.commit()
        return {"message": f"категорію з ID {category_id} видалено"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка сервера: {str(e)}")
#дії з товарами
#отримати всі товари
@app.get("/products")
def get_products(
    category_number: int | None = None,
    search_name: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    #ігнорує uppercase/lowercase для вводу
    db.create_function("py_lower", 1, lambda x: x.lower() if x else x)
    cursor = db.cursor()
    query = """
        SELECT p.id_product, p.product_name, p.characteristics, p.category_number, c.category_name 
        FROM Product p
        JOIN Category c ON p.category_number = c.category_number
    """
    conds = []
    params = []
    if category_number:
        conds.append("p.category_number = ?")
        params.append(category_number)
    if search_name:
        conds.append("py_lower(p.product_name) LIKE ?")
        params.append(f"%{search_name.lower()}%") 
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY p.product_name"
    cursor.execute(query, params)
    return cursor.fetchall()

#додати товар
@app.post("/products")
def create_product(product: ProductCreate, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO Product (category_number, product_name, characteristics) VALUES (?, ?, ?)", 
            (product.category_number, product.product_name, product.characteristics)
        )
        db.commit()
        return {"message": "товар додано", "id": cursor.lastrowid}
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="такої категорії немає")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка сервера: {str(e)}")

#видалити товар
@app.delete("/products/{product_id}")
def delete_product(product_id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Product WHERE id_product = ?", (product_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="товар не знайдено")
        cursor.execute("DELETE FROM Product WHERE id_product = ?", (product_id,))
        db.commit()
        return {"message": f"товар з ID {product_id} видалено"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка сервера: {str(e)}")

#оновити товар
@app.put("/products/{product_id}")
def update_product(product_id: int, product: ProductCreate, db: sqlite3.Connection = Depends(get_db),
                   current_user: dict = Depends(get_current_manager)):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Product WHERE id_product = ?", (product_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="товар не знайдено")
        cursor.execute(
            """
            UPDATE Product 
            SET category_number = ?, product_name = ?, characteristics = ?
            WHERE id_product = ?
            """, 
            (product.category_number, product.product_name, product.characteristics, product_id)
        )
        db.commit()
        return {"message": f"товар з ID {product_id} оновлено"}
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="такої категорії немає")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка сервера: {str(e)}")
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
        """, (check_data.check_number, current_user["id_employee"], check_data.card_number, print_date, sum_total, vat))
        
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
@app.get("/customer-cards")
def get_customer_cards(
    surname: str | None = None,
    percent: int | None = None,
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    db.create_function("py_lower", 1, lambda x: x.lower() if x else x)
    cursor = db.cursor()
    query = "SELECT * FROM Customer_Card"
    conds = []
    params = []
    #пошук за прізвищем
    if surname:
        conds.append("py_lower(cust_surname) LIKE ?")
        params.append(f"%{surname.lower()}%")
    #пошук за відсотком зникжи
    if percent is not None:
        conds.append("percent = ?")
        params.append(percent)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    #сортування за прізвищем
    query += " ORDER BY cust_surname"
    cursor.execute(query, params)
    return cursor.fetchall()

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
    
#дії з товарами в магазині
#всі товари
@app.get("/store-products")
def get_store_products(
    promotional: bool | None = None,
    upc: str | None = None,
    sort_by: str = "name", #сорт за назвою чи кількістю
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    cursor = db.cursor()
    query = """
        SELECT sp.UPC, sp.UPC_prom, sp.selling_price, sp.products_number, 
               sp.promotional_product, p.product_name, p.characteristics
        FROM Store_Product sp
        JOIN Product p ON sp.id_product = p.id_product
    """
    conds = []
    params = []
    #пошук за UPC
    if upc:
        conds.append("sp.UPC = ?")
        params.append(upc)
    #фільтр акційних/безакційних товарів
    if promotional is not None:
        conds.append("sp.promotional_product = ?")
        params.append(1 if promotional else 0)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    if sort_by == "quantity":
        query += " ORDER BY sp.products_number"
    else:
        query += " ORDER BY p.product_name"
    cursor.execute(query, params)
    return cursor.fetchall()

#додати товар на полицю (менеджер)
@app.post("/store-products")
def create_store_product(
    store_product: StoreProductCreate, 
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_manager)
):
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO Store_Product (
                UPC, UPC_prom, id_product, selling_price, products_number, promotional_product
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            store_product.UPC, store_product.UPC_prom, store_product.id_product, 
            store_product.selling_price, store_product.products_number, store_product.promotional_product
        ))
        db.commit()
        return {"message": f"товар з UPC {store_product.UPC} виставлено на полицю"}
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400, 
            detail="помилка: товар з таким UPC вже є / вказано неіснуючий id_product"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"помилка сервера: {str(e)}")
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

#редагування товару в магазині (менеджер)
@app.put("/store-products/{upc}")
def update_store_product(
    upc: str, 
    store_product: StoreProductUpdate, 
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_manager)
):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Store_Product WHERE UPC = ?", (upc,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="товар в магазині не знайдено")
        cursor.execute("""
            UPDATE Store_Product 
            SET UPC_prom = ?, id_product = ?, selling_price = ?, products_number = ?, promotional_product = ?
            WHERE UPC = ?
        """, (store_product.UPC_prom, store_product.id_product, store_product.selling_price, 
              store_product.products_number, store_product.promotional_product, upc))
        db.commit()
        return {"message": "дані товару в магазині оновлено"}
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

#видалення товару з магазину (менеджер)
@app.delete("/store-products/{upc}")
def delete_store_product(upc: str, db: sqlite3.Connection = Depends(get_db), current_user: dict = Depends(get_current_manager)):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM Store_Product WHERE UPC = ?", (upc,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="товар не знайдено")
        cursor.execute("DELETE FROM Store_Product WHERE UPC = ?", (upc,))
        db.commit()
        return {"message": "товар прибрано з полиць"}
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
#інформація про працівників (менеджер)
@app.get("/employees")
def get_employees(
    role: str | None = None,
    surname: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_manager)
):
    cursor = db.cursor()
    query = """
        SELECT id_employee, empl_surname, empl_name, empl_patronymic, 
               empl_role, salary, date_of_birth, date_of_start, 
               phone_number, city, street, zip_code 
        FROM Employee
    """
    conds = []
    params = []
    #пошук за посадою
    if role:
        conds.append("empl_role = ?")
        params.append(role)
    #пошук за прізвищем
    if surname:
        conds.append("empl_surname LIKE ?")
        params.append(f"{surname}%")
        
    #всі умови задані для пошуку збираються в запит
    if conds:
        query += " WHERE " + " AND ".join(conds)   
    #сортування за прізвищем
    query += " ORDER BY empl_surname"
    cursor.execute(query, params)
    return cursor.fetchall()

#інформація про себе
@app.get("/employees/me")
def get_current_employee_info(
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM Employee WHERE id_employee = ?", (current_user["id_employee"],))
    user_data = cursor.fetchone()
    if not user_data:
        raise HTTPException(status_code=404, detail="працівника не знайдено")
        
    return user_data

@app.get("/checks")
def get_checks(
    start_date: str | None = None, #формат YYYY-MM-DD
    end_date: str | None = None, #формат YYYY-MM-DD
    id_employee: str | None = None, 
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    if start_date:
        start_date = start_date.strip()
        if start_date in ["string", "", "null", "undefined"]: start_date = None
    if end_date:
        end_date = end_date.strip()
        if end_date in ["string", "", "null", "undefined"]: end_date = None
    if id_employee:
        id_employee = id_employee.strip()
        if id_employee in ["string", "", "null", "undefined"]: id_employee = None
    cursor = db.cursor()
    
    #касир бачить тільки свої чеки
    if current_user["role"] == "Касир":
        id_employee = current_user["id_employee"]
    query = "SELECT * FROM Check_AIS WHERE 1=1"
    params = []
    #фільтр по датах
    if start_date and end_date:
        query += " AND DATE(print_date) BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    elif start_date: 
        #якщо тільки дата початку, то виведе лише чеки за цей день
        query += " AND DATE(print_date) = ?"
        params.append(start_date)
    #фільтр по ID касира (менеджер)
    if id_employee:
        query += " AND id_employee = ?"
        params.append(id_employee)
    query += " ORDER BY print_date DESC"
    cursor.execute(query, params)
    checks = cursor.fetchall()
    result = []
    for c in checks:
        check_dict = dict(c) 
        cursor.execute("""
            SELECT s.UPC, p.product_name, s.product_number, s.selling_price 
            FROM Sale s
            JOIN Store_Product sp ON s.UPC = sp.UPC
            JOIN Product p ON sp.id_product = p.id_product
            WHERE s.check_number = ?
        """, (c["check_number"],))
        check_dict["items"] = cursor.fetchall() 
        result.append(check_dict)
    return result

#інформація про чек за його номером
@app.get("/checks/{check_number}")
def get_check_details(
    check_number: str,
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM Check_AIS WHERE check_number = ?", (check_number,))
    check_data = cursor.fetchone()
    if not check_data:
        raise HTTPException(status_code=404, detail="чек не знайдено")
    #товари
    cursor.execute("""
        SELECT s.UPC, p.product_name, s.product_number, s.selling_price 
        FROM Sale s
        JOIN Store_Product sp ON s.UPC = sp.UPC
        JOIN Product p ON sp.id_product = p.id_product
        WHERE s.check_number = ?
    """, (check_number,))   
    result = dict(check_data)
    result["items"] = cursor.fetchall()
    return result

#продажі (менеджер)
@app.get("/reports/sales")
def report_sales(
    start_date: str, 
    end_date: str,   
    id_employee: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_manager)
):
    cursor = db.cursor()
    query = """
        SELECT COUNT(check_number) as total_checks, SUM(sum_total) as total_sales_sum
        FROM Check_AIS
        WHERE DATE(print_date) BETWEEN ? AND ?
    """
    params = [start_date, end_date]
    if id_employee:
        query += " AND id_employee = ?"
        params.append(id_employee)
    cursor.execute(query, params)
    result = cursor.fetchone()
    total_sales = result["total_sales_sum"] if result["total_sales_sum"] else 0.0
    return {
        "id_employee": id_employee if id_employee else "всі касири",
        "period": f"з {start_date} по {end_date}",
        "total_checks_printed": result["total_checks"],
        "total_revenue": round(total_sales, 2)
    }

#кількість проданих одиниць товару за певний час (менеджер)
@app.get("/reports/product-sales")
def report_product_sales(
    upc: str,
    start_date: str,
    end_date: str,
    db: sqlite3.Connection = Depends(get_db),
    current_user: dict = Depends(get_current_manager)
):
    cursor = db.cursor()
    cursor.execute("""
        SELECT SUM(s.product_number) as total_sold
        FROM Sale s
        JOIN Check_AIS c ON s.check_number = c.check_number
        WHERE s.UPC = ? AND DATE(c.print_date) BETWEEN ? AND ?
    """, (upc, start_date, end_date))
    result = cursor.fetchone()
    total_sold = result["total_sold"] if result["total_sold"] else 0
    return {
        "UPC": upc,
        "period": f"з {start_date} по {end_date}",
        "total_units_sold": total_sold
    }