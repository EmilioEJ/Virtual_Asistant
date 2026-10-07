import sqlite3
import hashlib
import hmac
import os

DB_PATH = "users.db"

PBKDF2_ITERACIONES = 310_000

def hash_password(password: str) -> str:
    # PBKDF2-HMAC-SHA256 con salt aleatorio: pbkdf2_sha256$iteraciones$salt$hash
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), PBKDF2_ITERACIONES).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERACIONES}${salt}${digest}"

def es_hash_legado(stored_hash: str) -> bool:
    # Hashes de versiones anteriores: SHA-256 sin salt
    return not stored_hash.startswith("pbkdf2_sha256$")

def verify_password(password: str, stored_hash: str) -> bool:
    if es_hash_legado(stored_hash):
        return hmac.compare_digest(hashlib.sha256(password.encode('utf-8')).hexdigest(), stored_hash)
    _, iteraciones, salt, digest = stored_hash.split("$")
    calculado = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), int(iteraciones)).hex()
    return hmac.compare_digest(calculado, digest)

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
    # Contraseña inicial configurable; definir INITIAL_USER_PASSWORD en .env en producción
    regular_pass = os.getenv("INITIAL_USER_PASSWORD", "eespinozajimenez")
    
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
    # Contraseña inicial configurable; definir INITIAL_ADMIN_PASSWORD en .env en producción
    admin_pass = os.getenv("INITIAL_ADMIN_PASSWORD", "admin_eespinozajimenez")
    
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
