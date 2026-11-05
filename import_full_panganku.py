"""
Skrip Impor Lengkap: 1.146 Data Pangan Laboratorium Kemenkes RI (Panganku.org / TKPI)
Mengunduh dataset resmi Parquet dan menyimpannya ke dalam SQLite tkpi_nutrition.db
"""

import sqlite3
import os
import pandas as pd
import numpy as np

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")
PARQUET_URL = "https://huggingface.co/datasets/ichsanulamal/panganku-indonesian-food-nutrition/resolve/main/data.parquet"

def clean_val(val, default=0.0):
    if pd.isna(val) or val is None:
        return default
    try:
        if isinstance(val, str):
            val = val.replace(",", ".").strip()
        return float(val)
    except:
        return default

def import_full_tkpi_dataset():
    print("Mengunduh dataset resmi Panganku (1.146 item pangan)...")
    df = pd.read_parquet(PARQUET_URL)
    print(f"Data mentah berhasil dimuat: {len(df)} baris.")

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

    # 1. Masukkan data kurasi makanan harian & URT penting dengan kode awalan CUST_ agar tidak tertimpa
    essential_extras = [
        ("CUST_AIR1", "Air Mineral", "Minuman", "1 gelas", 250.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        ("CUST_AIR2", "Air Putih", "Minuman", "1 gelas", 250.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        ("CUST_AIR3", "Air Panas / Dingin", "Minuman", "1 gelas", 250.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        ("CUST_KOPI1", "Kopi hitam polos tanpa gula", "Minuman", "1 cangkir", 150.0, 100.0, 2.0, 0.1, 0.0, 0.3, 0.0, 2.0),
        ("CUST_TEH1", "Teh tawar hangat / es teh tawar", "Minuman", "1 gelas", 200.0, 100.0, 1.0, 0.0, 0.0, 0.2, 0.0, 3.0),
        ("CUST_TEH2", "Es teh manis", "Minuman", "1 gelas", 250.0, 100.0, 90.0, 0.0, 0.0, 22.0, 0.0, 5.0),
        ("CUST_KOPI2", "Kopi susu gula aren", "Minuman", "1 cup", 250.0, 100.0, 180.0, 3.5, 5.0, 30.0, 0.5, 65.0),
        ("CUST_NASI", "Nasi putih", "Makanan Pokok", "1 centong", 100.0, 100.0, 130.0, 2.4, 0.2, 28.6, 0.4, 1.0),
        ("CUST_LONT", "Lontong", "Makanan Pokok", "1 buah", 100.0, 100.0, 144.0, 2.7, 0.2, 31.8, 0.5, 9.0),
        ("CUST_AYAM1", "Ayam goreng paha/dada", "Lauk Hewani", "1 potong", 80.0, 70.0, 260.0, 25.0, 17.0, 1.0, 0.0, 280.0),
        ("CUST_AYAM2", "Ayam bakar", "Lauk Hewani", "1 potong", 80.0, 70.0, 215.0, 26.5, 11.2, 2.5, 0.0, 310.0),
        ("CUST_TELUR1", "Telur ayam rebus", "Lauk Hewani", "1 butir", 55.0, 89.0, 155.0, 12.6, 10.6, 1.1, 0.0, 124.0),
        ("CUST_TELUR2", "Telur dadar / ceplok", "Lauk Hewani", "1 butir", 60.0, 89.0, 196.0, 13.5, 14.8, 1.5, 0.0, 185.0),
        ("CUST_TAHU", "Tahu goreng", "Lauk Nabati", "1 potong", 40.0, 100.0, 115.0, 9.7, 7.3, 2.5, 1.2, 10.0),
        ("CUST_TEMPE", "Tempe goreng", "Lauk Nabati", "1 potong", 35.0, 100.0, 200.0, 14.0, 12.5, 8.0, 2.8, 15.0),
        ("CUST_SAYUR", "Sayuran rebus campur", "Sayuran", "1 porsi", 120.0, 100.0, 35.0, 2.2, 0.4, 6.8, 2.5, 25.0),
        ("CUST_KACANG", "Bumbu kacang gado-gado", "Bumbu/Saus", "3 sdm", 50.0, 100.0, 380.0, 15.0, 28.0, 20.0, 4.5, 420.0),
        ("CUST_KERUPUK", "Kerupuk putih kaleng", "Pelengkap", "1 buah", 15.0, 100.0, 480.0, 1.5, 22.0, 70.0, 0.5, 450.0),
        ("CUST_SAMBAL", "Sambal terasi", "Pelengkap", "1 sdt", 15.0, 100.0, 45.0, 1.0, 2.5, 4.5, 1.0, 210.0)
    ]

    cur.executemany("""
        INSERT OR REPLACE INTO food_composition 
        (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, essential_extras)

    # Masukkan 1.146 item dari Panganku
    inserted_count = 0
    for _, row in df.iterrows():
        code = str(row.get("Kode", "")).strip()
        name = str(row.get("Nama", "")).strip()
        category = str(row.get("Kategori", "Umum")).strip()
        
        bdd = clean_val(row.get("BDD"), default=100.0)
        energy = clean_val(row.get("Energy"), default=0.0)
        protein = clean_val(row.get("Protein"), default=0.0)
        fat = clean_val(row.get("Fat"), default=0.0)
        carb = clean_val(row.get("CHO"), default=0.0)
        fiber = clean_val(row.get("Fibre"), default=0.0)
        sodium = clean_val(row.get("Na"), default=0.0)
        
        cur.execute("""
            INSERT OR REPLACE INTO food_composition 
            (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, name, category, "100 gram", 100.0, bdd, energy, protein, fat, carb, fiber, sodium))
        inserted_count += 1

    conn.commit()
    total_db = cur.execute("SELECT count(*) FROM food_composition").fetchone()[0]
    conn.close()
    print(f"SUKSES! Total {total_db} bahan pangan resmi laboratorium telah masuk ke database lokal ({DB_PATH}).")

if __name__ == "__main__":
    import_full_tkpi_dataset()
