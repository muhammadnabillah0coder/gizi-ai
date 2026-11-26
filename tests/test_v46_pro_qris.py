"""
Suite Pengujian Regresi v4.6.0 Nutrisi Cerdas (Paket Pro, Gerbang Kuota & Pembayaran QRIS):
1. Prioritas Paket Pro atas OPEN_BETA_MODE, unlimited scan foto, dan perpanjangan stacking adil.
2. Voucher aktivasi Pro: blokir tamu, redeem sukses, anti-duplikasi & batas max_uses.
3. Payment Gateway & Webhook QRIS (Midtrans SHA-512 & Mayar Token): fail-closed, anti-underpayment, idempoten,
   checkout mocked API Mayar/Midtrans & fallback manual WA.
4. Metrik Growth Admin (target 100 user) & E2E AppTest redeem voucher Pro langsung di UI.
"""

import hashlib
import os
import sqlite3
import sys
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db_history
import payment_gateway

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TestV46ProAndQris(unittest.TestCase):
    def setUp(self):
        db_history.init_user_history_tables()
        self.uid1 = f"pro1_{uuid.uuid4().hex[:8]}@example.com"
        self.uid2 = f"pro2_{uuid.uuid4().hex[:8]}@example.com"
        ok1, _ = db_history.register_user(self.uid1, "Pengguna Satu", "1234")
        ok2, _ = db_history.register_user(self.uid2, "Pengguna Dua", "5678")
        self.assertTrue(ok1 and ok2)
        self.created_vouchers = []

    def tearDown(self):
        conn = sqlite3.connect(db_history.DB_PATH)
        cur = conn.cursor()
        for uid in (self.uid1, self.uid2):
            for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "payment_orders", "users"):
                cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (uid,))
        for code in self.created_vouchers:
            cur.execute("DELETE FROM pro_vouchers WHERE code = ?", (code,))
        conn.commit()
        conn.close()

    def test_01_pro_tier_priority_stacking_and_unlimited_scan_quota(self):
        # Awalnya user gratis terdaftar mendapat 5 scan (Open Beta tetap backward-compatible)
        st_free = db_history.get_user_scan_status(self.uid1, tz_offset=8)
        self.assertFalse(st_free["is_pro"])
        self.assertTrue(st_free["is_beta"])
        self.assertEqual(st_free["max_scans"], 5)

        for _ in range(5):
            db_history.record_scan_usage(self.uid1, tz_offset=8)
        self.assertFalse(db_history.get_user_scan_status(self.uid1, tz_offset=8)["can_scan"])

        # Aktifkan Pro 30 hari -> kuota langsung unlimited walaupun sudah 5 scan hari ini!
        db_history.activate_pro_tier(self.uid1, days=30)
        st_pro1 = db_history.get_user_scan_status(self.uid1, tz_offset=8)
        self.assertTrue(st_pro1["is_pro"])
        self.assertEqual(st_pro1["tier"], "pro")
        self.assertEqual(st_pro1["max_scans"], 999999)
        self.assertTrue(st_pro1["can_scan"])
        self.assertGreaterEqual(st_pro1["days_left"], 29)

        # Perpanjang lagi 30 hari -> stacking menjadi ~60 hari (tidak hangus)
        db_history.activate_pro_tier(self.uid1, days=30)
        st_pro2 = db_history.get_user_scan_status(self.uid1, tz_offset=8)
        self.assertGreaterEqual(st_pro2["days_left"], 59)

    def test_02_voucher_create_redeem_idempotency_and_guest_block(self):
        v = db_history.create_pro_voucher(days=7, plan_code="PRO_7D", max_uses=1, note="Unit Test")
        self.created_vouchers.append(v["code"])
        self.assertTrue(v["code"].startswith("NCPRO-"))

        # Tamu ditolak menukar voucher
        ok_g, msg_g = db_history.redeem_pro_voucher("guest_abcdef123456", v["code"])
        self.assertFalse(ok_g)
        self.assertIn("akun", msg_g.lower())

        # User 1 menukar voucher (case-insensitive) -> berhasil & Pro aktif 7 hari
        ok_u1, res_u1 = db_history.redeem_pro_voucher(self.uid1, v["code"].lower())
        self.assertTrue(ok_u1, f"Redeem gagal: {res_u1}")
        self.assertEqual(res_u1["days"], 7)
        self.assertTrue(db_history.get_user_scan_status(self.uid1)["is_pro"])

        # User 1 coba tukar lagi -> ditolak
        ok_dup, _ = db_history.redeem_pro_voucher(self.uid1, v["code"])
        self.assertFalse(ok_dup)

        # User 2 coba tukar voucher max_uses=1 -> ditolak
        ok_u2, msg_u2 = db_history.redeem_pro_voucher(self.uid2, v["code"])
        self.assertFalse(ok_u2)
        self.assertIn("habis", msg_u2.lower())

    def test_03_midtrans_sha512_and_mayar_webhooks_idempotent_and_fail_closed(self):
        # 1. Midtrans Snap checkout (mocked) + SHA-512 webhook verification
        fake_snap_resp = MagicMock()
        fake_snap_resp.json.return_value = {
            "token": "snap-tok-123",
            "redirect_url": "https://app.sandbox.midtrans.com/snap/v2/vtweb/snap-tok-123",
        }
        fake_snap_resp.raise_for_status.return_value = None

        with patch.dict(os.environ, {"MIDTRANS_SERVER_KEY": "SB-Mid-server-TESTKEY", "MIDTRANS_IS_SANDBOX": "true"}, clear=False):
            with patch("payment_gateway.requests.post", return_value=fake_snap_resp):
                ok_chk, ord_m = payment_gateway.create_qris_checkout(self.uid1, "Pengguna Satu", "PRO_30D")
            self.assertTrue(ok_chk, f"Checkout Midtrans gagal: {ord_m}")
            self.assertIn("midtrans.com", ord_m["payment_url"])
            self.assertEqual(ord_m["amount_idr"], 19000)

            oid = ord_m["order_id"]
            # Signature salah -> 401
            ok_bad, code_bad, _ = payment_gateway.process_midtrans_notification({
                "order_id": oid,
                "status_code": "200",
                "gross_amount": "19000.00",
                "signature_key": "palsu",
                "transaction_status": "settlement",
            })
            self.assertFalse(ok_bad)
            self.assertEqual(code_bad, 401)

            # Underpayment dengan signature sah -> ditolak 400
            bad_gross = "1000.00"
            sig_under = hashlib.sha512(f"{oid}200{bad_gross}SB-Mid-server-TESTKEY".encode()).hexdigest()
            ok_u, code_u, _ = payment_gateway.process_midtrans_notification({
                "order_id": oid,
                "status_code": "200",
                "gross_amount": bad_gross,
                "signature_key": sig_under,
                "transaction_status": "settlement",
            })
            self.assertFalse(ok_u)
            self.assertEqual(code_u, 400)

            # Settlement sah -> aktifkan Pro 30 hari
            gross = "19000.00"
            sig_ok = hashlib.sha512(f"{oid}200{gross}SB-Mid-server-TESTKEY".encode()).hexdigest()
            payload_ok = {
                "order_id": oid,
                "status_code": "200",
                "gross_amount": gross,
                "signature_key": sig_ok,
                "transaction_status": "settlement",
                "fraud_status": "accept",
                "transaction_id": "mid-tx-999",
            }
            ok1, c1, _ = payment_gateway.process_midtrans_notification(payload_ok)
            self.assertTrue(ok1)
            self.assertEqual(c1, 200)
            exp_first = db_history.get_user_scan_status(self.uid1)["pro_until"]
            self.assertTrue(db_history.get_user_scan_status(self.uid1)["is_pro"])

            # Webhook dikirim ulang (duplikat) -> idempoten, pro_until tidak bertambah ganda!
            ok2, c2, _ = payment_gateway.process_midtrans_notification(payload_ok)
            self.assertTrue(ok2)
            self.assertEqual(c2, 200)
            self.assertEqual(db_history.get_user_scan_status(self.uid1)["pro_until"], exp_first)

        # 2. Mayar webhook fail-closed & happy path
        ord_my = db_history.create_payment_order(self.uid2, "PRO_7D", 9000, 7, provider="mayar_api")
        with patch.dict(os.environ, {"MAYAR_WEBHOOK_TOKEN": ""}, clear=False):
            ok_nc, code_nc, _ = payment_gateway.process_mayar_webhook({"event": "payment.received"}, "any")
            self.assertFalse(ok_nc)
            self.assertEqual(code_nc, 503)

        with patch.dict(os.environ, {"MAYAR_WEBHOOK_TOKEN": "tok-rahasia-mayar"}, clear=False):
            ok_w1, c_w1, _ = payment_gateway.process_mayar_webhook({"event": "payment.received"}, "salah")
            self.assertFalse(ok_w1)
            self.assertEqual(c_w1, 401)

            ok_w2, c_w2, _ = payment_gateway.process_mayar_webhook(
                {
                    "event": "payment.received",
                    "data": {
                        "id": "myr-tx-777",
                        "amount": 9000,
                        "description": f"Nutrisi Cerdas Pass Pro 7 Hari | {ord_my['order_id']}",
                    },
                },
                supplied_token="tok-rahasia-mayar",
            )
            self.assertTrue(ok_w2)
            self.assertEqual(c_w2, 200)
            self.assertTrue(db_history.get_user_scan_status(self.uid2)["is_pro"])

    def test_04_growth_metrics_and_apptest_pro_popover_voucher_redeem(self):
        from streamlit.testing.v1 import AppTest

        v = db_history.create_pro_voucher(days=30, plan_code="PRO_30D", max_uses=1, note="AppTest UI")
        self.created_vouchers.append(v["code"])
        tok = db_history.create_session_token(self.uid1)

        app_path = os.path.join(ROOT_DIR, "app.py")
        at = AppTest.from_file(app_path, default_timeout=30)
        at.query_params["u"] = self.uid1
        at.query_params["s"] = tok
        at.run()
        self.assertEqual(len(at.exception), 0, f"Boot crash: {at.exception}")

        # Tukar kode voucher Pro langsung dari UI popover
        at.text_input(key="pro_voucher_in").set_value(v["code"]).run()
        at.button(key="btn_redeem_voucher").click().run()
        self.assertEqual(len(at.exception), 0, f"Redeem UI crash: {at.exception}")

        self.assertTrue(db_history.get_user_scan_status(self.uid1)["is_pro"])
        all_md = "\n".join(m.value for m in at.markdown)
        self.assertIn("Pro · Sisa", all_md)

        # Cek ringkasan growth metrics Admin mencakup pengguna terdaftar & Pro aktif
        gm = db_history.get_growth_metrics_summary()
        self.assertGreaterEqual(gm["total_registered_users"], 2)
        self.assertGreaterEqual(gm["active_pro_users"], 1)
        self.assertEqual(gm["target_users"], 100)


if __name__ == "__main__":
    unittest.main()
