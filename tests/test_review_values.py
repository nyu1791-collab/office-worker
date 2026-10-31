"""見直しで直した値の扱い・重複判定・API公開範囲の回帰テスト（外部通信なし）。"""
import contextlib
import io as stdio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from officeworker import io, recipe, server


class ValueParsingTests(unittest.TestCase):
    def test_dates_without_leading_four_digit_year_are_not_guessed(self):
        got = [recipe._parse_date(v) for v in ["26/10/01", "10/1", "01/10/2026", "2026/10/1", "2026-10-01 09:30",
                                               "2026年10月1日", "令和8年10月2日", "20261003", pd.Timestamp("2026-10-04")]]
        self.assertEqual(got, [None, None, None, "2026-10-01", "2026-10-01", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"])

    def test_unicode_minus_and_accounting_negatives(self):
        df = pd.DataFrame({"a": ["−300", "▲300", "△1,000", "(250)", "-５０", "1000円", "", None]})
        out = recipe.STEPS["to_number"](df, ["a"], {})["a"].tolist()
        self.assertEqual(out[:6], [-300, -300, -1000, -250, -50, 1000])
        self.assertTrue(pd.isna(out[6]) and pd.isna(out[7]))


class DuplicateAndLockFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.cwd = os.getcwd()
        os.chdir(self.d)  # error.log をテスト用フォルダへ
        self.addCleanup(os.chdir, self.cwd)

    def read(self):
        with contextlib.redirect_stdout(stdio.StringIO()):
            return io.read_many(str(self.d / "*.csv"), skip_duplicates=True)

    def test_resaved_copy_with_different_bytes_is_still_a_duplicate(self):
        (self.d / "a.csv").write_bytes("日付,店舗,金額\n2026/10/01,渋谷,100\n".encode("utf-8-sig"))
        (self.d / "a (1).csv").write_bytes('"日付","店舗","金額"\r\n"2026/10/01","渋谷","100"\r\n'.encode("cp932"))
        df = self.read()
        self.assertEqual(len(df), 1)
        self.assertEqual([Path(p).name for p in df.attrs["skipped_duplicates"]], ["a (1).csv"])

    def test_same_rows_in_different_stores_are_not_duplicates(self):
        (self.d / "a.csv").write_bytes("日付,店舗,金額\n2026/10/01,渋谷,100\n".encode())
        (self.d / "b.csv").write_bytes("日付,店舗,金額\n2026/10/01,池袋,100\n".encode())
        self.assertEqual(len(self.read()), 2)

    def test_excel_lock_files_are_ignored(self):
        (self.d / "a.csv").write_bytes("x\n1\n".encode())
        (self.d / "~$a.csv").write_bytes(b"\x00\x01")
        df = self.read()
        self.assertEqual(df.attrs["failed_files"], [])


class TextColumnsTests(unittest.TestCase):
    def test_as_text_keeps_leading_zero_codes(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "s.csv"
            f.write_bytes("店舗コード,金額\n001,100\n".encode())
            df = recipe._file_reader({"as_text": True})(f)
            self.assertEqual(df["店舗コード"].tolist(), ["001"])


class ApiExposureTests(unittest.TestCase):
    def test_lan_bind_without_token_is_refused(self):
        with patch.dict(os.environ, {"OW_API_TOKEN": ""}), patch("uvicorn.run") as run:
            with self.assertRaises(SystemExit):
                server.serve("0.0.0.0", 8765)
            run.assert_not_called()
            server.serve("127.0.0.1", 8765)
            run.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class SheetsPushTests(unittest.TestCase):
    def test_replace_never_clears_first_and_sends_safe_values(self):
        from unittest.mock import MagicMock
        from officeworker import sheets
        ws = MagicMock(row_count=2, col_count=2, url="u")
        ws.get_all_values.return_value = [["a", "b"], ["old", "1"], ["old2", "2"], ["old3", "3"]]
        df = pd.DataFrame({"a": ["=IMPORTXML(1)", None], "b": [pd.Timestamp("2026-10-01"), 5]})
        with patch.object(sheets, "_sheet"), patch.object(sheets, "_ws", return_value=ws):
            sheets.push(df, "t")
        ws.clear.assert_not_called()
        ws.resize.assert_called_once_with(rows=4, cols=2)
        grid = ws.update.call_args[0][0]
        self.assertEqual(grid, [["a", "b"], ["'=IMPORTXML(1)", "2026-10-01"], ["", 5], ["", ""]])
        import json
        json.dumps(grid)  # gspread が送れる値だけ
