import psycopg2
from psycopg2.extras import RealDictCursor
import os

DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            name TEXT NOT NULL,
            age TEXT NOT NULL,
            family_status TEXT NOT NULL,
            children TEXT NOT NULL,
            hobbies TEXT NOT NULL,
            themes TEXT NOT NULL,
            goal TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ База данных PostgreSQL создана!")

def save_application(anketa):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO applications (user_id, name, age, family_status, children, hobbies, themes, goal, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        anketa['user_id'],
        anketa['name'],
        anketa['age'],
        anketa['family_status'],
        anketa['children'],
        anketa['hobbies'],
        anketa['themes'],
        anketa['goal'],
        anketa['source']
    ))
    
    conn.commit()
    cursor.close()
    conn.close()

def get_all_applications():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM applications ORDER BY created_at DESC')
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return [dict(row) for row in rows]

def clear_all_applications():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM applications')
    
    conn.commit()
    cursor.close()
    conn.close()

def get_application(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM applications WHERE user_id = %s', (user_id,))
    row = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return dict(row) if row else None
