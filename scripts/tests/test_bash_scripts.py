import glob
import os
import subprocess
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class HealthMonitorTest(unittest.TestCase):
    @unittest.skipUnless(os.path.exists("/proc/stat"), "needs Linux /proc")
    def test_alert_with_tiny_thresholds(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "logs", "h.log")
            p = subprocess.run([os.path.join(SCRIPTS, "system_health_monitor.sh"), "--once",
                                "--cpu", "0", "--mem", "0", "--disk", "0", "--procs", "1", "--log", log],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertIn("ALERT", p.stdout)
            with open(log) as fh:
                self.assertIn("ALERT process count", fh.read())

    def test_no_alert_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run([os.path.join(SCRIPTS, "system_health_monitor.sh"), "--once",
                                "--cpu", "101", "--mem", "101", "--disk", "101", "--procs", "10000000",
                                "--log", os.path.join(d, "h.log")], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class BackupTest(unittest.TestCase):
    def test_local_backup(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "data"), os.path.join(d, "dest")
            os.makedirs(src)
            with open(os.path.join(src, "f.txt"), "w") as fh:
                fh.write("hello")
            report = os.path.join(d, "r.log")
            cmd = [os.path.join(SCRIPTS, "backup.sh"), "--source", src, "--type", "local",
                   "--dest", dst, "--report", report, "--keep", "2"]
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("status=SUCCESS", p.stdout)
            self.assertEqual(len(glob.glob(os.path.join(dst, "data-*.tar.gz"))), 1)
            self.assertEqual(len(glob.glob(os.path.join(dst, "data-*.tar.gz.sha256"))), 1)
            with open(report) as fh:
                self.assertIn("status=SUCCESS", fh.read())

    def test_dry_run_and_bad_source(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run([os.path.join(SCRIPTS, "backup.sh"), "--source", d, "--type", "local",
                                "--dest", os.path.join(d, "x"), "--dry-run", "--report", os.path.join(d, "r.log")],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0)
            self.assertIn("dry-run", p.stdout)
            self.assertFalse(os.path.exists(os.path.join(d, "x")))
            p = subprocess.run([os.path.join(SCRIPTS, "backup.sh"), "--source", "/nonexistent", "--type", "local", "--dest", d],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
