import os
import subprocess
import sys
import unittest


class ConsoleTests(unittest.TestCase):
    def test_limited_console_keeps_encoding_and_does_not_abort_processing(self):
        code = (
            "import sys; original = sys.stdout.encoding; "
            "import officeworker; "
            "assert sys.stdout.encoding == original; "
            "print('日本語の処理結果 ▶'); "
            "print('completed')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONIOENCODING": "cp1252:strict"},
            capture_output=True, check=True,
        )
        self.assertIn(b"completed", result.stdout)
        self.assertIn(b"\\u65e5", result.stdout)


if __name__ == "__main__":
    unittest.main()
