import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
import log_analyzer

SAMPLE = os.path.join(SCRIPTS, "sample_logs", "access.log")


class LogAnalyzerTest(unittest.TestCase):
    def setUp(self):
        with open(SAMPLE) as fh:
            self.result = log_analyzer.analyze(fh, 5)

    def test_counts(self):
        r = self.result
        self.assertEqual(r["total_requests"], 196)
        self.assertEqual(r["malformed_lines"], 3)
        self.assertEqual(r["unique_ips"], 11)
        self.assertEqual(r["bytes_served"], 3553075)
        self.assertEqual(r["status_codes"], {"200": 151, "302": 13, "404": 21, "500": 11})
        self.assertEqual(r["not_found_count"], 21)
        self.assertEqual(r["top_404_paths"][0], ["/old-page", 9])
        self.assertEqual(sum(r["requests_per_hour"].values()), 196)

    def test_gz_and_stdin_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            gz = os.path.join(d, "a.log.gz")
            with open(SAMPLE, "rb") as src, gzip.open(gz, "wb") as dst:
                dst.write(src.read())
            out = subprocess.run([sys.executable, os.path.join(SCRIPTS, "log_analyzer.py"), gz, "--json"],
                                 capture_output=True, text=True, check=True).stdout
            self.assertEqual(json.loads(out)["total_requests"], 196)
        with open(SAMPLE) as fh:
            out = subprocess.run([sys.executable, os.path.join(SCRIPTS, "log_analyzer.py")],
                                 stdin=fh, capture_output=True, text=True, check=True).stdout
        self.assertIn("Total requests : 196", out)


if __name__ == "__main__":
    unittest.main()
