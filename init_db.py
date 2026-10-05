import sqlite3
import hashlib
import os

DB_PATH = "users.db"

def hash_password(password: str) -> str:
    # Hash simple con salt integrado para evitar texto plano
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Crear tabla de usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    # Crear tabla de sesiones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_token TEXT PRIMARY KEY,
            username TEXT NOT NULL
        )
    ''')
    
    # Insertar el usuario regular inicial
    regular_user = "eespinozajimenez"
    regular_pass = "eespinozajimenez"
    
    # Comprobar si ya existe regular
    cursor.execute("SELECT id FROM users WHERE username = ?", (regular_user,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (regular_user, hash_password(regular_pass))
        )
        print(f"Usuario regular '{regular_user}' creado exitosamente.")
    else:
        print(f"El usuario regular '{regular_user}' ya existe.")

    # Insertar el usuario administrador especial
    admin_user = "admin_eespinozajimenez"
    admin_pass = "admin_eespinozajimenez"
    
    # Comprobar si ya existe admin
    cursor.execute("SELECT id FROM users WHERE username = ?", (admin_user,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (admin_user, hash_password(admin_pass))
        )
        print(f"Usuario administrador '{admin_user}' creado exitosamente.")
    else:
        print(f"El usuario administrador '{admin_user}' ya existe.")
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
