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
    
    # Tabel Pengguna (Mendukung Email, Username, Password/PIN Terenkripsi)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,      -- Email unik atau nomor WA/ID pengguna
            display_name TEXT,
            password_hash TEXT,                -- PIN/Password aman
            avatar_url TEXT,
            auth_provider TEXT DEFAULT 'local', -- 'google', 'local', atau 'whatsapp'
            theme_preference TEXT DEFAULT 'Apple Light',
            daily_calorie_target REAL DEFAULT 2000.0,
            gender TEXT DEFAULT 'Pria',
            weight_kg REAL DEFAULT 65.0,
            height_cm REAL DEFAULT 170.0,
            age_years INTEGER DEFAULT 25,
            subscription_tier TEXT DEFAULT 'free',
            pro_until TIMESTAMP,
            daily_scans_count INTEGER DEFAULT 0,
            last_scan_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrasi kolom password_hash jika belum ada
    try:
        cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN gender TEXT DEFAULT 'Pria'")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN weight_kg REAL DEFAULT 65.0")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN height_cm REAL DEFAULT 170.0")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN age_years INTEGER DEFAULT 25")
    except:
        pass
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
        
    # Tabel Log Asupan Air Harian (Water Intake Tracker)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS water_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            log_date TEXT NOT NULL,
            glasses_count INTEGER DEFAULT 0,
            target_glasses INTEGER DEFAULT 8,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, log_date)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_water_user_date ON water_logs(user_id, log_date)")
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
    
    # Tabel Antrean Moderasi / Staging Pangan Baru (Edit Sebelum Publikasi)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            food_name TEXT NOT NULL,
            category TEXT DEFAULT 'Produk Kemasan / Ritel',
            serving_unit TEXT DEFAULT '1 porsi (100g)',
            default_serving_weight REAL DEFAULT 100.0,
            energy_kcal REAL NOT NULL,
            protein_g REAL DEFAULT 0.0,
            fat_g REAL DEFAULT 0.0,
            carb_g REAL DEFAULT 0.0,
            fiber_g REAL DEFAULT 0.0,
            sodium_mg REAL DEFAULT 0.0,
            barcode TEXT,
            source_origin TEXT DEFAULT 'Open Food Facts / AI',
            submitted_by TEXT DEFAULT 'system',
            status TEXT DEFAULT 'pending', -- 'pending', 'published', 'rejected'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

ADMIN_IDENTIFIERS = {
    "nabillah",
    "muhammadnabillah0coder@gmail.com",
    "pkm tanah grogot",
    "admin"
}

import hashlib

def hash_password(password: str) -> str:
    """Hash sederhana aman untuk PIN/Password pengguna."""
    if not password:
        return ""
    return hashlib.sha256(password.strip().encode("utf-8")).hexdigest()

def register_user(user_id: str, display_name: str, pin_or_pass: str, gender: str = "Pria", bb: float = 65.0, tb: float = 170.0, age: int = 25, target_kcal: float = 2000.0):
    """
    Mendaftarkan akun baru dengan verifikasi PIN/Password dan profil tubuh pribadi.
    """
    clean_id = user_id.strip().lower()
    if not clean_id:
        return False, "ID Pengguna / Email tidak boleh kosong."
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Cek apakah ID sudah dipakai
    existing = cur.execute("SELECT id FROM users WHERE LOWER(user_id) = ?", (clean_id,)).fetchone()
    if existing:
        conn.close()
        return False, "ID Pengguna / Email ini sudah terdaftar. Silakan login."
        
    p_hash = hash_password(pin_or_pass) if pin_or_pass else ""
    is_admin = is_admin_user(clean_id)
    if is_admin:
        initial_tier = "pro"
        initial_expiry = "2099-12-31 23:59:59"
    else:
        # Bonus Sambutan: 30 Hari PRO gratis untuk setiap akun baru terdaftar
        initial_tier = "pro"
        initial_expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    
    cur.execute("""
        INSERT INTO users 
        (user_id, display_name, password_hash, auth_provider, daily_calorie_target, gender, weight_kg, height_cm, age_years, subscription_tier, pro_until)
        VALUES (?, ?, ?, 'local', ?, ?, ?, ?, ?, ?, ?)
    """, (clean_id, display_name or clean_id.capitalize(), p_hash, target_kcal, gender, bb, tb, age, initial_tier, initial_expiry))
    
    conn.commit()
    row = cur.execute("SELECT * FROM users WHERE LOWER(user_id) = ?", (clean_id,)).fetchone()
    user_dict = dict(row)
    conn.close()
    return True, user_dict

def authenticate_user(user_id: str, pin_or_pass: str):
    """
    Memverifikasi login pengguna dengan ID dan PIN/Password.
    """
    clean_id = user_id.strip().lower()
    if not clean_id:
        return False, "Ketikkan ID Pengguna / Email Anda."
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    user = cur.execute("SELECT * FROM users WHERE LOWER(user_id) = ?", (clean_id,)).fetchone()
    if not user:
        conn.close()
        return False, "Akun tidak ditemukan. Silakan klik 'Daftar Akun Baru'."
        
    u_dict = dict(user)
    saved_hash = u_dict.get("password_hash")
    
    # Jika user memiliki password_hash, wajib verifikasi
    if saved_hash:
        input_hash = hash_password(pin_or_pass)
        if input_hash != saved_hash:
            conn.close()
            return False, "PIN / Password salah! Silakan periksa kembali."
            
    conn.close()
    return True, u_dict

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

def log_water_intake(user_id: str, delta_glasses: int = 1):
    """Menambah atau mengurangi asupan air minum hari ini (+1 atau -1 gelas)."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("SELECT glasses_count FROM water_logs WHERE user_id = ? AND log_date = ?", (user_id, today_str))
    row = cur.fetchone()
    if row:
        new_count = max(0, row[0] + delta_glasses)
        cur.execute("UPDATE water_logs SET glasses_count = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND log_date = ?", (new_count, user_id, today_str))
    else:
        new_count = max(0, delta_glasses)
        cur.execute("INSERT INTO water_logs (user_id, log_date, glasses_count, target_glasses) VALUES (?, ?, ?, 8)", (user_id, today_str, new_count))
        
    conn.commit()
    conn.close()
    return new_count

def get_water_intake(user_id: str):
    """Mengambil progres air minum hari ini."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT glasses_count, target_glasses FROM water_logs WHERE user_id = ? AND log_date = ?", (user_id, today_str))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"glasses": row[0], "target": row[1], "ml": row[0] * 250, "target_ml": row[1] * 250}
    return {"glasses": 0, "target": 8, "ml": 0, "target_ml": 2000}

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

def log_meal(user_id: str, dish_name: str, totals: dict, multiplier: float = 1.0, caption: str = "", meal_type: str = "Makan Siang", log_date: str = None):
    """
    Menyimpan satu catatan makan ke buku harian pengguna dengan kategori waktu makan.
    Mendukung custom log_date (format YYYY-MM-DD) untuk mencatat makanan hari kemarin/lalu.
    Mengembalikan dict data log yang baru disimpan agar antarmuka dapat menampilkan tanda konfirmasi.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    if log_date:
        # Jika ada tanggal khusus, gabungkan dengan jam saat ini
        now_time = datetime.now().strftime("%H:%M:%S")
        custom_timestamp = f"{log_date} {now_time}"
        cur.execute("""
            INSERT INTO meal_logs 
            (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, portion_multiplier, photo_caption, meal_type, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            meal_type,
            custom_timestamp
        ))
    else:
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
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": new_id,
        "user_id": user_id,
        "dish_name": dish_name,
        "energy_kcal": totals.get("energy_kcal", 0.0),
        "meal_type": meal_type,
        "saved_at": datetime.now().strftime("%H:%M")
    }

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

def get_user_history_stats(user_id: str, target_date: str = None):
    """
    Mengambil rekapan nutrisi:
    1. Tanggal terpilih (target_date, default hari ini)
    2. 7 Hari Terakhir (Mingguan)
    3. 30 Hari Terakhir (Bulanan)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Gunakan tanggal yang diminta, atau default ke hari ini
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
        
    date_meals = cur.execute("""
        SELECT * FROM meal_logs 
        WHERE user_id = ? AND date(logged_at) = ?
        ORDER BY id DESC
    """, (user_id, target_date)).fetchall()
    
    date_totals = {
        "energy_kcal": round(sum(m["energy_kcal"] for m in date_meals), 1),
        "protein_g": round(sum(m["protein_g"] for m in date_meals), 1),
        "fat_g": round(sum(m["fat_g"] for m in date_meals), 1),
        "carb_g": round(sum(m["carb_g"] for m in date_meals), 1),
        "fiber_g": round(sum(m["fiber_g"] for m in date_meals), 1),
        "count": len(date_meals),
        "target_date": target_date
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
        "today_meals": [dict(m) for m in date_meals],
        "today_totals": date_totals,
        "weekly_data": [dict(r) for r in weekly_rows],
        "monthly_summary": {
            "total_kcal": round(monthly_row["total_kcal"] or 0.0, 1),
            "active_days": monthly_row["active_days"] or 0,
            "total_meals": monthly_row["total_meals"] or 0
        }
    }

def export_user_data_json(user_id: str) -> str:
    """
    Mengekspor data profil, preferensi, dan seluruh riwayat catatan makan pengguna ke format JSON.
    Berguna sebagai cadangan anti-hilang di sisi perangkat pengguna.
    """
    import json
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    user_row = cur.execute("SELECT user_id, display_name, daily_calorie_target, theme_preference, gender, weight_kg, height_cm, age_years, subscription_tier, created_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
    meal_rows = cur.execute("SELECT dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, portion_multiplier, photo_caption, meal_type, logged_at FROM meal_logs WHERE user_id = ? ORDER BY id ASC", (user_id,)).fetchall()
    custom_rows = cur.execute("SELECT food_name, serving_size, energy_kcal, protein_g, fat_g, carb_g FROM custom_foods WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    
    data = {
        "backup_version": "1.0",
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_profile": dict(user_row) if user_row else {"user_id": user_id},
        "meal_logs": [dict(m) for m in meal_rows],
        "custom_foods": [dict(c) for c in custom_rows]
    }
    return json.dumps(data, indent=2, ensure_ascii=False)

def import_user_data_json(user_id: str, json_str: str) -> tuple[bool, str]:
    """
    Memulihkan kembali riwayat catatan makan pengguna dari file JSON cadangan.
    """
    import json
    try:
        data = json.loads(json_str)
        meal_logs = data.get("meal_logs", [])
        if not meal_logs:
            return False, "File cadangan tidak memuat catatan makanan."
            
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        imported_count = 0
        for m in meal_logs:
            # Cek apakah log dengan nama, kalori, dan waktu yang sama persis sudah ada
            cur.execute("""
                SELECT id FROM meal_logs 
                WHERE user_id = ? AND dish_name = ? AND logged_at = ?
            """, (user_id, m["dish_name"], m.get("logged_at", "")))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO meal_logs 
                    (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, portion_multiplier, photo_caption, meal_type, logged_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    m["dish_name"],
                    m.get("energy_kcal", 0.0),
                    m.get("protein_g", 0.0),
                    m.get("fat_g", 0.0),
                    m.get("carb_g", 0.0),
                    m.get("fiber_g", 0.0),
                    m.get("portion_multiplier", 1.0),
                    m.get("photo_caption", ""),
                    m.get("meal_type", "Makan Siang"),
                    m.get("logged_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                ))
                imported_count += 1
                
        conn.commit()
        conn.close()
        return True, f"Berhasil memulihkan {imported_count} catatan makanan!"
    except Exception as e:
        return False, f"Format file cadangan tidak valid: {str(e)}"

def stage_pending_food(food_name: str, category: str, kcal_100: float, p_100: float, f_100: float, c_100: float, fib_100: float = 0.0, sod_100: float = 0.0, barcode: str = "", serving_unit: str = "1 porsi (100g)", serving_weight: float = 100.0, source_origin: str = "Open Food Facts", submitted_by: str = "system"):
    """
    Menyimpan data pangan baru ke tabel antrean (pending_foods) agar dapat ditinjau/diedit
    terlebih dahulu sebelum dipublikasikan ke database utama (menghindari update mendadak).
    """
    clean_name = food_name.strip()
    if not clean_name or kcal_100 < 0:
        return None
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Cek apakah sudah ada di food_composition atau pending_foods
    if barcode:
        ex_main = cur.execute("SELECT id FROM food_composition WHERE barcode = ?", (barcode.strip(),)).fetchone()
        ex_pend = cur.execute("SELECT id FROM pending_foods WHERE barcode = ? AND status = 'pending'", (barcode.strip(),)).fetchone()
        if ex_main or ex_pend:
            conn.close()
            return None
    ex_name = cur.execute("SELECT id FROM pending_foods WHERE LOWER(food_name) = LOWER(?) AND status = 'pending'", (clean_name,)).fetchone()
    if ex_name:
        conn.close()
        return ex_name[0]
        
    cur.execute("""
        INSERT INTO pending_foods 
        (food_name, category, serving_unit, default_serving_weight, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode, source_origin, submitted_by, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
    """, (
        clean_name, category, serving_unit, float(serving_weight),
        round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
        round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
        barcode.strip() if barcode else None, source_origin, submitted_by
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id

def get_pending_foods(status: str = "pending"):
    """Mengambil daftar pangan yang menunggu kurasi/edit sebelum publikasi."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM pending_foods WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def publish_food_to_catalog(food_name: str, category: str, kcal_100: float, p_100: float, f_100: float, c_100: float, fib_100: float = 0.0, sod_100: float = 0.0, barcode: str = "", serving_unit: str = "1 porsi", serving_weight: float = 100.0, pending_id: int = None):
    """
    Mempublikasikan data pangan yang sudah diverifikasi/diedit ke dalam katalog utama food_composition.
    Jika barcode atau nama sudah ada, melakukan update; jika belum, melakukan insert.
    """
    clean_name = food_name.strip()
    clean_barcode = barcode.strip() if barcode else None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    existing = None
    if clean_barcode:
        existing = cur.execute("SELECT id FROM food_composition WHERE barcode = ? LIMIT 1", (clean_barcode,)).fetchone()
    if not existing:
        existing = cur.execute("SELECT id FROM food_composition WHERE LOWER(food_name) = LOWER(?) LIMIT 1", (clean_name,)).fetchone()
        
    if existing:
        cur.execute("""
            UPDATE food_composition 
            SET food_name = ?, category = ?, serving_unit = ?, default_serving_weight = ?,
                energy_kcal = ?, protein_g = ?, fat_g = ?, carb_g = ?, fiber_g = ?, sodium_mg = ?,
                barcode = COALESCE(?, barcode)
            WHERE id = ?
        """, (
            clean_name, category, serving_unit, float(serving_weight),
            round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
            round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
            clean_barcode, existing["id"]
        ))
    else:
        code_hash = hashlib.md5(clean_name.encode("utf-8")).hexdigest()[:6].upper()
        food_code = f"MN_{code_hash}"
        cur.execute("""
            INSERT INTO food_composition 
            (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode)
            VALUES (?, ?, ?, ?, ?, 100.0, ?, ?, ?, ?, ?, ?, ?)
        """, (
            food_code, clean_name, category, serving_unit, float(serving_weight),
            round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
            round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
            clean_barcode
        ))
        
    if pending_id is not None:
        cur.execute("UPDATE pending_foods SET status = 'published' WHERE id = ?", (pending_id,))
        
    conn.commit()
    conn.close()
    return True

def reject_pending_food(pending_id: int):
    """Menolak/menghapus item dari antrean draft."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE pending_foods SET status = 'rejected' WHERE id = ?", (pending_id,))
    conn.commit()
    conn.close()
    return True

if __name__ == "__main__":
    init_user_history_tables()
    print("Tabel users dan meal_logs berhasil dibuat!")
