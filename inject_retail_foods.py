"""
Script Penambahan Produk Kemasan Ritel Populer Indonesia ke tkpi_nutrition.db
(Indomaret, Alfamart, Warung: Susu UHT, Biskuit/Snack, Minuman Isotonik/Teh/Kopi, Mi Instan, Suplemen)
Data nutrisi per 100g atau per sajian standar berdasarkan label Informasi Nilai Gizi resmi BPOM.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

RETAIL_PRODUCTS = [
    # Susu & Olahan Susu
    ("RET_ULTRA_250", "Ultra Milk Susu UHT Cokelat 250ml", "Produk Kemasan / Minuman Ritel", "1 kotak (250ml)", 250.0, 100.0, 160.0, 6.0, 4.0, 24.0, 2.0, 105.0),
    ("RET_ULTRA_FULL", "Ultra Milk Susu UHT Full Cream 250ml", "Produk Kemasan / Minuman Ritel", "1 kotak (250ml)", 250.0, 100.0, 150.0, 8.0, 8.0, 12.0, 0.0, 110.0),
    ("RET_BEAR_BRAND", "Bear Brand Susu Steril Murni 189ml", "Produk Kemasan / Minuman Ritel", "1 kaleng (189ml)", 189.0, 100.0, 120.0, 6.0, 7.0, 9.0, 0.0, 95.0),
    ("RET_GREENFIELDS", "Greenfields Susu UHT Full Cream 200ml", "Produk Kemasan / Minuman Ritel", "1 kotak (200ml)", 200.0, 100.0, 130.0, 6.5, 7.0, 10.0, 0.0, 90.0),
    ("RET_CIMORY_YOG", "Cimory Yogurt Drink Strawberry 240ml", "Produk Kemasan / Minuman Ritel", "1 botol (240ml)", 240.0, 100.0, 170.0, 4.0, 3.5, 31.0, 1.0, 115.0),
    ("RET_YAKULT", "Yakult Minuman Fermentasi 65ml", "Produk Kemasan / Minuman Ritel", "1 botol (65ml)", 65.0, 100.0, 50.0, 0.8, 0.1, 11.5, 0.0, 15.0),
    ("RET_MILO_UHT", "Milo Susu UHT Cokelat Malt 180ml", "Produk Kemasan / Minuman Ritel", "1 kotak (180ml)", 180.0, 100.0, 120.0, 3.5, 3.0, 20.0, 1.5, 80.0),
    ("RET_INDOMILK_CKL", "Indomilk UHT Kids Cokelat 115ml", "Produk Kemasan / Minuman Ritel", "1 kotak (115ml)", 115.0, 100.0, 80.0, 2.5, 2.0, 13.0, 0.5, 60.0),

    # Snack Sehat, Biskuit & Granola Bar
    ("RET_FITBAR_CHOC", "Fitbar Crispy Chocolate 22g", "Produk Kemasan / Biskuit & Snack", "1 bar (22g)", 22.0, 100.0, 90.0, 2.0, 2.5, 16.0, 2.0, 50.0),
    ("RET_FITBAR_TIRAM", "Fitbar Crispy Tiramisu 22g", "Produk Kemasan / Biskuit & Snack", "1 bar (22g)", 22.0, 100.0, 90.0, 2.0, 2.5, 16.0, 2.0, 50.0),
    ("RET_SOYJOY_ALM", "Soyjoy Almond Chocolate 30g", "Produk Kemasan / Biskuit & Snack", "1 bar (30g)", 30.0, 100.0, 140.0, 5.0, 9.0, 11.0, 3.0, 65.0),
    ("RET_SOYJOY_BERRY", "Soyjoy Crispy Strawberry 25g", "Produk Kemasan / Biskuit & Snack", "1 bar (25g)", 25.0, 100.0, 120.0, 4.0, 6.0, 13.0, 2.0, 55.0),
    ("RET_QUAKER_OAT", "Quaker Instant Oatmeal Matang (35g kering)", "Produk Kemasan / Sereal", "1 mangkok (35g)", 35.0, 100.0, 130.0, 4.0, 2.5, 24.0, 3.5, 5.0),
    ("RET_ROMA_KELAPA", "Roma Biskuit Kelapa (3 keping / ~27g)", "Produk Kemasan / Biskuit & Snack", "3 keping (27g)", 27.0, 100.0, 130.0, 2.0, 5.0, 19.0, 1.0, 75.0),
    ("RET_ROMA_MALKIST", "Roma Malkist Crackers Abon (2 keping / 25g)", "Produk Kemasan / Biskuit & Snack", "2 keping (25g)", 25.0, 100.0, 120.0, 2.0, 4.5, 17.0, 0.5, 120.0),
    ("RET_OREO_REG", "Oreo Sandwich Cookies Vanilla (3 keping / 28.5g)", "Produk Kemasan / Biskuit & Snack", "3 keping (28.5g)", 28.5, 100.0, 140.0, 1.0, 6.0, 20.0, 1.0, 115.0),
    ("RET_SILVERQUEEN", "SilverQueen Cokelat Susu Mete 58g", "Produk Kemasan / Konfeksioneri", "1 batang (58g)", 58.0, 100.0, 310.0, 6.0, 19.0, 31.0, 2.0, 55.0),
    ("RET_KITKAT_2F", "KitKat Cokelat 2 Fingers 17g", "Produk Kemasan / Konfeksioneri", "1 bungkus (17g)", 17.0, 100.0, 90.0, 1.0, 5.0, 11.0, 0.5, 15.0),

    # Minuman Kemasan Ritel (Teh, Kopi, Isotonik)
    ("RET_TEH_BOTOL", "Teh Botol Sosro Original 350ml", "Produk Kemasan / Minuman Ritel", "1 botol (350ml)", 350.0, 100.0, 130.0, 0.0, 0.0, 33.0, 0.0, 20.0),
    ("RET_TEH_PUCUK", "Teh Pucuk Harum Melati 350ml", "Produk Kemasan / Minuman Ritel", "1 botol (350ml)", 350.0, 100.0, 140.0, 0.0, 0.0, 35.0, 0.0, 25.0),
    ("RET_POCARI_350", "Pocari Sweat Minuman Isotonik 350ml", "Produk Kemasan / Minuman Ritel", "1 botol (350ml)", 350.0, 100.0, 90.0, 0.0, 0.0, 21.0, 0.0, 140.0),
    ("RET_POCARI_ION", "Pocari Sweat Ion Water (Low Calorie) 350ml", "Produk Kemasan / Minuman Ritel", "1 botol (350ml)", 350.0, 100.0, 35.0, 0.0, 0.0, 8.0, 0.0, 140.0),
    ("RET_HYDRO_COCO", "Hydro Coco Original Air Kelapa 250ml", "Produk Kemasan / Minuman Ritel", "1 kotak (250ml)", 250.0, 100.0, 60.0, 0.5, 0.0, 14.0, 1.0, 95.0),
    ("RET_NESCAFE_CAN", "Nescafe Kopi Can Original 240ml", "Produk Kemasan / Minuman Ritel", "1 kaleng (240ml)", 240.0, 100.0, 140.0, 3.0, 3.5, 24.0, 1.0, 100.0),
    ("RET_KOPASKO_AREN", "Kopiko Lucky Day Kopi Susu 180ml", "Produk Kemasan / Minuman Ritel", "1 botol (180ml)", 180.0, 100.0, 130.0, 2.5, 3.0, 23.0, 0.5, 85.0),
    ("RET_GOOD_DAY_BOT", "Good Day Coffee Tiramisu Bliss 250ml", "Produk Kemasan / Minuman Ritel", "1 botol (250ml)", 250.0, 100.0, 150.0, 2.5, 3.0, 28.0, 1.0, 95.0),
    ("RET_ICHI_OCHA", "Ichi Ocha Teh Hijau Melati 350ml", "Produk Kemasan / Minuman Ritel", "1 botol (350ml)", 350.0, 100.0, 120.0, 0.0, 0.0, 30.0, 0.0, 20.0),
    ("RET_FLORIDINA", "Floridina Minuman Jus Jeruk Pulir 350ml", "Produk Kemasan / Minuman Ritel", "1 botol (350ml)", 350.0, 100.0, 140.0, 0.0, 0.0, 34.0, 1.0, 30.0),
    ("RET_BUAVITA_JAMBU", "Buavita Jus Jambu Biji 245ml", "Produk Kemasan / Minuman Ritel", "1 kotak (245ml)", 245.0, 100.0, 130.0, 0.5, 0.0, 31.0, 2.0, 25.0),

    # Mi Instan Populer (Per Bungkus Standar Sajian Matang)
    ("RET_INDOMIE_GOR", "Indomie Mi Goreng Spesial 85g", "Produk Kemasan / Mi & Pasta", "1 bungkus (85g)", 85.0, 100.0, 390.0, 8.0, 17.0, 51.0, 3.0, 860.0),
    ("RET_INDOMIE_AYAM", "Indomie Kuah Rasa Ayam Bawang 69g", "Produk Kemasan / Mi & Pasta", "1 bungkus (69g)", 69.0, 100.0, 310.0, 7.0, 12.0, 44.0, 2.0, 1150.0),
    ("RET_INDOMIE_SOTO", "Indomie Kuah Rasa Soto Mie 70g", "Produk Kemasan / Mi & Pasta", "1 bungkus (70g)", 70.0, 100.0, 320.0, 7.0, 13.0, 44.0, 2.0, 1220.0),
    ("RET_MIE_SEDAAP_G", "Mie Sedaap Goreng Original 90g", "Produk Kemasan / Mi & Pasta", "1 bungkus (90g)", 90.0, 100.0, 420.0, 8.0, 19.0, 54.0, 3.0, 910.0),
    ("RET_LEMONILO_GOR", "Lemonilo Mi Instan Alami Kuah/Goreng 80g", "Produk Kemasan / Mi & Pasta", "1 bungkus (80g)", 80.0, 100.0, 280.0, 7.0, 6.0, 50.0, 4.0, 580.0),
    ("RET_POP_MIE_AYAM", "Pop Mie Instan Cup Rasa Ayam 75g", "Produk Kemasan / Mi & Pasta", "1 cup (75g)", 75.0, 100.0, 330.0, 6.0, 13.0, 47.0, 2.0, 1190.0),
    ("RET_SAMYANG_HOT", "Samyang Hot Chicken Ramen Pedas 140g", "Produk Kemasan / Mi & Pasta", "1 bungkus (140g)", 140.0, 100.0, 530.0, 12.0, 19.0, 78.0, 4.0, 1380.0),

    # Roti & Roti Gandum Kemasan
    ("RET_SARI_ROTI_TW", "Sari Roti Tawar Gandum (2 lembar / ~60g)", "Produk Kemasan / Roti & Roti Gandum", "2 lembar (60g)", 60.0, 100.0, 160.0, 6.0, 2.5, 28.0, 3.5, 210.0),
    ("RET_SARI_ROTI_PUT", "Sari Roti Tawar Spesial Kupas (2 lembar / 55g)", "Produk Kemasan / Roti & Roti Gandum", "2 lembar (55g)", 55.0, 100.0, 150.0, 5.0, 2.0, 28.0, 1.0, 230.0),
    ("RET_SARI_ROTI_COK", "Sari Roti Sobek Cokelat (1 porsi / 60g)", "Produk Kemasan / Roti & Roti Gandum", "1 porsi (60g)", 60.0, 100.0, 210.0, 5.0, 6.0, 34.0, 1.5, 160.0),
    ("RET_AOKA_ROTI", "Aoka Roti Panggang Cokelat/Keju 65g", "Produk Kemasan / Roti & Roti Gandum", "1 bungkus (65g)", 65.0, 100.0, 240.0, 4.5, 9.0, 35.0, 1.0, 180.0),

    # Snack Keripik & Kacang
    ("RET_LAYS_CHIPS", "Chitato Sapi Panggang 68g (1/2 bungkus / 34g)", "Produk Kemasan / Biskuit & Snack", "1 porsi (34g)", 34.0, 100.0, 180.0, 2.0, 10.0, 20.0, 1.0, 160.0),
    ("RET_KUSUKA_ORIG", "Kusuka Keripik Singkong Original 60g (1/2 bungkus)", "Produk Kemasan / Biskuit & Snack", "1 porsi (30g)", 30.0, 100.0, 150.0, 1.0, 7.0, 21.0, 1.5, 120.0),
    ("RET_GARUDA_KAC", "Kacang Kulit Garuda Garing (1 porsi bersih / 30g)", "Produk Kemasan / Biskuit & Snack", "1 porsi (30g)", 30.0, 100.0, 170.0, 8.0, 14.0, 5.0, 3.0, 95.0),
    ("RET_GARUDA_ROAS", "Kacang Atom Garuda 100g (1 porsi / 30g)", "Produk Kemasan / Biskuit & Snack", "1 porsi (30g)", 30.0, 100.0, 150.0, 4.0, 7.0, 18.0, 1.0, 140.0)
]

def inject_retail_products():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    count_new = 0
    for prod in RETAIL_PRODUCTS:
        code, name, cat, unit, def_w, bdd, kcal, p, f, c, fib, sod = prod
        # Periksa apakah sudah ada
        cur.execute("SELECT id FROM food_composition WHERE LOWER(food_name) = LOWER(?)", (name,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO food_composition 
                (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, prod)
            count_new += 1
            
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM food_composition")
    total = cur.fetchone()[0]
    conn.close()
    
    print(f"Berhasil menambahkan {count_new} produk kemasan baru.")
    print(f"Total database pangan sekarang: {total} entri.")

if __name__ == "__main__":
    inject_retail_products()
