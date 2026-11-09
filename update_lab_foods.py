"""
Script kurasi ekspansi data pangan modern Indonesia:
Menambahkan masakan populer, jajanan pasar, fast food, aneka kopi/teh,
serta masakan khas warteg & resto nusantara dengan data lab terverifikasi.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

# Data kurasi berbasis TKPI Kemenkes RI, USDA FoodData Central, & NilaiGizi.com
# Format: (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg)
ADDITIONAL_LAB_FOODS = [
    # --- Makanan Pokok & Olahan Nasi ---
    ("CUR_NASI_UDUK", "Nasi uduk", "Makanan Pokok", "1 porsi sedang", 150.0, 100.0, 160.0, 3.2, 5.0, 25.5, 0.6, 120.0),
    ("CUR_NASI_KUNING", "Nasi kuning", "Makanan Pokok", "1 porsi sedang", 150.0, 100.0, 155.0, 3.0, 4.5, 25.0, 0.5, 110.0),
    ("CUR_NASI_PADANG", "Nasi padang putih", "Makanan Pokok", "1 centong penuh", 120.0, 100.0, 135.0, 2.5, 0.3, 29.5, 0.4, 2.0),
    ("CUR_NASI_MERAH", "Nasi merah matang", "Makanan Pokok", "1 centong", 100.0, 100.0, 111.0, 2.6, 0.9, 23.0, 1.8, 1.0),
    ("CUR_LONTONG_POLOS", "Lontong polos", "Makanan Pokok", "1 buah sedang", 100.0, 100.0, 144.0, 2.7, 0.2, 31.8, 0.5, 9.0),
    ("CUR_KETUPAT_POLOS", "Ketupat matang", "Makanan Pokok", "1 buah sedang", 100.0, 100.0, 140.0, 2.6, 0.2, 31.0, 0.5, 8.0),
    ("CUR_BIHUN_GORENG", "Bihun goreng", "Makanan Pokok", "1 piring", 150.0, 100.0, 190.0, 4.0, 7.5, 27.0, 1.1, 350.0),
    ("CUR_KWETIAU_GORENG", "Kwetiau goreng", "Makanan Pokok", "1 piring", 180.0, 100.0, 210.0, 5.5, 9.0, 26.5, 1.0, 420.0),
    ("CUR_MIE_INSTAN_REBUS", "Mie instan kuah matang", "Makanan Pokok", "1 mangkok", 350.0, 100.0, 110.0, 2.6, 4.8, 14.5, 0.8, 480.0),
    ("CUR_MIE_INSTAN_GORENG", "Mie instan goreng matang", "Makanan Pokok", "1 piring", 150.0, 100.0, 250.0, 5.0, 11.5, 32.0, 1.2, 580.0),

    # --- Aneka Lauk Ayam & Bebek ---
    ("CUR_AYAM_GORENG_DADA", "Dada ayam goreng", "Lauk Hewani", "1 potong", 85.0, 75.0, 245.0, 28.5, 13.5, 0.5, 0.0, 260.0),
    ("CUR_AYAM_GORENG_PAHA", "Paha ayam goreng", "Lauk Hewani", "1 potong", 80.0, 70.0, 270.0, 23.0, 19.5, 0.5, 0.0, 290.0),
    ("CUR_AYAM_BAKAR_DADA", "Dada ayam bakar", "Lauk Hewani", "1 potong", 85.0, 75.0, 195.0, 29.0, 7.5, 2.0, 0.0, 280.0),
    ("CUR_AYAM_GULAI", "Gulai ayam", "Lauk Hewani", "1 potong + kuah", 100.0, 70.0, 220.0, 20.0, 14.5, 3.5, 0.4, 340.0),
    ("CUR_AYAM_POPRI", "Ayam pop", "Lauk Hewani", "1 potong", 75.0, 75.0, 185.0, 24.0, 9.5, 1.0, 0.0, 230.0),
    ("CUR_AYAM_PENYET", "Ayam penyet + sambal", "Lauk Hewani", "1 porsi", 90.0, 70.0, 265.0, 24.0, 17.5, 3.0, 0.8, 410.0),
    ("CUR_AYAM_GEPREK", "Ayam geprek krispi sambal bawang", "Lauk Hewani", "1 porsi", 100.0, 80.0, 295.0, 21.0, 19.0, 10.5, 0.6, 450.0),
    ("CUR_AYAM_KECAP", "Ayam masak kecap", "Lauk Hewani", "1 potong", 85.0, 70.0, 210.0, 22.0, 9.0, 9.5, 0.2, 380.0),
    ("CUR_BEBEK_GORENG", "Bebek goreng", "Lauk Hewani", "1 potong", 90.0, 65.0, 310.0, 22.0, 24.5, 0.0, 0.0, 310.0),
    ("CUR_ATI_AMPELA_GORENG", "Ati ampela ayam goreng", "Lauk Hewani", "1 pasang", 60.0, 100.0, 225.0, 26.0, 12.0, 2.5, 0.0, 190.0),

    # --- Aneka Daging Sapi & Kambing ---
    ("CUR_RENDANG_DAGING", "Rendang daging sapi padang", "Lauk Hewani", "1 potong", 50.0, 100.0, 260.0, 21.5, 17.0, 5.5, 1.2, 360.0),
    ("CUR_EMPUD_DAGING", "Empal daging sapi goreng", "Lauk Hewani", "1 potong", 45.0, 100.0, 280.0, 24.0, 18.5, 4.0, 0.0, 320.0),
    ("CUR_DENENG_BALADO", "Dendeng balado kering", "Lauk Hewani", "1 lembar", 40.0, 100.0, 310.0, 32.0, 16.0, 8.5, 0.5, 420.0),
    ("CUR_DAGING_SEMUR", "Semur daging sapi", "Lauk Hewani", "1 potong", 60.0, 100.0, 185.0, 19.0, 8.5, 7.5, 0.3, 310.0),
    ("CUR_SATE_AYAM", "Sate ayam bumbu kacang", "Lauk Hewani", "5 tusuk", 100.0, 100.0, 240.0, 19.0, 15.0, 8.0, 1.2, 350.0),
    ("CUR_SATE_KAMBING", "Sate kambing kecap", "Lauk Hewani", "5 tusuk", 100.0, 100.0, 220.0, 23.0, 13.0, 4.0, 0.2, 290.0),

    # --- Aneka Ikan & Seafood Populer ---
    ("CUR_LELE_GORENG", "Ikan lele goreng", "Ikan/Kerang/Udang dll", "1 ekor sedang", 90.0, 75.0, 245.0, 18.0, 18.5, 1.0, 0.0, 170.0),
    ("CUR_NILA_GORENG", "Ikan nila goreng", "Ikan/Kerang/Udang dll", "1 ekor", 100.0, 70.0, 210.0, 22.0, 12.5, 1.5, 0.0, 180.0),
    ("CUR_NILA_BAKAR", "Ikan nila bakar", "Ikan/Kerang/Udang dll", "1 ekor", 100.0, 70.0, 165.0, 23.5, 6.5, 2.5, 0.0, 220.0),
    ("CUR_GURAME_GORENG", "Ikan gurame goreng", "Ikan/Kerang/Udang dll", "1 potong", 100.0, 65.0, 220.0, 21.0, 14.0, 1.5, 0.0, 160.0),
    ("CUR_TONGKOL_BALADO", "Ikan tongkol balado", "Ikan/Kerang/Udang dll", "1 potong", 70.0, 90.0, 175.0, 23.0, 7.5, 3.5, 0.5, 280.0),
    ("CUR_KEMBUNG_GORENG", "Ikan kembung goreng", "Ikan/Kerang/Udang dll", "1 ekor", 80.0, 75.0, 215.0, 22.5, 13.0, 0.5, 0.0, 190.0),
    ("CUR_BANDENG_PRESTO", "Ikan bandeng presto goreng", "Ikan/Kerang/Udang dll", "1 potong", 75.0, 100.0, 240.0, 20.5, 16.0, 2.5, 0.0, 310.0),
    ("CUR_UDANG_GORENG_TEPUNG", "Udang goreng tepung crispy", "Ikan/Kerang/Udang dll", "5 ekor", 80.0, 100.0, 275.0, 16.5, 17.0, 14.0, 0.4, 380.0),
    ("CUR_CUMI_GORENG_TEPUNG", "Cumi goreng tepung", "Ikan/Kerang/Udang dll", "1 porsi", 90.0, 100.0, 260.0, 15.0, 15.5, 15.0, 0.3, 410.0),
    ("CUR_CUMI_SAUS_TIRAM", "Cumi saus tiram", "Ikan/Kerang/Udang dll", "1 porsi", 100.0, 100.0, 145.0, 16.0, 5.0, 9.0, 0.4, 490.0),

    # --- Olahan Telur, Tempe, & Tahu ---
    ("CUR_TELUR_BALADO", "Telur balado", "Telur", "1 butir", 65.0, 89.0, 170.0, 12.0, 12.0, 4.0, 0.3, 260.0),
    ("CUR_TELUR_DADAR_PADANG", "Telur dadar tebal padang", "Telur", "1 potong", 70.0, 100.0, 230.0, 13.0, 18.0, 4.5, 0.5, 320.0),
    ("CUR_TELUR_MATA_SAPI", "Telur ceplok mata sapi", "Telur", "1 butir", 55.0, 100.0, 195.0, 13.5, 14.5, 1.2, 0.0, 180.0),
    ("CUR_TELUR_ASIN", "Telur bebek asin matang", "Telur", "1 butir", 60.0, 85.0, 185.0, 13.5, 13.8, 1.5, 0.0, 540.0),
    ("CUR_TEMPE_OREK_BASAH", "Orek tempe manis basah", "Lauk Nabati", "3 sendok makan", 50.0, 100.0, 185.0, 12.0, 7.5, 18.0, 2.5, 220.0),
    ("CUR_TEMPE_OREK_KERING", "Orek tempe kering teri kacang", "Lauk Nabati", "2 sendok makan", 35.0, 100.0, 310.0, 18.0, 18.5, 20.0, 3.2, 340.0),
    ("CUR_TEMPE_MENDOAN", "Tempe mendoan goreng", "Lauk Nabati", "1 lembar lebar", 60.0, 100.0, 220.0, 10.5, 14.5, 12.0, 1.8, 240.0),
    ("CUR_TEMPE_BACEM", "Tempe bacem manis", "Lauk Nabati", "1 potong", 45.0, 100.0, 160.0, 11.0, 5.0, 18.5, 2.2, 180.0),
    ("CUR_TAHU_BACEM", "Tahu bacem manis", "Lauk Nabati", "1 potong", 50.0, 100.0, 135.0, 9.0, 4.5, 15.0, 1.1, 170.0),
    ("CUR_TAHU_ISI_GORENG", "Tahu isi sayur goreng tepung", "Lauk Nabati", "1 buah", 60.0, 100.0, 195.0, 7.0, 12.0, 15.0, 1.5, 260.0),

    # --- Gorengan & Jajanan Pasar ---
    ("CUR_BAKWAN_SAYUR", "Bakwan sayur / bala-bala", "Lauk Nabati", "1 buah", 50.0, 100.0, 260.0, 5.0, 16.0, 24.0, 1.5, 290.0),
    ("CUR_CIRENG", "Cireng goreng bumbu rujak", "Konfeksioneri", "3 buah", 60.0, 100.0, 290.0, 1.5, 12.0, 44.0, 0.5, 310.0),
    ("CUR_PISANG_GORENG", "Pisang goreng tepung", "Konfeksioneri", "1 buah", 65.0, 100.0, 235.0, 2.0, 9.5, 36.0, 2.0, 120.0),
    ("CUR_RISOL_MAYO", "Risol mayo telur asap", "Konfeksioneri", "1 buah", 60.0, 100.0, 270.0, 6.5, 16.5, 24.0, 0.8, 320.0),
    ("CUR_MARTABAK_TELUR", "Martabak telur bebek sapi", "Lauk Hewani", "2 potong", 100.0, 100.0, 290.0, 12.0, 21.0, 14.0, 0.9, 440.0),
    ("CUR_MARTABAK_MANIS", "Martabak manis coklat keju", "Konfeksioneri", "1 potong tebal", 70.0, 100.0, 360.0, 6.5, 18.0, 44.0, 1.2, 280.0),
    ("CUR_PEMPEK_KAPAL_SELAM", "Pempek kapal selam telur + cuko", "Menu Komposit", "1 buah", 150.0, 100.0, 185.0, 9.5, 6.5, 22.0, 0.8, 480.0),
    ("CUR_SIOMAY_IKAN", "Siomay ikan bumbu kacang", "Menu Komposit", "3 biji + bumbu", 120.0, 100.0, 175.0, 9.0, 8.5, 16.0, 1.2, 380.0),
    ("CUR_BATAGOR", "Batagor bumbu kacang", "Menu Komposit", "1 porsi", 150.0, 100.0, 240.0, 8.5, 14.5, 20.0, 1.4, 410.0),
    ("CUR_SEBLAK_KOMPLIT", "Seblak basah komplit pedas", "Menu Komposit", "1 mangkok", 250.0, 100.0, 145.0, 4.5, 6.0, 18.5, 1.0, 520.0),

    # --- Sayuran Masak & Sup Nusantara ---
    ("CUR_SAYUR_ASEM", "Sayur asem jakarta / sunda", "Sayuran", "1 mangkok", 200.0, 100.0, 35.0, 1.5, 0.6, 6.5, 1.8, 190.0),
    ("CUR_SAYUR_LODEH", "Sayur lodeh santan", "Sayuran", "1 mangkok", 200.0, 100.0, 75.0, 2.0, 5.2, 5.5, 1.6, 280.0),
    ("CUR_SAYUR_BENING_BAYAM", "Sayur bening bayam jagung", "Sayuran", "1 mangkok", 150.0, 100.0, 28.0, 1.8, 0.3, 5.0, 1.4, 160.0),
    ("CUR_TUMIS_KANGKUNG_TERASI", "Tumis kangkung terasi", "Sayuran", "1 porsi", 100.0, 100.0, 68.0, 2.8, 4.5, 4.2, 2.2, 240.0),
    ("CUR_TUMIS_TAUGE_TAHU", "Tumis tauge tahu", "Sayuran", "1 porsi", 100.0, 100.0, 62.0, 4.5, 3.2, 4.0, 1.6, 210.0),
    ("CUR_CAPCAY_GORENG", "Capcay goreng kuah kental", "Sayuran", "1 piring", 180.0, 100.0, 78.0, 3.8, 3.5, 8.0, 2.2, 360.0),
    ("CUR_SOP_BUNTUT", "Sop buntut sapi", "Menu Komposit", "1 mangkok kuah + daging", 300.0, 100.0, 115.0, 9.5, 7.5, 2.5, 0.4, 380.0),
    ("CUR_RAWON_SAPI", "Rawon daging sapi kuah kluwek", "Menu Komposit", "1 mangkok", 250.0, 100.0, 110.0, 8.5, 7.0, 3.5, 0.6, 420.0),
    ("CUR_SOTO_BETAWI", "Soto betawi santan susu", "Menu Komposit", "1 mangkok", 300.0, 100.0, 140.0, 8.0, 10.5, 4.0, 0.3, 440.0),

    # --- Minuman Modern & Warung ---
    ("CUR_AIR_MINERAL_0", "Air putih / Air mineral", "Minuman", "1 gelas (250ml)", 250.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0),
    ("CUR_KOPI_HITAM_POLOS", "Kopi hitam tanpa gula", "Minuman", "1 cangkir (150ml)", 150.0, 100.0, 2.0, 0.1, 0.0, 0.3, 0.0, 3.0),
    ("CUR_AMERICANO", "Americano / Espresso", "Minuman", "1 cup (200ml)", 200.0, 100.0, 3.0, 0.2, 0.0, 0.4, 0.0, 4.0),
    ("CUR_KOPI_SUSU_GULA_AREN", "Kopi susu gula aren kekinian", "Minuman", "1 cup (300ml)", 300.0, 100.0, 65.0, 1.5, 2.2, 10.0, 0.1, 35.0),
    ("CUR_ES_TEH_MANIS", "Es teh manis warung", "Minuman", "1 gelas (250ml)", 250.0, 100.0, 40.0, 0.0, 0.0, 10.0, 0.0, 5.0),
    ("CUR_ES_TEH_TAWAR", "Es teh tawar", "Minuman", "1 gelas (250ml)", 250.0, 100.0, 1.0, 0.0, 0.0, 0.2, 0.0, 3.0),
    ("CUR_TEH_TARIK", "Teh tarik susu", "Minuman", "1 gelas (250ml)", 250.0, 100.0, 68.0, 1.6, 2.4, 10.2, 0.0, 45.0),
    ("CUR_JUS_ALPUKAT", "Jus alpukat manis kental manis", "Minuman", "1 gelas (300ml)", 300.0, 100.0, 85.0, 1.2, 5.5, 8.5, 2.2, 20.0),
    ("CUR_JUS_MANGGA", "Jus mangga segar", "Minuman", "1 gelas (300ml)", 300.0, 100.0, 52.0, 0.5, 0.2, 12.5, 0.8, 5.0),
    ("CUR_SUSU_UHT_FULL_CREAM", "Susu UHT full cream cair", "Susu", "1 kotak (250ml)", 250.0, 100.0, 60.0, 3.2, 3.4, 4.8, 0.0, 45.0),
    ("CUR_SUSU_UHT_COKELAT", "Susu UHT cokelat cair", "Susu", "1 kotak (250ml)", 250.0, 100.0, 72.0, 3.0, 2.8, 9.2, 0.4, 55.0),
    ("CUR_SUSU_KEDELAI", "Susu kedelai / sari kedelai manis", "Minuman", "1 gelas (250ml)", 250.0, 100.0, 54.0, 3.0, 1.8, 6.5, 0.5, 25.0)
]

def update_nutrition_database():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.executemany("""
        INSERT OR REPLACE INTO food_composition 
        (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ADDITIONAL_LAB_FOODS)
    
    conn.commit()
    total = cur.execute("SELECT count(*) FROM food_composition").fetchone()[0]
    conn.close()
    print(f"Update sukses! Total pangkalan data gizi sekarang: {total} item makanan.")

if __name__ == "__main__":
    update_nutrition_database()
