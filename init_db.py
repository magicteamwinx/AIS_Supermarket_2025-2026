import sqlite3
from security import get_password_hash

def setup_database():
    conn = sqlite3.connect("zlagoda.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    #табл Category
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Category (
        category_number INTEGER PRIMARY KEY AUTOINCREMENT,
        category_name VARCHAR(50) NOT NULL UNIQUE
    )
    """)
    #табл Product
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Product (
        id_product INTEGER PRIMARY KEY AUTOINCREMENT,
        category_number INTEGER NOT NULL,
        product_name VARCHAR(50) NOT NULL,
        characteristics VARCHAR(100) NOT NULL,
        FOREIGN KEY (category_number) REFERENCES Category (category_number) ON UPDATE CASCADE ON DELETE NO ACTION
    )
    """)
    #табл Employee
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Employee (
        id_employee VARCHAR(10) PRIMARY KEY,
        empl_surname VARCHAR(50) NOT NULL,
        empl_name VARCHAR(50) NOT NULL,
        empl_patronymic VARCHAR(50),
        empl_role VARCHAR(10) NOT NULL,
        salary DECIMAL(13,4) NOT NULL CHECK (salary>= 0),
        date_of_birth DATE NOT NULL,
        date_of_start DATE NOT NULL,
        phone_number VARCHAR(13) NOT NULL,
        city VARCHAR(50) NOT NULL,
        street VARCHAR(50) NOT NULL,
        zip_code VARCHAR(9) NOT NULL,
        password_hash VARCHAR(255) NOT NULL
    )
    """)

    #табл Customer_Card
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Customer_Card (
        card_number VARCHAR(13) PRIMARY KEY,
        cust_surname VARCHAR(50) NOT NULL,
        cust_name VARCHAR(50) NOT NULL,
        cust_patronymic VARCHAR(50),
        phone_number VARCHAR(13) NOT NULL,
        city VARCHAR(50),
        street VARCHAR(50),
        zip_code VARCHAR(9),
        percent INTEGER NOT NULL CHECK (percent>= 0)
    )
    """)

    #табл Store_Product
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Store_Product (
        UPC VARCHAR(12) PRIMARY KEY,
        UPC_prom VARCHAR(12),
        id_product INTEGER NOT NULL,
        selling_price DECIMAL(13,4) NOT NULL CHECK (selling_price>=0),
        products_number INTEGER NOT NULL CHECK (products_number>= 0),
        promotional_product BOOLEAN NOT NULL,
        FOREIGN KEY (UPC_prom) REFERENCES Store_Product (UPC) ON UPDATE CASCADE ON DELETE SET NULL,
        FOREIGN KEY (id_product) REFERENCES Product (id_product) ON UPDATE CASCADE ON DELETE NO ACTION
    )
    """)

    #табл Check_AIS (check - reserved keyword)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS "Check_AIS" (
        check_number VARCHAR(10) PRIMARY KEY,
        id_employee VARCHAR(10) NOT NULL,
        card_number VARCHAR(13),
        print_date DATETIME NOT NULL,
        sum_total DECIMAL(13,4) NOT NULL CHECK (sum_total>= 0),
        vat DECIMAL(13,4) NOT NULL CHECK (vat>=0),
        FOREIGN KEY (id_employee) REFERENCES Employee (id_employee) ON UPDATE CASCADE ON DELETE NO ACTION,
        FOREIGN KEY (card_number) REFERENCES Customer_Card (card_number) ON UPDATE CASCADE ON DELETE NO ACTION
    )
    """)

    #табл Sale
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Sale (
        UPC VARCHAR(12) NOT NULL,
        check_number VARCHAR(10) NOT NULL,
        product_number INTEGER NOT NULL CHECK (product_number >=0),
        selling_price DECIMAL(13,4) NOT NULL CHECK (selling_price>= 0),
        PRIMARY KEY (UPC, check_number),
        FOREIGN KEY (UPC) REFERENCES Store_Product (UPC) ON UPDATE CASCADE ON DELETE NO ACTION,
        FOREIGN KEY (check_number) REFERENCES "Check_AIS" (check_number) ON UPDATE CASCADE ON DELETE CASCADE
    )
    """)
    #тестові дані
    cursor.execute("""
    INSERT OR IGNORE INTO Category (category_number, category_name) VALUES
    (1, 'Молочні продукти'),
    (2, 'Хлібобулочні вироби'),
    (3, 'М''ясні вироби'),
    (4, 'Напої'),
    (5, 'Бакалія');
    """) 

    cursor.execute("""
    INSERT OR IGNORE INTO Product (id_product, category_number, product_name, characteristics) VALUES 
    (1, 1, 'Молоко 2,5%', 'ТМ Яготинське, 900г, пляшка'),
    (2, 1, 'Сир кисломолочний', 'ТМ Простоквашино, 300г'),
    (3, 2, 'Хліб білий', 'Київхліб, нарізний, 500г'),
    (4, 2, 'Батон Нива', 'Київхліб, 400г'),
    (5, 3, 'Ковбаса Лікарська', 'ТМ Глобино, варена, 500г'),
    (6, 3, 'Сосиски Філейні', 'ТМ Бащинський, 400г'),
    (7, 4, 'Сік яблучний', 'ТМ Сандора, 1л'),
    (8, 4, 'Вода мінеральна', 'Моршинська, слабогазована, 1.5л'),
    (9, 5, 'Гречка', 'ТМ Хуторок, 800г'),
    (10, 5, 'Цукор', 'ТМ Своя Лінія, 1кг');
    """)
    
    manager_hash = get_password_hash("admin")
    cashier_hash = get_password_hash("1234")
    pass1 = get_password_hash("maramel/$$$")
    pass2 = get_password_hash("bonda356")
    pass3 = get_password_hash("petka3pka5ka")
    pass4 = get_password_hash("kravannaaswagslaysayless")
    
    cursor.execute("""
    INSERT OR IGNORE INTO Employee 
    (id_employee, empl_surname, empl_name, empl_patronymic, empl_role, salary, date_of_birth, date_of_start, phone_number, city, street, zip_code, password_hash) 
    VALUES 
    ('EMP001', 'Коваленко', 'Іван', 'Петрович', 'Менеджер', 25000.00, '1985-10-12', '2020-01-15', '+380501234567', 'Київ', 'Хрещатик, 1', '01001', ?),
    ('EMP002', 'Шевченко', 'Марія', 'Іванівна', 'Касир', 15000.00, '1995-05-20', '2022-03-10', '+380671234567', 'Київ', 'Перемоги, 15', '03056', ?),
    ('EMP003', 'Мельник', 'Олена', 'Іванівна', 'Менеджер', 25000.00, '1985-04-12', '2020-01-15', '+380501234567', 'Київ', 'Хрещатик, 1', '01001', ?),
    ('EMP004', 'Бондаренко', 'Марія', 'Василівна', 'Касир', 15000.00, '1998-11-05', '2021-06-01', '+380631234567', 'Київ', 'Шевченка, 42', '01032', ?),
    ('EMP005', 'Ткаченко', 'Петро', 'Миколайович', 'Касир', 15000.00, '2000-02-14', '2022-09-15', '+380991234567', 'Київ', 'Франка, 8', '01030', ?),
    ('EMP006', 'Кравченко', 'Анна', 'Сергіївна', 'Касир', 15000.00, '1990-07-19', '2020-11-20', '+380971234567', 'Київ', 'Лесі Українки, 24', '01133', ?);
    """, (manager_hash, cashier_hash, pass1, pass2, pass3, pass4))

    cursor.execute("""
    INSERT OR IGNORE INTO Customer_Card (card_number, cust_surname, cust_name, cust_patronymic, phone_number, city, street, zip_code, percent) VALUES 
    ('CARD001', 'Білий', 'Тарас', 'Григорович', '+380509876543', 'Київ', 'Грушевського, 5', '01008', 5),
    ('CARD002', 'Бондаренко', 'Іван', 'Якович', '+380679876543', 'Київ', 'Володимирська, 12', '01001', 10),
    ('CARD003', 'Рудюк', 'Дмитро', 'Федорович', '+380639876543', 'Київ', 'Саксаганського, 97', '01032', 20),
    ('CARD004', 'Литвинюк', 'Єлизавета', 'Федорівна', '+380689876543', 'Київ', 'Кудряшова, 16', '02000', 20),
    ('CARD005', 'Подуфалова', 'Єлизавета', 'Володимирівна', '+380999876543', 'Київ', 'Георгія Гонгадзе, 2', '04208', 10);
    """)

    cursor.execute("""
    INSERT OR IGNORE INTO Store_Product (UPC, UPC_prom, id_product, selling_price, products_number, promotional_product) VALUES 
    ('UPC001', NULL, 1, 40.50, 50, 0),
    ('UPC002', NULL, 2, 65.00, 30, 0),
    ('UPC003', 'UPC004', 3, 25.00, 20, 0),
    ('UPC004', NULL, 3, 20.00, 15, 1),
    ('UPC005', NULL, 4, 22.00, 25, 0),
    ('UPC006', NULL, 5, 150.00, 10, 0),
    ('UPC007', 'UPC008', 6, 95.00, 40, 0),
    ('UPC008', NULL, 6, 76.00, 25, 1),
    ('UPC009', NULL, 7, 55.00, 60, 0),
    ('UPC010', NULL, 8, 20.00, 100, 0),
    ('UPC011', NULL, 9, 80.00, 45, 0),
    ('UPC012', NULL, 10, 35.00, 80, 0);
    """)

    cursor.execute("""
    INSERT OR IGNORE INTO Check_AIS (check_number, id_employee, card_number, print_date, sum_total, vat) VALUES 
    ('CH001', 'EMP002', NULL, '2026-10-01 10:15:00', 201.50, 40.30),
    ('CH002', 'EMP003', 'CARD001', '2026-10-01 11:30:00', 142.50, 28.50),
    ('CH003', 'EMP004', 'CARD002', '2026-10-01 14:45:00', 485.00, 97.00),
    ('CH004', 'EMP005', 'CARD003', '2026-10-02 09:20:00', 90.00, 18.00),
    ('CH005', 'EMP002', 'CARD004', '2026-10-02 16:10:00', 1025.00, 205.00),
    ('CH006', 'EMP005', NULL, '2026-10-03 12:05:00', 340.00, 68.00),
    ('CH007', 'EMP004', 'CARD005', '2026-10-03 18:30:00', 76.00, 15.20),
    ('CH008', 'EMP002', 'CARD001', '2026-10-04 08:50:00', 452.50, 90.50),
    ('CH009', 'EMP002', NULL, '2026-10-05 09:15:00', 192.50, 38.50),
    ('CH010', 'EMP002', 'CARD002', '2026-10-05 11:45:00', 295.20, 59.04),
    ('CH011', 'EMP002', NULL, '2026-10-06 14:20:00', 230.00, 46.00),
    ('CH012', 'EMP002', 'CARD005', '2026-10-06 18:00:00', 378.00, 75.60),
    ('CH013', 'EMP003', 'CARD001', '2026-10-05 10:30:00', 57.00, 11.40),
    ('CH014', 'EMP004', NULL, '2026-10-05 16:15:00', 150.00, 30.00),
    ('CH015', 'EMP002', 'CARD003', '2026-10-06 09:05:00', 258.40, 51.68),
    ('CH016', 'EMP004', NULL, '2026-10-06 19:30:00', 200.00, 40.00),
    ('CH017', 'EMP005', NULL, '2026-10-07 08:10:00', 200.00, 40.00),
    ('CH018', 'EMP002', 'CARD002', '2026-10-08 12:00:00', 426.60, 85.32),
    ('CH019', 'EMP003', 'CARD003', '2026-10-08 14:30:00', 286.45, 57.29);
    """)

    cursor.execute("""
    INSERT OR IGNORE INTO Sale (UPC, check_number, product_number, selling_price) VALUES 
    ('UPC001', 'CH001', 2, 40.50),
    ('UPC002', 'CH001', 1, 65.00),
    ('UPC003', 'CH002', 3, 25.00),
    ('UPC006', 'CH003', 2, 150.00),
    ('UPC010', 'CH004', 5, 20.00),
    ('UPC001', 'CH005', 10, 40.50),
    ('UPC007', 'CH005', 4, 95.00),
    ('UPC012', 'CH006', 8, 35.00),
    ('UPC008', 'CH007', 1, 76.00),
    ('UPC005', 'CH008', 5, 22.00),
    ('UPC009', 'CH009', 2, 55.00),
    ('UPC011', 'CH010', 3, 80.00),
    ('UPC004', 'CH011', 10, 20.00),
    ('UPC002', 'CH012', 4, 65.00),
    ('UPC001', 'CH013', 1, 40.50),
    ('UPC006', 'CH014', 1, 150.00),
    ('UPC010', 'CH015', 6, 20.00),
    ('UPC011', 'CH016', 2, 80.00),
    ('UPC005', 'CH017', 4, 22.00),
    ('UPC007', 'CH018', 3, 95.00),
    ('UPC012', 'CH019', 5, 35.00);
    """)

    conn.commit()
    conn.close()
    print("БД оновлена")
if __name__ == "__main__":
    setup_database()