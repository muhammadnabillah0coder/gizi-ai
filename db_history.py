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
    
    # Tabel Pengguna (Mendukung Username, Google Email, dan Preferensi Tema UI)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,      -- Bisa email Google (misal: user@gmail.com) atau username
            display_name TEXT,
            avatar_url TEXT,
            auth_provider TEXT DEFAULT 'local', -- 'google' atau 'local'
            theme_preference TEXT DEFAULT 'Apple Light', -- 'Apple Light', 'Cal AI Dark', 'Mint Fresh'
            daily_calorie_target REAL DEFAULT 2000.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrasi kolom theme_preference jika belum ada
    try:
        cur.execute("ALTER TABLE users ADD COLUMN theme_preference TEXT DEFAULT 'Apple Light'")
    except:
        pass
        
    # Migrasi kolom subscription_tier dan scan quota
    try:
        cur.execute("ALTER TABLE users ADD COLUMN subscription_tier TEXT DEFAULT 'free'")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN pro_until TIMESTAMP")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN daily_scans_count INTEGER DEFAULT 0")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_scan_date TEXT")
    except:
        pass
    
    # Tabel Log Makanan (Mendukung Kategori Waktu Makan)
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
            meal_type TEXT DEFAULT 'Makan Siang', -- 'Sarapan', 'Makan Siang', 'Makan Malam', 'Camilan'
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrasi kolom meal_type jika belum ada
    try:
        cur.execute("ALTER TABLE meal_logs ADD COLUMN meal_type TEXT DEFAULT 'Makan Siang'")
    except:
        pass
    # Tabel Makanan Kustom Pribadi (Fitur Input Manual User)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS custom_foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            food_name TEXT NOT NULL,
            serving_size TEXT DEFAULT '1 porsi',
            energy_kcal REAL NOT NULL,
            protein_g REAL DEFAULT 0.0,
            fat_g REAL DEFAULT 0.0,
            carb_g REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_custom_food_user ON custom_foods(user_id)")
    
    conn.commit()
    conn.close()

ADMIN_IDENTIFIERS = {
    "nabillah",
    "muhammadnabillah0coder@gmail.com",
    "pkm tanah grogot",
    "admin"
}

def is_admin_user(user_id: str) -> bool:
    """Mengecek apakah user adalah Founder / Admin aplikasi."""
    if not user_id:
        return False
    uid = user_id.strip().lower()
    return uid in ADMIN_IDENTIFIERS or "nabillah" in uid or "admin" in uid

def get_or_create_user(user_id: str, display_name: str = "", auth_provider: str = "local"):
    """
    Mengambil data user atau membuat profil baru jika belum ada.
    Jika user adalah Admin / Founder (Nabillah), otomatis mendapatkan status PRO Seumur Hidup.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    is_admin = is_admin_user(user_id)
    initial_tier = "pro" if is_admin else "free"
    initial_expiry = "2099-12-31 23:59:59" if is_admin else None
    
    row = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        name = display_name or user_id.split("@")[0].capitalize()
        cur.execute("""
            INSERT INTO users (user_id, display_name, auth_provider, daily_calorie_target, subscription_tier, pro_until)
            VALUES (?, ?, ?, 2000.0, ?, ?)
        """, (user_id, name, auth_provider, initial_tier, initial_expiry))
        conn.commit()
        row = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    else:
        # Jika user yang sudah ada adalah admin, pastikan statusnya selalu PRO
        if is_admin and row["subscription_tier"] != "pro":
            cur.execute("UPDATE users SET subscription_tier = 'pro', pro_until = '2099-12-31 23:59:59' WHERE user_id = ?", (user_id,))
            conn.commit()
            row = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        
    user_dict = dict(row)
    conn.close()
    return user_dict

def add_custom_food(user_id: str, food_name: str, serving_size: str, kcal: float, protein: float, fat: float, carb: float):
    """Menyimpan makanan manual buatan pengguna sendiri."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO custom_foods (user_id, food_name, serving_size, energy_kcal, protein_g, fat_g, carb_g)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, food_name, serving_size, kcal, protein, fat, carb))
    conn.commit()
    conn.close()
    return True

def get_custom_foods(user_id: str):
    """Mengambil daftar makanan kustom yang pernah disimpan pengguna."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM custom_foods WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_custom_food(food_id: int, user_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM custom_foods WHERE id = ? AND user_id = ?", (food_id, user_id))
    conn.commit()
    conn.close()
    return True

def update_calorie_target(user_id: str, target_kcal: float):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET daily_calorie_target = ? WHERE user_id = ?", (target_kcal, user_id))
    conn.commit()
    conn.close()

def update_user_theme(user_id: str, theme_name: str):
    """Menyimpan tema pilihan pengguna ke database permanen."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET theme_preference = ? WHERE user_id = ?", (theme_name, user_id))
    conn.commit()
    conn.close()

def get_user_scan_status(user_id: str):
    """
    Memeriksa kuota scan foto harian user (3x gratis per hari untuk Free member, unlimited untuk Pro).
    Juga memeriksa apakah masa aktif PRO masih berlaku.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    user = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    
    if not user:
        return {"tier": "free", "scans_today": 0, "max_scans": 3, "can_scan": True, "is_pro": False, "days_left": 0}
        
    u_dict = dict(user)
    is_admin = is_admin_user(user_id)
    tier = u_dict.get("subscription_tier") or "free"
    pro_until_str = u_dict.get("pro_until")
    
    is_pro = False
    days_left = 0
    if is_admin:
        is_pro = True
        tier = "pro"
        days_left = 9999
    elif tier == "pro" and pro_until_str:
        try:
            expiry_dt = datetime.strptime(pro_until_str, "%Y-%m-%d %H:%M:%S")
            now_dt = datetime.now()
            if expiry_dt > now_dt:
                is_pro = True
                days_left = max(1, (expiry_dt - now_dt).days)
            else:
                # Masa trial/pro habis, kembalikan ke free
                is_pro = False
                tier = "free"
        except:
            is_pro = True
            
    today_str = datetime.now().strftime("%Y-%m-%d")
    last_date = u_dict.get("last_scan_date")
    scans_today = u_dict.get("daily_scans_count") or 0
    
    if last_date != today_str:
        scans_today = 0
        
    can_scan = True if is_pro else (scans_today < 3)
    
    return {
        "tier": tier,
        "scans_today": scans_today,
        "max_scans": 9999 if is_pro else 3,
        "can_scan": can_scan,
        "is_pro": is_pro,
        "days_left": days_left
    }

def record_scan_usage(user_id: str):
    """Mencatat 1 kali pemakaian scan foto makanan."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    row = cur.execute("SELECT last_scan_date, daily_scans_count FROM users WHERE user_id = ?", (user_id,)).fetchone()
    
    if row:
        last_date, count = row[0], row[1] or 0
        new_count = 1 if last_date != today_str else count + 1
        cur.execute("UPDATE users SET last_scan_date = ?, daily_scans_count = ? WHERE user_id = ?", (today_str, new_count, user_id))
    conn.commit()
    conn.close()

def activate_pro_tier(user_id: str, days: int = 30):
    """Mengaktifkan langganan Pro untuk pengguna."""
    expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET subscription_tier = 'pro', pro_until = ? WHERE user_id = ?", (expiry, user_id))
    conn.commit()
    conn.close()
    return expiry

def log_meal(user_id: str, dish_name: str, totals: dict, multiplier: float = 1.0, caption: str = "", meal_type: str = "Makan Siang"):
    """
    Menyimpan satu catatan makan ke buku harian pengguna dengan kategori waktu makan.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO meal_logs 
        (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, portion_multiplier, photo_caption, meal_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        dish_name,
        totals.get("energy_kcal", 0.0),
        totals.get("protein_g", 0.0),
        totals.get("fat_g", 0.0),
        totals.get("carb_g", 0.0),
        totals.get("fiber_g", 0.0),
        multiplier,
        caption,
        meal_type
    ))
    conn.commit()
    conn.close()
    return True

def delete_meal_log(log_id: int, user_id: str):
    """
    Menghapus satu catatan makan berdasarkan ID milik user yang sedang aktif.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM meal_logs WHERE id = ? AND user_id = ?", (log_id, user_id))
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
