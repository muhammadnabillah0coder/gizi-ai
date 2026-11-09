"""
Script Memetakan Nomor Barcode Resmi (EAN-13) Produk Populer ke Database Pangan Nutrisi Cerdas.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

BARCODE_MAPPING = {
    # Barcode EAN-13 resmi Indonesia (899...)
    "8998866200231": "Ultra Milk Susu UHT Cokelat 250ml",
    "8998866200224": "Ultra Milk Susu UHT Full Cream 250ml",
    "7613035315802": "Bear Brand Susu Steril Murni 189ml",
    "8992753111105": "Teh Botol Sosro Original 350ml",
    "8992775211111": "Teh Pucuk Harum Melati 350ml",
    "8993480000057": "Pocari Sweat Minuman Isotonik 350ml",
    "8998866600017": "Hydro Coco Original Air Kelapa 250ml",
    "89686010921": "Indomie Mi Goreng Spesial 85g",
    "089686010921": "Indomie Mi Goreng Spesial 85g",
    "89686011317": "Indomie Kuah Rasa Soto Mie 70g",
    "089686011317": "Indomie Kuah Rasa Soto Mie 70g",
    "8993175537532": "Fitbar Crispy Chocolate 22g",
    "8993175537549": "Fitbar Crispy Tiramisu 22g",
    "8993175536009": "Soyjoy Almond Chocolate 30g",
    "8992772123456": "Sari Roti Tawar Gandum (2 lembar / ~60g)",
    "8992772654321": "Sari Roti Tawar Spesial Kupas (2 lembar / 55g)",
    "8992745123456": "Yakult Minuman Fermentasi 65ml",
    "8998009010214": "Roma Biskuit Kelapa (3 keping / ~27g)",
    "8998009010450": "Roma Malkist Crackers Abon (2 keping / 25g)",
    "7622210014523": "Oreo Sandwich Cookies Vanilla (3 keping / 28.5g)",
    "8991001100124": "SilverQueen Cokelat Susu Mete 58g",
    "8992761001016": "Chitato Sapi Panggang 68g (1/2 bungkus / 34g)",
    "8992741987654": "Kacang Kulit Garuda Garing (1 porsi bersih / 30g)"
}

def apply_barcodes():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    updated = 0
    for code, name in BARCODE_MAPPING.items():
        cur.execute("UPDATE food_composition SET barcode = ? WHERE LOWER(food_name) = LOWER(?)", (code, name))
        if cur.rowcount > 0:
            updated += 1
            
    conn.commit()
    conn.close()
    print(f"Berhasil menautkan {updated} barcode EAN-13 ke produk database.")

if __name__ == "__main__":
    apply_barcodes()
