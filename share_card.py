"""
Generator Kartu Visual Ringkasan Harian Nutrisi Cerdas (PNG 1080x1920 / 9:16)
Siap dibagikan ke Instagram Story dan WhatsApp Status dengan desain Unslop 60/30/10
(Warm Lab Paper Terang & Quiet Graphite Gelap), 100% lokal menggunakan Pillow (<120ms).
"""

import io
import math
import os
from PIL import Image, ImageDraw, ImageFont

_MODULE_MTIME = round(os.path.getmtime(__file__), 6) if os.path.exists(__file__) else 0.0

CARD_WIDTH = 1080
CARD_HEIGHT = 1920

_PALETTES = {
    "light": {
        "bg": (247, 246, 242),
        "card": (255, 255, 255),
        "surface": (239, 236, 230),
        "border": (222, 218, 210),
        "text_primary": (28, 25, 23),
        "text_secondary": (87, 83, 78),
        "text_muted": (120, 113, 108),
        "accent": (21, 128, 61),
        "accent_fg": (255, 255, 255),
        "protein": (3, 105, 161),
        "fat": (180, 83, 9),
        "fiber": (109, 40, 217),
        "danger": (185, 28, 28),
        "track": (232, 228, 220),
    },
    "dark": {
        "bg": (20, 20, 21),
        "card": (27, 27, 30),
        "surface": (36, 36, 40),
        "border": (54, 54, 60),
        "text_primary": (237, 237, 237),
        "text_secondary": (166, 166, 173),
        "text_muted": (133, 133, 140),
        "accent": (52, 211, 153),
        "accent_fg": (11, 19, 16),
        "protein": (56, 189, 248),
        "fat": (245, 158, 11),
        "fiber": (167, 139, 250),
        "danger": (229, 72, 77),
        "track": (48, 48, 54),
    },
}

_FONT_CANDIDATES = {
    "sans_regular": [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "sans_bold": [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    "mono_bold": [
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/lucon.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    ],
    "mono_regular": [
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ],
}


def _load_font(kind: str, size: int):
    for fpath in _FONT_CANDIDATES.get(kind, []):
        if os.path.exists(fpath):
            try:
                return ImageFont.truetype(fpath, size=size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _truncate_text(text: str, max_chars: int) -> str:
    clean = " ".join(str(text or "").strip().split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(1, max_chars - 3)].rstrip() + "..."


def _draw_brand_emblem(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, pal: dict):
    """Menggambar emblem geometris datar Nutrisi Cerdas (kotak bulat + mangkuk + daun)."""
    r = int(size * 0.25)
    draw.rounded_rectangle([x, y, x + size, y + size], radius=r, fill=pal["accent"])
    # Mangkuk bawah (setengah lingkaran)
    bx1 = x + int(size * 0.22)
    by1 = y + int(size * 0.34)
    bx2 = x + int(size * 0.78)
    by2 = y + int(size * 0.80)
    draw.pieslice([bx1, by1, bx2, by2], start=0, end=180, fill=pal["accent_fg"])
    # Daun kanan atas
    lx1 = x + int(size * 0.48)
    ly1 = y + int(size * 0.20)
    lx2 = x + int(size * 0.76)
    ly2 = y + int(size * 0.48)
    draw.ellipse([lx1, ly1, lx2, ly2], fill=pal["accent_fg"])
    # Daun kiri kecil
    sx1 = x + int(size * 0.28)
    sy1 = y + int(size * 0.28)
    sx2 = x + int(size * 0.49)
    sy2 = y + int(size * 0.49)
    draw.ellipse([sx1, sy1, sx2, sy2], fill=pal["accent_fg"])


def _render_ring_image(pct_actual: float, pal: dict, size: int = 320) -> Image.Image:
    """Merender cincin kalori presisi 2x supersampled dengan 12 tanda skala lab."""
    scale = 2
    s = size * scale
    ring_img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(ring_img)
    cx, cy = s // 2, s // 2
    r_outer = int(s * 0.45)
    r_inner_tick = int(s * 0.425)
    for i in range(12):
        ang = math.radians(i * 30.0 - 90.0)
        x1 = cx + r_inner_tick * math.cos(ang)
        y1 = cy + r_inner_tick * math.sin(ang)
        x2 = cx + r_outer * math.cos(ang)
        y2 = cy + r_outer * math.sin(ang)
        d.line([(x1, y1), (x2, y2)], fill=pal["border"], width=3)

    r_ring = int(s * 0.365)
    stroke = int(s * 0.068)
    bbox = [cx - r_ring, cy - r_ring, cx + r_ring, cy + r_ring]
    d.arc(bbox, start=0, end=360, fill=pal["track"], width=stroke)

    clamped_pct = max(0.0, min(100.0, float(pct_actual)))
    if clamped_pct > 0.2:
        arc_col = pal["danger"] if pct_actual > 105.0 else pal["accent"]
        end_deg = -90.0 + (360.0 * (clamped_pct / 100.0))
        d.arc(bbox, start=-90.0, end=end_deg, fill=arc_col, width=stroke)

    pct_label = f"{pct_actual:.0f}%" if abs(pct_actual - round(pct_actual)) < 0.05 else f"{pct_actual:.1f}%"
    f_pct = _load_font("mono_bold", int(46 * scale))
    f_sub = _load_font("sans_regular", int(22 * scale))
    d.text((cx, cy - int(18 * scale)), pct_label, font=f_pct, fill=pal["text_primary"], anchor="mm")
    d.text((cx, cy + int(24 * scale)), "dari target", font=f_sub, fill=pal["text_muted"], anchor="mm")

    return ring_img.resize((size, size), Image.Resampling.LANCZOS)


def generate_daily_share_card_png(
    *,
    display_name: str,
    date_label: str,
    focus_goal: str,
    fasting_mode: str,
    today_kcal: float,
    target_kcal: float,
    totals: dict,
    macro_targets: dict,
    water_data: dict,
    streak_days: int,
    today_meals: list,
    style: str = "light",
) -> bytes:
    """Menghasilkan gambar PNG 1080x1920 (9:16) siap unggah ke IG Story & Status WA."""
    pal = _PALETTES["dark" if str(style).lower() == "dark" else "light"]
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), pal["bg"])
    draw = ImageDraw.Draw(img)

    # Font hierarki tenang (sans + mono tabular)
    f_brand = _load_font("sans_bold", 38)
    f_sub = _load_font("sans_regular", 26)
    f_label = _load_font("sans_regular", 25)
    f_sec = _load_font("sans_bold", 30)
    f_hero_num = _load_font("mono_bold", 64)
    f_hero_unit = _load_font("mono_regular", 30)
    f_val = _load_font("mono_bold", 34)
    f_strip_val = _load_font("mono_bold", 26)
    f_small_mono = _load_font("mono_regular", 24)
    f_dish = _load_font("sans_bold", 27)
    f_footer = _load_font("mono_regular", 23)

    pad = 72
    w_inner = CARD_WIDTH - (pad * 2)

    # 1. Header Brand (aman di bawah notch & header IG Story: y=132)
    y = 132
    _draw_brand_emblem(draw, pad, y, 76, pal)
    draw.text((pad + 98, y + 6), "Nutrisi Cerdas", font=f_brand, fill=pal["text_primary"])
    fast_short = ""
    if fasting_mode == "Puasa Sunnah / Ramadan":
        fast_short = " · Mode Puasa"
    elif fasting_mode == "Intermittent Fasting 16:8":
        fast_short = " · IF 16:8"
    elif fasting_mode and fasting_mode != "Normal":
        fast_short = f" · {fasting_mode}"
    draw.text(
        (pad + 98, y + 48),
        _truncate_text(f"{date_label} · {focus_goal}{fast_short}", 48),
        font=f_sub,
        fill=pal["text_muted"],
    )

    # Badge Streak kanan atas bila streak > 0
    if streak_days and int(streak_days) > 0:
        st_txt = f"Streak {int(streak_days)} hari"
        bbox_st = draw.textbbox((0, 0), st_txt, font=f_small_mono)
        tw = bbox_st[2] - bbox_st[0]
        bx1 = CARD_WIDTH - pad - tw - 36
        draw.rounded_rectangle([bx1, y + 14, CARD_WIDTH - pad, y + 62], radius=12, fill=pal["surface"], outline=pal["border"], width=2)
        draw.text((bx1 + 18, y + 26), st_txt, font=f_small_mono, fill=pal["accent"])

    # 2. Kartu Utama Kalori & Ring Terkalibrasi
    y = 252
    hero_h = 440
    draw.rounded_rectangle([pad, y, pad + w_inner, y + hero_h], radius=28, fill=pal["card"], outline=pal["border"], width=2)

    pct_actual = round((float(today_kcal) / max(1.0, float(target_kcal))) * 100.0, 1)
    ring_im = _render_ring_image(pct_actual, pal, size=312)
    img.paste(ring_im, (pad + w_inner - 352, y + 64), ring_im)

    tx = pad + 44
    draw.text((tx, y + 44), f"Ringkasan Harian · {_truncate_text(display_name, 22)}", font=f_label, fill=pal["text_muted"])
    draw.text((tx, y + 96), f"{today_kcal:,.0f}", font=f_hero_num, fill=pal["text_primary"])
    draw.text((tx, y + 174), f"dari {target_kcal:,.0f} kkal", font=f_hero_unit, fill=pal["text_muted"])

    delta = float(target_kcal) - float(today_kcal)
    if delta >= 0:
        status_txt = f"Sisa budget {delta:,.0f} kkal"
        status_col = pal["accent"]
    else:
        status_txt = f"Melebihi +{abs(delta):,.0f} kkal"
        status_col = pal["danger"]
    draw.text((tx, y + 240), status_txt, font=f_sec, fill=status_col)

    meals_cnt = int(totals.get("count") or len(today_meals))
    draw.text((tx, y + 306), f"{meals_cnt} menu tercatat · Lab TKPI Kemenkes", font=f_label, fill=pal["text_secondary"])

    # 3. Grid Makronutrien 2x2
    y = y + hero_h + 32
    macro_h = 336
    draw.rounded_rectangle([pad, y, pad + w_inner, y + macro_h], radius=28, fill=pal["card"], outline=pal["border"], width=2)
    draw.text((pad + 44, y + 32), "Keseimbangan Makronutrien", font=f_sec, fill=pal["text_primary"])

    macros = [
        ("Protein", float(totals.get("protein_g") or 0.0), float(macro_targets.get("protein_g") or 100.0), pal["protein"]),
        ("Lemak", float(totals.get("fat_g") or 0.0), float(macro_targets.get("fat_g") or 60.0), pal["fat"]),
        ("Karbohidrat", float(totals.get("carb_g") or 0.0), float(macro_targets.get("carb_g") or 250.0), pal["accent"]),
        ("Serat", float(totals.get("fiber_g") or 0.0), float(macro_targets.get("fiber_g") or 25.0), pal["fiber"]),
    ]
    cell_w = (w_inner - 128) // 2
    for idx, (m_lbl, m_val, m_tgt, m_col) in enumerate(macros):
        col_i = idx % 2
        row_i = idx // 2
        mx = pad + 44 + col_i * (cell_w + 40)
        my = y + 96 + row_i * 112
        draw.text((mx, my), m_lbl, font=f_label, fill=pal["text_muted"])
        draw.text((mx, my + 34), f"{m_val:.1f}g / {m_tgt:.0f}g", font=f_val, fill=pal["text_primary"])
        bar_y = my + 82
        draw.rounded_rectangle([mx, bar_y, mx + cell_w, bar_y + 10], radius=5, fill=pal["track"])
        ratio = max(0.0, min(1.0, m_val / max(1.0, m_tgt)))
        if ratio > 0.01:
            fw = max(10, int(cell_w * ratio))
            draw.rounded_rectangle([mx, bar_y, mx + fw, bar_y + 10], radius=5, fill=m_col)

    # 4. Strip Rambu GGL & Hidrasi (3 kolom sejajar)
    y = y + macro_h + 32
    ggl_h = 160
    draw.rounded_rectangle([pad, y, pad + w_inner, y + ggl_h], radius=28, fill=pal["card"], outline=pal["border"], width=2)
    sug_v = float(totals.get("sugar_g") or 0.0)
    sug_t = float(macro_targets.get("sugar_g") or 50.0)
    sod_v = float(totals.get("sodium_mg") or 0.0)
    sod_t = float(macro_targets.get("sodium_mg") or 2000.0)
    w_gl = int(water_data.get("glasses") or 0)
    w_tg = int(water_data.get("target") or 8)

    strips = [
        ("Gula (GGL)", f"{sug_v:.1f} / {sug_t:.0f}g", pal["danger"] if sug_v > sug_t else pal["text_primary"]),
        ("Natrium (GGL)", f"{sod_v:,.0f} / {sod_t:,.0f}mg", pal["danger"] if sod_v > sod_t else pal["text_primary"]),
        ("Air Minum", f"{w_gl} / {w_tg} gelas", pal["accent"] if w_gl >= w_tg else pal["text_primary"]),
    ]
    col_starts = [pad + 40, pad + 312, pad + 656]
    for idx, (s_lbl, s_val, s_col) in enumerate(strips):
        sx = col_starts[idx]
        if idx > 0:
            draw.line([(sx - 24, y + 36), (sx - 24, y + ggl_h - 36)], fill=pal["border"], width=2)
        draw.text((sx, y + 36), s_lbl, font=f_label, fill=pal["text_muted"])
        draw.text((sx, y + 84), s_val, font=f_strip_val, fill=s_col)

    # 5. Daftar Menu Pilihan Hari Ini (maks 4 baris rapi)
    y = y + ggl_h + 32
    list_h = 414
    draw.rounded_rectangle([pad, y, pad + w_inner, y + list_h], radius=28, fill=pal["card"], outline=pal["border"], width=2)
    draw.text((pad + 44, y + 32), "Catatan Menu Hari Ini", font=f_sec, fill=pal["text_primary"])

    if today_meals:
        shown = today_meals[:4]
        row_y = y + 96
        for idx, m in enumerate(shown):
            if idx > 0:
                draw.line([(pad + 44, row_y - 14), (pad + w_inner - 44, row_y - 14)], fill=pal["border"], width=2)
            d_name = _truncate_text(m.get("dish_name", "Menu"), 32)
            m_type = _truncate_text(m.get("meal_type", ""), 18)
            m_kcal = f"{float(m.get('energy_kcal') or 0.0):,.0f} kkal"
            draw.text((pad + 44, row_y), d_name, font=f_dish, fill=pal["text_primary"])
            draw.text((pad + 44, row_y + 34), m_type, font=f_small_mono, fill=pal["text_muted"])
            draw.text((pad + w_inner - 44, row_y + 12), m_kcal, font=f_val, fill=pal["accent"], anchor="ra")
            row_y += 72
    else:
        draw.text((pad + 44, y + 140), "Belum ada menu tercatat pada tanggal ini.", font=f_sub, fill=pal["text_muted"])

    # 6. Footer Brand Tenang (aman di atas kotak balas IG Story / WA Status)
    fy = CARD_HEIGHT - 160
    draw.line([(pad, fy - 24), (pad + w_inner, fy - 24)], fill=pal["border"], width=2)
    draw.text((pad, fy), "nutrisi-cerdas.streamlit.app", font=f_sec, fill=pal["accent"])
    draw.text((pad + w_inner, fy + 6), "Basis 1.304 Data Lab TKPI Kemenkes RI", font=f_footer, fill=pal["text_muted"], anchor="ra")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
