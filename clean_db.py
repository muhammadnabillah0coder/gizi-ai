"""
Script Pembersihan & Audit Kualitas Database Pangan Nutrisi Cerdas:
1. Memperbaiki kategori salah (Abon haruwan -> Ikan/Kerang/Udang dll).
2. Memperbaiki ejaan (Abon haruwan -> Abon ikan haruan).
3. Menghapus 14 entri duplikat persis menggunakan deduplikasi SQLite (keep min ID).
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

def clean_database():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Perbaiki Abon haruwan (Ikan gabus/haruan khas Banjar)
    cur.execute("""
        UPDATE food_composition 
        SET food_name = 'Abon ikan haruan (gabus)', category = 'Ikan/Kerang/Udang dll'
        WHERE LOWER(food_name) LIKE '%abon haruwan%'
    """)
    print(f"Perbaikan Abon Haruan: {cur.rowcount} baris diperbarui.")

    # 1b. Perbaiki 18 baris anomali Panganku/TKPI (kesalahan scraping desimal/angka hilang/Atwater/serat>karbo)
    tkpi_repairs = [
        ("DR004", {"energy_kcal": 29.0}),
        ("DP042", {"energy_kcal": 91.0}),
        ("GP071", {"energy_kcal": 135.0}),
        ("AP022", {"carb_g": 71.0}),
        ("BP021", {"carb_g": 84.3}),
        ("BP024", {"carb_g": 72.1}),
        ("FP011", {"energy_kcal": 405.0}),
        ("BR033", {"carb_g": 26.3}),
        ("CR008", {"fiber_g": 2.9}),
        ("ER107", {"fiber_g": 4.5}),
        ("GP060", {"protein_g": 54.3, "energy_kcal": 496.0}),
        ("GP022", {"protein_g": 58.3, "carb_g": 17.2, "energy_kcal": 439.0}),
        ("FP035", {"energy_kcal": 246.0}),
        ("AP040", {"energy_kcal": 74.0}),
        ("GR078", {"energy_kcal": 80.0}),
        ("NR018", {"fiber_g": 2.0}),
        ("DR138", {"fiber_g": 2.2}),
        ("DR088", {"carb_g": 5.5, "fiber_g": 5.1}),
    ]
    fixed_rows = 0
    for fcode, fields in tkpi_repairs:
        sets = ", ".join(f"{col} = ?" for col in fields)
        vals = list(fields.values()) + [fcode]
        cur.execute(f"UPDATE food_composition SET {sets} WHERE food_code = ?", vals)
        fixed_rows += cur.rowcount

    # Safeguard umum: pastikan serat tidak melebihi karbohidrat total
    cur.execute("UPDATE food_composition SET fiber_g = carb_g WHERE fiber_g > carb_g")
    clamped_rows = cur.rowcount
    print(f"Perbaikan anomali TKPI/Panganku: {fixed_rows} baris diperbaiki, {clamped_rows} baris serat diselaraskan.")
    
    # 2. Hapus duplikat nama pangan persis (simpan baris dengan id terkecil)
    cur.execute("""
        DELETE FROM food_composition
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM food_composition
            GROUP BY LOWER(TRIM(food_name))
        )
    """)
    print(f"Deduplikasi baris ganda: {cur.rowcount} baris duplikat dihapus.")
    
    # 3. Hitung total entri unik sekarang
    cur.execute("SELECT COUNT(*) FROM food_composition")
    total = cur.fetchone()[0]
    print(f"Total entri bersih sekarang: {total} item.")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    clean_database()
