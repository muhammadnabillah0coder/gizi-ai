"""
Database Seed: Tabel Komposisi Pangan Indonesia (TKPI Kemenkes RI)
Nilai nutrisi disajikan per 100 gram BDD (Bagian yang Dapat Dimakan).
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

# Sample data komposisi pangan Indonesia berbasis TKPI Kemenkes & URT standard
# Kolom: food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg
TKPI_DATA = [
    # --- Makanan Pokok & Karbohidrat ---
    ("MP001", "Nasi putih", "Makanan Pokok", "1 centong", 100.0, 100.0, 130.0, 2.4, 0.2, 28.6, 0.4, 1.0),
    ("MP002", "Lontong / Ketupat", "Makanan Pokok", "1 buah sedang", 100.0, 100.0, 144.0, 2.7, 0.2, 31.8, 0.5, 9.0),
    ("MP003", "Mie kuning basah / Mie baso", "Makanan Pokok", "1 mangkok", 150.0, 100.0, 138.0, 4.5, 3.3, 22.5, 1.2, 18.0),
    ("MP004", "Kentang rebus", "Makanan Pokok", "1 buah sedang", 100.0, 85.0, 87.0, 1.9, 0.1, 20.1, 1.8, 4.0),
    ("MP005", "Bubur beras", "Makanan Pokok", "1 mangkok", 250.0, 100.0, 50.0, 0.9, 0.1, 10.8, 0.2, 2.0),
    
    # --- Lauk Pauk (Hewani & Nabati) ---
    ("LK001", "Ayam goreng paha/dada", "Lauk Hewani", "1 potong sedang", 80.0, 70.0, 260.0, 25.0, 17.0, 1.0, 0.0, 280.0),
    ("LK002", "Ayam bakar", "Lauk Hewani", "1 potong sedang", 80.0, 70.0, 215.0, 26.5, 11.2, 2.5, 0.0, 310.0),
    ("LK003", "Telur ayam rebus", "Lauk Hewani", "1 butir", 55.0, 89.0, 155.0, 12.6, 10.6, 1.1, 0.0, 124.0),
    ("LK004", "Telur dadar / ceplok", "Lauk Hewani", "1 butir", 60.0, 89.0, 196.0, 13.5, 14.8, 1.5, 0.0, 185.0),
    ("LK005", "Daging sapi rendang", "Lauk Hewani", "1 potong", 50.0, 100.0, 255.0, 21.0, 16.5, 6.0, 1.5, 350.0),
    ("LK006", "Ikan lele goreng", "Lauk Hewani", "1 ekor sedang", 90.0, 75.0, 240.0, 17.5, 18.0, 1.5, 0.0, 160.0),
    ("LK007", "Tahu goreng", "Lauk Nabati", "1 potong sedang", 40.0, 100.0, 115.0, 9.7, 7.3, 2.5, 1.2, 10.0),
    ("LK008", "Tempe goreng tepung/biasa", "Lauk Nabati", "1 potong sedang", 35.0, 100.0, 200.0, 14.0, 12.5, 8.0, 2.8, 15.0),
    
    # --- Sayuran & Bahan Campur ---
    ("SY001", "Sayuran rebus campur (kangkung, tauge, kubis, kacang panjang)", "Sayuran", "1 porsi", 120.0, 100.0, 35.0, 2.2, 0.4, 6.8, 2.5, 25.0),
    ("SY002", "Tauge rebus", "Sayuran", "1 mangkok kecil", 60.0, 100.0, 23.0, 2.9, 0.2, 3.2, 1.4, 6.0),
    ("SY003", "Kangkung tumis", "Sayuran", "1 porsi sedang", 100.0, 100.0, 65.0, 3.0, 4.2, 4.5, 2.1, 180.0),
    ("SY004", "Sayur sop campur", "Sayuran", "1 mangkok", 150.0, 100.0, 42.0, 1.8, 1.5, 6.0, 1.8, 220.0),
    ("SY005", "Timun mentah", "Sayuran", "3 iris", 30.0, 90.0, 12.0, 0.6, 0.1, 2.4, 0.5, 2.0),

    # --- Saus, Bumbu, & Pelengkap ---
    ("PL001", "Bumbu kacang gado-gado / sate", "Bumbu/Saus", "3 sendok makan", 50.0, 100.0, 380.0, 15.0, 28.0, 20.0, 4.5, 420.0),
    ("PL002", "Sambal terasi / ulek", "Bumbu/Pelengkap", "1 sendok teh", 15.0, 100.0, 45.0, 1.0, 2.5, 4.5, 1.0, 210.0),
    ("PL003", "Kerupuk putih kaleng", "Pelengkap", "1 buah", 15.0, 100.0, 480.0, 1.5, 22.0, 70.0, 0.5, 450.0),
    ("PL004", "Emping melinjo", "Pelengkap", "5 keping", 15.0, 100.0, 450.0, 12.0, 19.5, 60.0, 1.5, 280.0),
    ("PL005", "Bawang goreng", "Pelengkap", "1 sendok teh", 5.0, 100.0, 520.0, 6.0, 38.0, 40.0, 3.0, 50.0),

    # --- Menu Komposit Jadi (Standar URT) ---
    ("MK001", "Gado-gado lengkap (lontong, telur, bumbu kacang)", "Menu Komposit", "1 piring lengkap", 350.0, 100.0, 125.0, 5.2, 5.8, 13.5, 2.1, 160.0), # per 100g = ~437 kkal total
    ("MK002", "Bakso sapi komplit (mie, tahu, 5 bakso kecil)", "Menu Komposit", "1 mangkok", 380.0, 100.0, 85.0, 6.0, 3.5, 7.5, 0.8, 380.0), # per 100g = ~323 kkal total
    ("MK003", "Soto ayam (kuah bening + bihun + suwir ayam)", "Menu Komposit", "1 mangkok", 300.0, 100.0, 70.0, 5.5, 2.8, 6.0, 0.5, 340.0),
    ("MK004", "Nasi goreng telur standar penjual", "Menu Komposit", "1 piring", 250.0, 100.0, 168.0, 5.1, 6.5, 22.5, 1.0, 320.0)
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS food_composition (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            food_code TEXT UNIQUE,
            food_name TEXT NOT NULL,
            category TEXT,
            serving_unit TEXT,
            default_serving_weight REAL,
            bdd_rate REAL,
            energy_kcal REAL,
            protein_g REAL,
            fat_g REAL,
            carb_g REAL,
            fiber_g REAL,
            sodium_mg REAL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_food_name ON food_composition(food_name)")
    
    cur.executemany("""
        INSERT OR REPLACE INTO food_composition 
        (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, TKPI_DATA)
    
    conn.commit()
    count = cur.execute("SELECT count(*) FROM food_composition").fetchone()[0]
    conn.close()
    print(f"Database TKPI berhasil diinisialisasi di {DB_PATH} dengan {count} item pangan.")

if __name__ == "__main__":
    init_db()
