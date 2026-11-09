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
