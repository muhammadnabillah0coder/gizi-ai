"""
Database History & Multi-User Manager (Gizi.AI)
Mengelola profil pengguna (termasuk email/Google Account) dan riwayat log makanan harian.
"""

import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

def init_user_history_tables():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Tabel Pengguna (Mendukung Username & Google Account Email)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,      -- Bisa email Google (misal: user@gmail.com) atau username
            display_name TEXT,
            avatar_url TEXT,
            auth_provider TEXT DEFAULT 'local', -- 'google' atau 'local'
            daily_calorie_target REAL DEFAULT 2000.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Tabel Log Makanan
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meal_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            dish_name TEXT NOT NULL,
            energy_kcal REAL NOT NULL,
            protein_g REAL NOT NULL,
            fat_g REAL NOT NULL,
            carb_g REAL NOT NULL,
            fiber_g REAL NOT NULL,
            portion_multiplier REAL DEFAULT 1.0,
            photo_caption TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_meal_user ON meal_logs(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_meal_date ON meal_logs(logged_at)")
    
    conn.commit()
    conn.close()

def get_or_create_user(user_id: str, display_name: str = "", auth_provider: str = "local"):
    """
    Mengambil data user atau membuat profil baru jika belum ada.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    row = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        name = display_name or user_id.split("@")[0].capitalize()
        cur.execute("""
            INSERT INTO users (user_id, display_name, auth_provider, daily_calorie_target)
            VALUES (?, ?, ?, 2000.0)
        """, (user_id, name, auth_provider))
        conn.commit()
        row = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        
    user_dict = dict(row)
    conn.close()
    return user_dict

def update_calorie_target(user_id: str, target_kcal: float):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET daily_calorie_target = ? WHERE user_id = ?", (target_kcal, user_id))
    conn.commit()
    conn.close()

def log_meal(user_id: str, dish_name: str, totals: dict, multiplier: float = 1.0, caption: str = ""):
    """
    Menyimpan satu catatan makan ke buku harian pengguna.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO meal_logs 
        (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, portion_multiplier, photo_caption)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        dish_name,
        totals.get("energy_kcal", 0.0),
        totals.get("protein_g", 0.0),
        totals.get("fat_g", 0.0),
        totals.get("carb_g", 0.0),
        totals.get("fiber_g", 0.0),
        multiplier,
        caption
    ))
    conn.commit()
    conn.close()
    return True

def get_user_history_stats(user_id: str):
    """
    Mengambil rekapan nutrisi:
    1. Hari ini
    2. 7 Hari Terakhir (Mingguan)
    3. 30 Hari Terakhir (Bulanan)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Hari ini (sejak jam 00:00)
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_meals = cur.execute("""
        SELECT * FROM meal_logs 
        WHERE user_id = ? AND date(logged_at) = date('now', 'localtime')
        ORDER BY id DESC
    """, (user_id,)).fetchall()
    
    today_totals = {
        "energy_kcal": round(sum(m["energy_kcal"] for m in today_meals), 1),
        "protein_g": round(sum(m["protein_g"] for m in today_meals), 1),
        "fat_g": round(sum(m["fat_g"] for m in today_meals), 1),
        "carb_g": round(sum(m["carb_g"] for m in today_meals), 1),
        "fiber_g": round(sum(m["fiber_g"] for m in today_meals), 1),
        "count": len(today_meals)
    }
    
    # 7 Hari Terakhir (Harian untuk Chart)
    weekly_rows = cur.execute("""
        SELECT date(logged_at, 'localtime') as day, 
               sum(energy_kcal) as total_kcal,
               count(*) as meals_count
        FROM meal_logs
        WHERE user_id = ? AND date(logged_at, 'localtime') >= date('now', 'localtime', '-6 days')
        GROUP BY day
        ORDER BY day ASC
    """, (user_id,)).fetchall()
    
    # 30 Hari Terakhir (Bulanan)
    monthly_row = cur.execute("""
        SELECT sum(energy_kcal) as total_kcal,
               count(DISTINCT date(logged_at, 'localtime')) as active_days,
               count(*) as total_meals
        FROM meal_logs
        WHERE user_id = ? AND date(logged_at, 'localtime') >= date('now', 'localtime', '-29 days')
    """, (user_id,)).fetchone()
    
    conn.close()
    
    return {
        "today_meals": [dict(m) for m in today_meals],
        "today_totals": today_totals,
        "weekly_data": [dict(r) for r in weekly_rows],
        "monthly_summary": {
            "total_kcal": round(monthly_row["total_kcal"] or 0.0, 1),
            "active_days": monthly_row["active_days"] or 0,
            "total_meals": monthly_row["total_meals"] or 0
        }
    }

if __name__ == "__main__":
    init_user_history_tables()
    print("Tabel users dan meal_logs berhasil dibuat!")
