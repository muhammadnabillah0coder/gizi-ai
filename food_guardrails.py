"""
Anti-Prank & Food Integrity Guardrails (Nutrisi Cerdas)
Pertahanan deterministik 4 lapis (0 token AI, <0.2ms) untuk mencegah input iseng,
benda non-makanan, satwa ekstrem/dilindungi, kuantitas grosir mustahil,
angka fisika gizi palsu, dan injeksi prompt/HTML mencemari aplikasi maupun database.
"""

import html
import os
import re

_MODULE_MTIME = round(os.path.getmtime(__file__), 6) if os.path.exists(__file__) else 0.0

MAX_SINGLE_DISH_GRAMS = 2500.0
MAX_SINGLE_DISH_KCAL = 3500.0
MAX_COUNTABLE_SMALL_UNIT = 30.0
MAX_COUNTABLE_LARGE_UNIT = 5.0
MAX_DENSITY_KCAL_PER_100G = 920.0
MAX_DAILY_MEALS_PER_USER = 25
MAX_DAILY_KCAL_PER_USER = 12000.0
MAX_FREE_UNCLEAR_IMAGE_RETRIES_PER_DAY = 2

# Frasa kuliner Indonesia sah yang memakai nama hewan/benda agar tidak pernah salah diblokir
CULINARY_IDIOM_ALLOWLIST = (
    "kacang mete/biji jambu monyet",
    "biji jambu monyet",
    "jambu monyet",
    "ceplok mata sapi",
    "telur mata sapi",
    "mata sapi",
    "kue lidah kucing",
    "lidah kucing",
    "es lidah buaya",
    "lidah buaya",
    "kue kuping gajah",
    "kuping gajah",
    "kue sarang semut",
    "sarang semut",
    "teh kumis kucing",
    "kumis kucing",
    "pepare ular",
    "pare ular",
    "kayu manis",
    "ubi kayu",
    "kacang tanah",
    "gula pasir",
    "gula batu",
    "garam batu",
    "es batu",
    "es lilin",
    "es gabus",
    "nasi kucing",
    "roti buaya",
    "kue buaya",
    "hot dog",
    "hotdog",
    "corn dog",
    "corndog",
    "kaki naga",
    "cakar ayam",
    "rambut nenek",
    "bakso beranak",
)

NON_FOOD_TOKENS = (
    "sandal jepit", "sandal", "sendal", "sepatu", "kaos kaki", "celana dalam",
    "batu bata", "batu kali", "kerikil", "batu", "semen", "aspal",
    "pasir bangunan", "tanah liat", "lumpur", "sampah", "plastik", "kresek",
    "styrofoam", "stereofoam", "kertas", "kardus", "tisu", "tissue",
    "paku", "baut", "kawat", "besi tua", "pecahan kaca", "beling",
    "kayu bakar", "serbuk kayu", "papan kayu", "oli bekas", "oli mesin", "oli",
    "bensin", "pertalite", "pertamax", "solar", "thinner", "spirtus",
    "sabun", "shampo", "sampo", "deterjen", "pewangi pakaian", "wipol",
    "rokok", "puntung rokok", "puntung", "asbak", "vape",
    "handphone", "smartphone", "laptop", "keyboard", "charger", "baterai",
    "uang kertas", "koin logam",
)

POISON_AND_FILTH_TOKENS = (
    "tinja", "feses", "kotoran manusia", "kotoran hewan", "kotoran",
    "berak", "tai", "pipis", "urine", "air kencing", "dahak", "ingus",
    "bangkai", "formalin", "boraks", "sianida", "arsenik", "merkuri",
    "pestisida", "insektisida", "baygon", "obat nyamuk", "racun tikus", "racun",
)

EXTREME_TABOO_TOKENS = (
    "katak", "kodok", "swike", "swikee",
    "tikus", "anjing", "rw, anjing", "daging rw", "saksang",
    "kucing", "ular", "kobra", "piton", "biawak", "buaya", "paniki",
    "kelelawar", "penyu", "monyet", "kera", "tupai", "musang",
    "kecoa", "lalat", "belatung", "cacing", "lintah", "cicak", "tokek",
    "ulat sagu", "ulat", "bekicot", "keong",
)

JOKE_OR_GIBBERISH_PATTERNS = (
    re.compile(r"(?:(?:wk){2,}|(?:kw){2,}|(?:ha){3,}|(?:he){3,}|(?:xi){2,}|asdf|qwer|zxcv)", re.IGNORECASE),
    re.compile(r"^(test+|tes+|coba+|abc+|aaa+|xxx+)\d*$", re.IGNORECASE),
)

PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\b(abaikan|lupakan|hiraukan)\s+(semua\s+)?(aturan|instruksi|perintah|larangan)\b", re.IGNORECASE),
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|system)\s+(instructions|rules|prompts)\b", re.IGNORECASE),
    re.compile(r"\b(system\s+prompt|jailbreak|developer\s+mode|override\s+rules)\b", re.IGNORECASE),
    re.compile(r"\b(anggap\s+(saja\s+)?ini|pura[- ]?pura\s+ini|paksa\s+output)\b", re.IGNORECASE),
)

WHOLESALE_UNITS = (
    "ton", "kwintal", "kuintal", "karung", "zak", "sak", "truk",
    "kontainer", "container", "gerobak", "dandang", "ember", "jerigen",
    "kardus", "krat", "peti", "kodi", "lusin", "sejuta", "seribu",
    "ribuan", "jutaan", "miliaran",
)

COUNTABLE_SMALL_UNITS = (
    "tusuk", "butir", "biji", "buah", "potong", "iris", "lembar",
    "sendok", "sdm", "sdt", "bungkus", "sachet", "ekor",
)

COUNTABLE_LARGE_UNITS = (
    "piring", "mangkok", "mangkuk", "porsi", "kotak", "box", "cup",
    "gelas", "botol", "kaleng", "loyang", "tampah", "baskom", "panci",
)

_IDIOM_REGEX = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in sorted(CULINARY_IDIOM_ALLOWLIST, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


class FoodGuardrailRejected(ValueError):
    """Exception terstruktur ketika input ditolak oleh lapisan guardrail pangan."""

    def __init__(self, rejection_type: str, message: str):
        super().__init__(message)
        self.rejection_type = rejection_type or "non_food"
        self.message = message

    @property
    def consumes_scan_quota(self) -> bool:
        # Foto gelap/buram tidak sengaja diberi toleransi terpisah; prank/non-food tetap memotong kuota anti-spam
        return self.rejection_type != "unclear_image"


def sanitize_html_text(value, default: str = "") -> str:
    """Meng-escape tag HTML dari input user/AI sebelum dirender ke blok markdown unsafe_allow_html."""
    raw = default if value is None else str(value)
    return html.escape(raw, quote=True)


def _mask_culinary_idioms(text: str) -> str:
    return _IDIOM_REGEX.sub(" pangan_aman ", text or "")


def _build_token_regex(tokens: tuple[str, ...]) -> re.Pattern:
    ordered = sorted(tokens, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(t) for t in ordered) + r")\b", re.IGNORECASE)


_RE_NON_FOOD = _build_token_regex(NON_FOOD_TOKENS)
_RE_POISON_FILTH = _build_token_regex(POISON_AND_FILTH_TOKENS)
_RE_EXTREME_TABOO = _build_token_regex(EXTREME_TABOO_TOKENS)
_RE_WHOLESALE = _build_token_regex(WHOLESALE_UNITS)
_RE_WATER_ALLOWED = re.compile(r"\bair\s*(mineral|putih|minum|tawar)\b", re.IGNORECASE)


def _parse_numeric_token(raw_num: str) -> float:
    clean = (raw_num or "").strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", clean):
        return float(clean.replace(".", ""))
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", clean):
        return float(clean.replace(",", ""))
    return float(clean.replace(",", "."))


def check_prompt_injection(text: str):
    cleaned = " ".join((text or "").split())
    for pat in PROMPT_INJECTION_PATTERNS:
        if pat.search(cleaned):
            raise FoodGuardrailRejected(
                "prompt_injection",
                "Permintaan ditolak karena mengandung pola instruksi tidak wajar. Tuliskan nama makanan yang sebenarnya.",
            )


def _check_text_gibberish(text: str):
    clean = " ".join((text or "").strip().split())
    alpha_chars = re.findall(r"[a-zA-Z]", clean)
    if len(alpha_chars) < 3:
        raise FoodGuardrailRejected(
            "non_food",
            "Nama makanan terlalu singkat atau tidak dikenali. Ketikkan nama hidangan yang jelas (contoh: '1 porsi soto ayam').",
        )
    for pat in JOKE_OR_GIBBERISH_PATTERNS:
        if pat.search(clean):
            raise FoodGuardrailRejected(
                "non_food",
                "Teks terdeteksi sebagai ketikan acak/candaan. Masukkan nama hidangan yang valid untuk dihitung gizinya.",
            )


def _check_taboo_and_non_food(text: str):
    masked = _mask_culinary_idioms(text)
    if _RE_POISON_FILTH.search(masked):
        raise FoodGuardrailRejected(
            "unsafe_or_taboo",
            "Objek/bahan berbahaya atau tidak layak konsumsi terdeteksi. Aplikasi hanya menganalisis makanan & minuman manusia yang aman.",
        )
    if _RE_EXTREME_TABOO.search(masked):
        raise FoodGuardrailRejected(
            "unsafe_or_taboo",
            "Bahan/hewan ekstrem tersebut tidak didukung dalam pangkalan data gizi standar Nutrisi Cerdas dan otomatis ditolak.",
        )
    hit_non = _RE_NON_FOOD.search(masked)
    if hit_non:
        raise FoodGuardrailRejected(
            "non_food",
            f"Objek '{hit_non.group(1)}' bukan makanan/minuman yang dapat dikonsumsi dan tidak diproses.",
        )


def _check_quantity_plausibility(text: str, allow_trailing_model_code: bool = False):
    clean = " ".join((text or "").strip().split())
    if not clean:
        return

    if re.search(r"\b(puluhan\s+ribu|ratusan|ribu|juta|miliar|milyar|triliun)\b", clean, re.IGNORECASE):
        raise FoodGuardrailRejected(
            "implausible_portion",
            "Jumlah porsi skala ribuan/jutaan tidak realistis untuk 1 kali makan dan otomatis ditolak.",
        )

    ws_hit = _RE_WHOLESALE.search(clean)
    if ws_hit and not _RE_WATER_ALLOWED.search(clean):
        raise FoodGuardrailRejected(
            "implausible_portion",
            f"Satuan grosir '{ws_hit.group(1)}' melebihi takaran makan perorangan yang wajar (maks. 2.500g / 1 porsi wajar).",
        )

    # Pola angka berdiri utuh (tidak menempel huruf alfanumerik acak seperti kode '7850a1')
    num_pat = re.compile(
        r"(?<![a-zA-Z0-9])(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)(?:\s*(%|[a-zA-Z]+))?(?![a-zA-Z0-9])",
        re.IGNORECASE,
    )
    for match in num_pat.finditer(clean):
        val = _parse_numeric_token(match.group(1))
        unit = (match.group(2) or "").lower()

        if unit == "%":
            if val > 100.0:
                raise FoodGuardrailRejected("implausible_portion", f"Persentase {val:g}% tidak valid untuk komposisi makanan.")
            continue

        if unit in {"mg", "mcg", "ug", "iu"}:
            if val > 10000.0:
                raise FoodGuardrailRejected("implausible_portion", f"Kandungan {val:,.0f} {unit} tidak realistis untuk 1 sajian makanan.")
            continue

        if unit == "x":
            if val > 5.0:
                raise FoodGuardrailRejected("implausible_portion", f"Pengali porsi {val:g}x melebihi batas wajar 1 kali makan.")
            continue

        if unit in {"kkal", "kcal", "kal", "kalori"}:
            if val > MAX_SINGLE_DISH_KCAL:
                raise FoodGuardrailRejected(
                    "implausible_portion",
                    f"Angka kalori {val:,.0f} kkal untuk satu hidangan melebihi batas realistis ({MAX_SINGLE_DISH_KCAL:,.0f} kkal).",
                )
            continue

        if unit in {"kg", "kilogram", "kilo", "l", "liter"}:
            if val > 2.5 and not _RE_WATER_ALLOWED.search(clean):
                raise FoodGuardrailRejected(
                    "implausible_portion",
                    f"Takaran {val:g} {unit} melebihi batas wajar 1 kali makan perorangan (maks. 2,5 kg/liter).",
                )
            continue

        if unit in {"g", "gr", "gram", "ml", "cc"}:
            if val > MAX_SINGLE_DISH_GRAMS and not _RE_WATER_ALLOWED.search(clean):
                raise FoodGuardrailRejected(
                    "implausible_portion",
                    f"Berat/volume {val:,.0f} {unit} melebihi batas wajar 1 hidangan (maks. {MAX_SINGLE_DISH_GRAMS:,.0f}g/ml).",
                )
            continue

        if unit == "oz":
            if val > 40.0:
                raise FoodGuardrailRejected("implausible_portion", f"Takaran {val:g} oz melebihi batas wajar 1 kali makan.")
            continue

        if unit in COUNTABLE_LARGE_UNITS:
            if val > MAX_COUNTABLE_LARGE_UNIT:
                raise FoodGuardrailRejected(
                    "implausible_portion",
                    f"Jumlah {val:g} {unit} terlalu besar untuk 1 catatan makan (maks. {int(MAX_COUNTABLE_LARGE_UNIT)} {unit}).",
                )
            continue

        if unit in COUNTABLE_SMALL_UNITS:
            if val > MAX_COUNTABLE_SMALL_UNIT:
                raise FoodGuardrailRejected(
                    "implausible_portion",
                    f"Jumlah {val:g} {unit} tidak realistis untuk 1 kali makan (maks. {int(MAX_COUNTABLE_SMALL_UNIT)} {unit}).",
                )
            continue

        # Kecualikan nomor barcode resmi pada fallback nama produk Open Food Facts
        if not unit and val >= 10000000 and re.search(r"\bbarcode\s+\d{8,18}\b", clean, re.IGNORECASE):
            continue

        # Pada nama entri katalog/staging, kode varian di belakang nama ("Regal 1952" / "Produk 999") sah selama < 10.000
        if allow_trailing_model_code and not unit and val < 10000 and match.start() > 0:
            continue

        # Angka tanpa satuan (mis. "100.000 sate ayam" atau "500 bakso")
        if val > MAX_COUNTABLE_SMALL_UNIT:
            raise FoodGuardrailRejected(
                "implausible_portion",
                f"Kuantitas {val:,.0f} porsi/item terlalu ekstrem untuk 1 kali makan. Gunakan takaran perorangan yang wajar.",
            )


def validate_food_text_query(text_input: str) -> str:
    """Memvalidasi teks menu makanan pengguna sebelum memanggil Gemini API (0 token bila invalid)."""
    clean = " ".join((text_input or "").strip().split())
    check_prompt_injection(clean)
    _check_text_gibberish(clean)
    _check_taboo_and_non_food(clean)
    _check_quantity_plausibility(clean)
    return clean


def validate_photo_caption(caption: str) -> str:
    """Menyaring keterangan opsional foto terhadap prompt injection, konten iseng, atau porsi mustahil."""
    clean = " ".join((caption or "").strip().split())
    if not clean:
        return ""
    if len(clean) > 160:
        clean = clean[:160].strip()
    check_prompt_injection(clean)
    _check_taboo_and_non_food(clean)
    _check_quantity_plausibility(clean)
    return clean


def validate_nutrition_sanity(
    energy_kcal: float,
    protein_g: float,
    fat_g: float,
    carb_g: float,
    fiber_g: float = 0.0,
    weight_g: float = 100.0,
    is_catalog_entry: bool = True,
):
    """Memeriksa kewajaran fisika gizi Atwater dan batas kepadatan energi per 100g / per sajian."""
    kcal = float(energy_kcal or 0.0)
    p = float(protein_g or 0.0)
    f = float(fat_g or 0.0)
    c = float(carb_g or 0.0)
    fib = float(fiber_g or 0.0)
    w = float(weight_g or 100.0)

    if any(v < 0 for v in (kcal, p, f, c, fib)) or w <= 0:
        raise FoodGuardrailRejected("invalid_nutrition", "Angka nutrisi atau berat pangan tidak boleh negatif.")

    if is_catalog_entry:
        if kcal > MAX_DENSITY_KCAL_PER_100G:
            raise FoodGuardrailRejected(
                "invalid_nutrition",
                f"Kalori {kcal:.1f} kkal/100g melebihi batas fisik maksimum pangan ({MAX_DENSITY_KCAL_PER_100G:.0f} kkal/100g).",
            )
        if (p + f + c) > 105.0 or max(p, f, c, fib) > 100.0:
            raise FoodGuardrailRejected(
                "invalid_nutrition",
                "Total makronutrien (Protein + Lemak + Karbohidrat) melebihi 105g per 100g bahan pangan.",
            )
    else:
        if kcal > MAX_SINGLE_DISH_KCAL:
            raise FoodGuardrailRejected(
                "implausible_portion",
                f"Kalori satu hidangan ({kcal:,.1f} kkal) melebihi batas wajar per sajian ({MAX_SINGLE_DISH_KCAL:,.0f} kkal).",
            )
        if max(p, f) > 200.0 or c > 400.0:
            raise FoodGuardrailRejected(
                "invalid_nutrition",
                "Nilai makronutrien per sajian melebihi batas wajar konsumsi satu kali makan.",
            )

    atwater_kcal = (4.0 * p) + (9.0 * f) + (4.0 * c)
    macro_sum = p + f + c
    if kcal >= 150.0 and macro_sum < (kcal / 12.0):
        raise FoodGuardrailRejected(
            "invalid_nutrition",
            "Angka kalori terlalu tinggi sementara Protein, Lemak, dan Karbohidrat hampir nol (tidak konsisten secara ilmiah).",
        )
    if macro_sum >= 15.0 and atwater_kcal > 0 and kcal > max(atwater_kcal * 2.2 + 120.0, 300.0):
        raise FoodGuardrailRejected(
            "invalid_nutrition",
            "Angka kalori tidak selaras dengan perhitungan Atwater (4P + 9L + 4K) dari makronutriennya.",
        )


def validate_food_candidate(
    food_name: str,
    energy_kcal: float,
    protein_g: float = 0.0,
    fat_g: float = 0.0,
    carb_g: float = 0.0,
    fiber_g: float = 0.0,
    is_catalog_entry: bool = True,
) -> str:
    """Memvalidasi kelayakan nama pangan sekaligus kewajaran angka gizinya sebelum disimpan ke katalog/staging."""
    clean_name = " ".join((food_name or "").strip().split())
    check_prompt_injection(clean_name)
    _check_text_gibberish(clean_name)
    _check_taboo_and_non_food(clean_name)
    _check_quantity_plausibility(clean_name, allow_trailing_model_code=is_catalog_entry)
    validate_nutrition_sanity(
        energy_kcal=energy_kcal,
        protein_g=protein_g,
        fat_g=fat_g,
        carb_g=carb_g,
        fiber_g=fiber_g,
        weight_g=100.0,
        is_catalog_entry=is_catalog_entry,
    )
    return clean_name


def validate_extracted_dish_totals(dish_name: str, totals: dict):
    """Memastikan hasil akhir kalkulasi 1 hidangan (dari AI atau Preview) masuk dalam batas biologis wajar."""
    clean_name = " ".join((dish_name or "").strip().split())
    if clean_name:
        _check_taboo_and_non_food(clean_name)

    total_w = float((totals or {}).get("total_weight_g") or 0.0)
    total_k = float((totals or {}).get("energy_kcal") or 0.0)
    if total_w > MAX_SINGLE_DISH_GRAMS * 2.0 or total_k > MAX_SINGLE_DISH_KCAL * 1.5:
        raise FoodGuardrailRejected(
            "implausible_portion",
            f"Total porsi hidangan ({total_w:,.0f}g · {total_k:,.0f} kkal) melampaui batas wajar konsumsi perorangan.",
        )


def is_excluded_from_public_catalog(food_name: str) -> bool:
    """Menyaring entri ekstrem/tabu bawaan TKPI agar tidak tampil pada pencarian & pencocokan publik."""
    masked = _mask_culinary_idioms(food_name or "")
    return bool(_RE_EXTREME_TABOO.search(masked) or _RE_POISON_FILTH.search(masked))


def validate_display_name(display_name: str) -> tuple[bool, str]:
    """Menolak nama akun dengan tag HTML berbahaya, kata kasar/kotoran, atau panjang berlebih."""
    clean = " ".join((display_name or "").strip().split())
    if not clean:
        return True, ""
    if len(clean) > 40:
        return False, "Nama panggilan maksimal 40 karakter."
    if "<" in clean or ">" in clean:
        return False, "Nama panggilan tidak boleh mengandung karakter HTML `<` atau `>`."
    if _RE_POISON_FILTH.search(_mask_culinary_idioms(clean)):
        return False, "Nama panggilan mengandung kata yang tidak pantas."
    return True, clean
