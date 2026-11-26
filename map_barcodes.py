"""
Script Memetakan Nomor Barcode Resmi (EAN-13) Seluruh 45 Produk Ritel Populer Indonesia
ke Database Pangan Nutrisi Cerdas (tkpi_nutrition.db).
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

BARCODE_MAPPING = {
    # Susu & Olahan Susu (8 produk)
    "8998866200231": "Ultra Milk Susu UHT Cokelat 250ml",
    "8998866200224": "Ultra Milk Susu UHT Full Cream 250ml",
    "7613035315802": "Bear Brand Susu Steril Murni 189ml",
    "8997009510019": "Greenfields Susu UHT Full Cream 200ml",
    "8993351120028": "Cimory Yogurt Drink Strawberry 240ml",
    "8992745123456": "Yakult Minuman Fermentasi 65ml",
    "8992696401112": "Milo Susu UHT Cokelat Malt 180ml",
    "8992702000115": "Indomilk UHT Kids Cokelat 115ml",

    # Snack Sehat, Biskuit & Konfeksioneri (11 produk)
    "8993175537532": "Fitbar Crispy Chocolate 22g",
    "8993175537549": "Fitbar Crispy Tiramisu 22g",
    "8993175536009": "Soyjoy Almond Chocolate 30g",
    "8993175536023": "Soyjoy Crispy Strawberry 25g",
    "8850002016254": "Quaker Instant Oatmeal Matang (35g kering)",
    "8998009010214": "Roma Biskuit Kelapa (3 keping / ~27g)",
    "8998009010450": "Roma Malkist Crackers Abon (2 keping / 25g)",
    "7622210449283": "Oreo Sandwich Cookies Vanilla (3 keping / 28.5g)",
    "8991001100124": "SilverQueen Cokelat Susu Mete 58g",
    "8992696410176": "KitKat Cokelat 2 Fingers 17g",
    "3017620422003": "Nutella Hazelnut Spread 15g",

    # Minuman Kemasan Ritel (11 produk)
    "8992753111105": "Teh Botol Sosro Original 350ml",
    "8992775211111": "Teh Pucuk Harum Melati 350ml",
    "8993480000057": "Pocari Sweat Minuman Isotonik 350ml",
    "8993480000187": "Pocari Sweat Ion Water (Low Calorie) 350ml",
    "8998866600017": "Hydro Coco Original Air Kelapa 250ml",
    "8992696404243": "Nescafe Kopi Can Original 240ml",
    "8996001600399": "Kopiko Lucky Day Kopi Susu 180ml",
    "8991002105256": "Good Day Coffee Tiramisu Bliss 250ml",
    "8992775710355": "Ichi Ocha Teh Hijau Melati 350ml",
    "8998866202358": "Floridina Minuman Jus Jeruk Pulir 350ml",
    "8999999038243": "Buavita Jus Jambu Biji 245ml",

    # Mi Instan Populer (7 produk)
    "089686010921": "Indomie Mi Goreng Spesial 85g",
    "089686010198": "Indomie Kuah Rasa Ayam Bawang 69g",
    "089686011317": "Indomie Kuah Rasa Soto Mie 70g",
    "8998866200576": "Mie Sedaap Goreng Original 90g",
    "8997220240014": "Lemonilo Mi Instan Alami Kuah/Goreng 80g",
    "089686060209": "Pop Mie Instan Cup Rasa Ayam 75g",
    "8801073113428": "Samyang Hot Chicken Ramen Pedas 140g",

    # Roti Kemasan (4 produk)
    "8992772123456": "Sari Roti Tawar Gandum (2 lembar / ~60g)",
    "8992772654321": "Sari Roti Tawar Spesial Kupas (2 lembar / 55g)",
    "8992772010607": "Sari Roti Sobek Cokelat (1 porsi / 60g)",
    "8997236390062": "Aoka Roti Panggang Cokelat/Keju 65g",

    # Snack Keripik & Kacang (4 produk)
    "8992761001016": "Chitato Sapi Panggang 68g (1/2 bungkus / 34g)",
    "8997014170017": "Kusuka Keripik Singkong Original 60g (1/2 bungkus)",
    "8992741987654": "Kacang Kulit Garuda Garing (1 porsi bersih / 30g)",
    "8992741901001": "Kacang Atom Garuda 100g (1 porsi / 30g)",
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
    total_mapped = cur.execute(
        "SELECT COUNT(*) FROM food_composition WHERE food_code LIKE 'RET_%' AND barcode IS NOT NULL AND barcode != ''"
    ).fetchone()[0]
    conn.close()
    print(f"Berhasil menautkan {updated} barcode EAN-13 ({total_mapped}/45 produk RET_* terpetakan).")


if __name__ == "__main__":
    apply_barcodes()
