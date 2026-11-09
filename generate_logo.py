"""
Script Pembuat Logo Resmi Nutrisi Cerdas:
1. Ukuran standar Google OAuth Consent Logo: 512x512 piksel & 120x120 piksel (< 1MB, format PNG).
2. Konsep: Apple Healthtech Minimalist (Gradasi Emerald Green #10b981 ke Mint #059669, squircle superellipse, ikon daun sehat & kilau AI emas).
"""

from PIL import Image, ImageDraw, ImageFont
import math
import os

def create_nutrisi_cerdas_logo(size=512):
    # Buat kanvas RGBA transparan
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 1. Background Squircle / Rounded Rectangle dengan Gradasi
    padding = int(size * 0.05)
    corner_radius = int(size * 0.22)
    
    # Buat base gradient
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base_draw = ImageDraw.Draw(base)
    
    # Mask rounded rect
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(
        [padding, padding, size - padding, size - padding],
        radius=corner_radius,
        fill=255
    )
    
    # Isi dengan gradasi Emerald ke Deep Mint (#10b981 -> #047857)
    for y in range(size):
        interp = y / float(size)
        r = int(16 * (1 - interp) + 4 * interp)
        g = int(185 * (1 - interp) + 120 * interp)
        b = int(129 * (1 - interp) + 87 * interp)
        base_draw.line([(0, y), (size, y)], fill=(r, g, b, 255))
        
    img.paste(base, (0, 0), mask)
    
    # 2. Gambar Vektor Ikon Mangkuk Gizi Sehat & Daun Tunas Minimalis (Clean Tech)
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    
    cx, cy = size // 2, size // 2
    scale = size / 512.0
    
    # Mangkuk Minimalis (Lengkungan bawah)
    bowl_top = int(cy + 10 * scale)
    bowl_bottom = int(cy + 120 * scale)
    bowl_left = int(cx - 130 * scale)
    bowl_right = int(cx + 130 * scale)
    
    ov_draw.chord(
        [bowl_left, bowl_top - int(80 * scale), bowl_right, bowl_bottom],
        start=0,
        end=180,
        fill=(255, 255, 255, 245)
    )
    
    # Garis Bibir Mangkuk Elegan
    ov_draw.rounded_rectangle(
        [bowl_left - int(10 * scale), bowl_top - int(6 * scale), bowl_right + int(10 * scale), bowl_top + int(10 * scale)],
        radius=int(8 * scale),
        fill=(255, 255, 255, 255)
    )
    
    # 3. Dua Daun Organik Tunas Sehat (Emerald Light & Mint)
    # Daun Kiri (Besar melengkung)
    leaf1_points = [
        (cx, int(cy - 10 * scale)),
        (int(cx - 90 * scale), int(cy - 60 * scale)),
        (int(cx - 100 * scale), int(cy - 140 * scale)),
        (int(cx - 20 * scale), int(cy - 120 * scale)),
        (cx, int(cy - 10 * scale))
    ]
    ov_draw.polygon(leaf1_points, fill=(255, 255, 255, 230))
    
    # Daun Kanan (Melengkung ke atas dinamis)
    leaf2_points = [
        (cx, int(cy - 10 * scale)),
        (int(cx + 40 * scale), int(cy - 80 * scale)),
        (int(cx + 95 * scale), int(cy - 150 * scale)),
        (int(cx + 105 * scale), int(cy - 80 * scale)),
        (cx, int(cy - 10 * scale))
    ]
    ov_draw.polygon(leaf2_points, fill=(240, 253, 244, 255))
    
    # 4. Simbol Bintang Kilau AI / Cerdas (Sparkle) di Puncak Kanan
    sp_cx = int(cx + 110 * scale)
    sp_cy = int(cy - 145 * scale)
    sp_r = int(28 * scale)
    sp_color = (254, 240, 138, 255) # Emas lembut / soft gold
    
    # Gambar 4-point star
    star_pts = [
        (sp_cx, sp_cy - sp_r),
        (sp_cx + int(sp_r * 0.28), sp_cy - int(sp_r * 0.28)),
        (sp_cx + sp_r, sp_cy),
        (sp_cx + int(sp_r * 0.28), sp_cy + int(sp_r * 0.28)),
        (sp_cx, sp_cy + sp_r),
        (sp_cx - int(sp_r * 0.28), sp_cy + int(sp_r * 0.28)),
        (sp_cx - sp_r, sp_cy),
        (sp_cx - int(sp_r * 0.28), sp_cy - int(sp_r * 0.28))
    ]
    ov_draw.polygon(star_pts, fill=sp_color)
    
    # Gabungkan overlay ke gambar utama
    img = Image.alpha_composite(img, overlay)
    return img

if __name__ == "__main__":
    out_dir = os.path.dirname(__file__)
    
    # Simpan logo 512x512
    logo_512 = create_nutrisi_cerdas_logo(512)
    path_512 = os.path.join(out_dir, "logo_nutrisi_cerdas_512.png")
    logo_512.save(path_512, "PNG")
    print(f"Logo 512x512 tersimpan di: {path_512}")
    
    # Simpan versi khusus Google OAuth Consent Screen (120x120 px, ukuran wajib Google)
    logo_120 = logo_512.resize((120, 120), Image.Resampling.LANCZOS)
    path_120 = os.path.join(out_dir, "logo_nutrisi_cerdas_120.png")
    logo_120.save(path_120, "PNG")
    print(f"Logo 120x120 (Google OAuth) tersimpan di: {path_120}")
