import http.server
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app_health_checker as hc


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code = 500 if self.path == "/fail" else 200
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


class HealthCheckerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_up_and_down(self):
        exp = hc.parse_expected("200-399")
        self.assertEqual(hc.check(self.base + "/", exp)["status"], "UP")
        r = hc.check(self.base + "/fail", exp)
        self.assertEqual((r["status"], r["code"]), ("DOWN", 500))

    def test_connection_error(self):
        r = hc.check("http://127.0.0.1:1/", {200}, timeout=1)
        self.assertEqual(r["status"], "DOWN")
        self.assertIsNone(r["code"])

    def test_exit_codes(self):
        self.assertEqual(hc.main([self.base + "/", "--json"]), 0)
        self.assertEqual(hc.main([self.base + "/", self.base + "/fail", "--json"]), 1)
        self.assertEqual(hc.main([self.base + "/fail", "--expected", "500"]), 0)

    def test_interval_uptime(self):
        self.assertEqual(hc.main([self.base + "/", "--interval", "0.01", "--count", "3"]), 0)


if __name__ == "__main__":
    unittest.main()
