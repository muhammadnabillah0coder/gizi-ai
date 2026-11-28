"""
Utilitas Pembersih & Auditor Seed Database (tkpi_nutrition.db) untuk Git Publik.
Memastikan file database yang di-commit ke repositori 100% murni katalog pangan (TKPI & Ritel)
tanpa menyertakan data akun pengguna, catatan makan, maupun secret sesi (app_meta).
"""

import argparse
import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

USER_DATA_TABLES = (
    "users",
    "meal_logs",
    "water_logs",
    "weight_logs",
    "custom_foods",
    "pending_foods",
    "payment_orders",
    "pro_vouchers",
    "voucher_redemptions",
    "oauth_used_nonces",
    "app_meta",
)


def check_seed_db_clean(db_path: str = DB_PATH) -> tuple[bool, dict]:
    """Memeriksa apakah file seed tkpi_nutrition.db bebas dari data pengguna & secret."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    existing_tables = {
        r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    report = {}
    for tbl in ("food_composition", *USER_DATA_TABLES):
        if tbl in existing_tables:
            report[tbl] = int(cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
        else:
            report[tbl] = 0
    conn.close()

    dirty_tables = {t: report[t] for t in USER_DATA_TABLES if report.get(t, 0) > 0}
    catalog_ok = report.get("food_composition", 0) >= 1300
    return (len(dirty_tables) == 0 and catalog_ok), {
        "counts": report,
        "dirty_tables": dirty_tables,
        "catalog_ok": catalog_ok,
    }


def sanitize_seed_db(db_path: str = DB_PATH) -> dict:
    """Mengosongkan seluruh tabel non-katalog & menjalankan VACUUM pada seed tkpi_nutrition.db."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    existing_tables = {
        r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    removed = {}
    for tbl in USER_DATA_TABLES:
        if tbl in existing_tables:
            cnt = int(cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
            cur.execute(f"DELETE FROM {tbl}")
            removed[tbl] = cnt
    if "sqlite_sequence" in existing_tables:
        placeholders = ",".join("?" for _ in USER_DATA_TABLES)
        cur.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})", USER_DATA_TABLES)
    conn.commit()
    cur.execute("VACUUM")
    conn.close()
    is_clean, status = check_seed_db_clean(db_path)
    return {"removed": removed, "is_clean": is_clean, **status}


def main():
    parser = argparse.ArgumentParser(description="Bersihkan atau audit seed tkpi_nutrition.db")
    parser.add_argument("--check", action="store_true", help="Hanya periksa kebersihan tanpa mengubah DB")
    parser.add_argument("--db", default=DB_PATH, help="Path file SQLite target")
    args = parser.parse_args()

    if args.check:
        ok, info = check_seed_db_clean(args.db)
        print(f"Seed DB check ({args.db}): {'CLEAN' if ok else 'DIRTY'} | counts={info['counts']}")
        if not ok:
            print(f"Dirty tables: {info['dirty_tables']} | catalog_ok={info['catalog_ok']}")
            sys.exit(1)
        sys.exit(0)

    res = sanitize_seed_db(args.db)
    print(f"Seed DB sanitized ({args.db}): removed={res['removed']} | clean={res['is_clean']} | food_composition={res['counts']['food_composition']}")
    if not res["is_clean"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
