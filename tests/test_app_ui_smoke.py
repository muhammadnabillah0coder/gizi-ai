"""
Uji Integrasi Streamlit UI (AppTest) untuk memverifikasi alur Preview, Slider Porsi
tanpa penulisan DB berulang, Simpan Anti-Dobel, Water Tracker (water_data),
Edit Inline, Hapus Catatan, dan Pencarian Database TKPI Ter-Cache.
"""

import os
import sys
import time
import uuid
import sqlite3
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db_history


class TestAppUISmoke(unittest.TestCase):
    def setUp(self):
        db_history.init_user_history_tables()
        self.test_uid = f"ui_smoke_{uuid.uuid4().hex[:8]}@example.com"
        ok, _ = db_history.register_user(self.test_uid, "UI Smoke", "1234", bb=65.0)
        self.assertTrue(ok)
        self.session_tok = db_history.create_session_token(self.test_uid)

    def tearDown(self):
        conn = sqlite3.connect(db_history.DB_PATH)
        cur = conn.cursor()
        for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "users"):
            cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (self.test_uid,))
        conn.commit()
        conn.close()

    def test_quick_plate_preview_slider_save_edit_delete_and_water(self):
        from streamlit.testing.v1 import AppTest

        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        at = AppTest.from_file(app_path, default_timeout=30)
        at.query_params["u"] = self.test_uid
        at.query_params["s"] = self.session_tok

        t_boot0 = time.perf_counter()
        at.run()
        boot_ms = (time.perf_counter() - t_boot0) * 1000.0
        self.assertEqual(len(at.exception), 0, f"Boot UI exception: {at.exception}")

        # 1. Klik Piring Cepat Kopi Susu Aren -> Preview
        btn_qp = next(b for b in at.button if b.key == "dash_qp_4")
        t_prev0 = time.perf_counter()
        btn_qp.click().run()
        prev_ms = (time.perf_counter() - t_prev0) * 1000.0
        self.assertEqual(len(at.exception), 0, f"Preview exception: {at.exception}")

        # 2. Geser slider porsi (prev_mult_diary_) -> pastikan 0 exception & rerun cepat
        sl_prev = next(s for s in at.select_slider if (s.key or "").startswith("prev_mult_diary_"))
        new_opt = 0.5 if sl_prev.value != 0.5 else 1.5
        t_sl0 = time.perf_counter()
        sl_prev.set_value(new_opt).run()
        slider_ms = (time.perf_counter() - t_sl0) * 1000.0
        self.assertEqual(len(at.exception), 0, f"Slider exception: {at.exception}")

        # 3. Simpan ke Buku Harian
        btn_save = next(b for b in at.button if (b.key or "").startswith("prev_btn_save_diary_"))
        btn_save.click().run()
        self.assertEqual(len(at.exception), 0, f"Save exception: {at.exception}")

        today_str = db_history.get_local_now(8).strftime("%Y-%m-%d")
        stats_after_save = db_history.get_user_history_stats(self.test_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(stats_after_save["today_totals"]["count"], 1)
        saved_id = stats_after_save["today_meals"][0]["id"]
        saved_kcal = stats_after_save["today_meals"][0]["energy_kcal"]

        # 4. Uji Water Tracker (+/-) memastikan bundle water_data sinkron
        btn_w_plus = next(b for b in at.button if b.key == "btn_add_water")
        btn_w_plus.click().run()
        self.assertEqual(len(at.exception), 0, f"Water + exception: {at.exception}")
        self.assertEqual(db_history.get_water_intake(self.test_uid, tz_offset=8)["glasses"], 1)

        btn_w_minus = next(b for b in at.button if b.key == "btn_sub_water")
        btn_w_minus.click().run()
        self.assertEqual(len(at.exception), 0, f"Water - exception: {at.exception}")
        self.assertEqual(db_history.get_water_intake(self.test_uid, tz_offset=8)["glasses"], 0)

        # 5. Edit porsi inline di Buku Harian (anti-dobel) -> pastikan kalori terskala & 1 baris
        sl_edit = next(s for s in at.select_slider if s.key == f"ed_mult_{saved_id}")
        sl_edit.set_value(1.5).run()
        self.assertEqual(len(at.exception), 0, f"Edit slider exception: {at.exception}")
        btn_ed_save = next(b for b in at.button if b.key == f"btn_ed_save_{saved_id}")
        btn_ed_save.click().run()
        self.assertEqual(len(at.exception), 0, f"Inline edit exception: {at.exception}")
        stats_after_edit = db_history.get_user_history_stats(self.test_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(stats_after_edit["today_totals"]["count"], 1)
        self.assertGreater(stats_after_edit["today_meals"][0]["energy_kcal"], saved_kcal)

        btn_del = next(b for b in at.button if b.key == f"del_{saved_id}")
        btn_del.click().run()
        self.assertEqual(len(at.exception), 0, f"Delete exception: {at.exception}")
        stats_after_del = db_history.get_user_history_stats(self.test_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(stats_after_del["today_totals"]["count"], 0)

        # 6. Uji filter & pencarian Database TKPI ter-cache
        kb_in = next(t for t in at.text_input if t.key == "kb_search")
        kb_in.input("Ayam").run()
        self.assertEqual(len(at.exception), 0, f"DB search exception: {at.exception}")

        # 7. Logout via Sidebar harus membersihkan last_saved_item & nutrition_data (BUG-08)
        at.session_state["last_saved_item"] = {"id": 999, "dish_name": "Bocoran"}
        btn_logout = next(b for b in at.button if b.key == "sb_btn_logout")
        btn_logout.click().run()
        self.assertEqual(len(at.exception), 0, f"Logout exception: {at.exception}")
        self.assertIsNone(at.session_state["last_saved_item"])
        self.assertIsNone(at.session_state["nutrition_data"])

        print(f"[AppTest Latency] boot={boot_ms:.1f}ms preview={prev_ms:.1f}ms slider={slider_ms:.1f}ms")

    def test_admin_session_pending_foods_and_panel_no_typeerror(self):
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest

        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        with patch.object(db_history, "ADMIN_IDENTIFIERS", db_history.ADMIN_IDENTIFIERS | {self.test_uid}):
            at = AppTest.from_file(app_path, default_timeout=30)
            at.query_params["u"] = self.test_uid
            at.query_params["s"] = self.session_tok
            at.run()
            self.assertEqual(len(at.exception), 0, f"Admin UI crash: {at.exception}")


if __name__ == "__main__":
    unittest.main()
