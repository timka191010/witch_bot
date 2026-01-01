import sqlite3

def init_db():
    """Создание базы данных и таблицы для анкет"""
    conn = sqlite3.connect('witches_club.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS applications (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        age INTEGER,
        city TEXT,
        about TEXT,
        why_join TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ База данных создана!")

def save_application(user_id, username, data):
    """Сохранение анкеты пользователя"""
    conn = sqlite3.connect('witches_club.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT OR REPLACE INTO applications 
    (user_id, username, full_name, age, city, about, why_join)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, username, data['name'], data['age'], 
          data['city'], data['about'], data['why']))
    
    conn.commit()
    conn.close()

def get_application(user_id):
    """Получение анкеты по ID пользователя"""
    conn = sqlite3.connect('witches_club.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM applications WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result
