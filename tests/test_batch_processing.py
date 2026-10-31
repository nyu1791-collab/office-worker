import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from officeworker import io, pdf, recipe, server


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def test_csv_failure_keeps_valid_data_and_logs_error(self):
        (self.root / "good.csv").write_text("金額\n100\n", encoding="utf-8")
        (self.root / "bad.csv").write_text('金額\n"unfinished\n', encoding="utf-8")
        df = io.read_many("*.csv")
        self.assertEqual(df["金額"].tolist(), [100])
        self.assertEqual(df.attrs["failed_files"][0]["file"], str(self.root / "bad.csv"))
        self.assertIn("bad.csv", (self.root / "error.log").read_text(encoding="utf-8"))

    def test_all_failures_raise_instead_of_saving_empty_success(self):
        (self.root / "bad.csv").write_text('a\n"unfinished\n', encoding="utf-8")
        with self.assertRaises(io.BatchReadError) as failure:
            io.read_many("*.csv")
        self.assertEqual(len(failure.exception.failures), 1)

    def test_failed_invoice_is_left_in_input_after_recipe_move(self):
        for name in ("good.pdf", "bad.pdf"):
            (self.root / name).write_bytes(b"placeholder")
        spec = self.root / "recipe.yaml"
        spec.write_text("steps:\n  - invoices: '*.pdf'\n  - save: result.csv\n  - move: {files: '*.pdf', to: archive}\n", encoding="utf-8")

        def extract(path):
            if Path(path).name == "bad.pdf":
                raise ValueError("damaged PDF")
            return {"file": "good.pdf", "total": 12345}

        with patch.object(pdf, "invoice", side_effect=extract):
            df, ctx = recipe.run_full(spec)
        self.assertEqual(len(df), 1)
        self.assertEqual(len(ctx["failed_files"]), 1)
        self.assertTrue((self.root / "bad.pdf").exists())
        self.assertTrue((self.root / "archive" / "good.pdf").exists())
        self.assertFalse((self.root / "good.pdf").exists())

    def test_load_append_keeps_failures_for_move(self):
        (self.root / "first.csv").write_text("amount\n100\n", encoding="utf-8")
        (self.root / "second.csv").write_text("amount\n200\n", encoding="utf-8")
        (self.root / "second-bad.csv").write_text('a\n"unfinished\n', encoding="utf-8")
        spec = self.root / "recipe.yaml"
        spec.write_text("steps:\n  - load: first.csv\n  - load: 'second*.csv'\n  - move: {files: '*.csv', to: archive}\n", encoding="utf-8")
        df, ctx = recipe.run_full(spec)
        self.assertEqual(len(df), 2)
        self.assertEqual(len(ctx["failed_files"]), 1)
        self.assertTrue((self.root / "second-bad.csv").exists())
        self.assertTrue((self.root / "archive" / "first.csv").exists())

    def test_fullwidth_invoice_amount_is_not_truncated(self):
        with patch.object(pdf, "text", return_value="株式会社テスト\n合計 ￥１２，３４５\n請求日 2026年10月1日"), patch.object(pdf.llm, "ask", return_value=None):
            invoice = pdf.invoice("invoice.pdf")
        self.assertEqual(invoice["total"], 12345)
        self.assertEqual(invoice["issue_date"], "2026-10-01")

    def test_blank_pdf_fails_without_calling_llm(self):
        for text in ("", " \n\t "):
            with self.subTest(text=text), patch.object(pdf, "text", return_value=text), patch.object(pdf.llm, "ask") as ask:
                with self.assertRaisesRegex(ValueError, "OCR未対応"):
                    pdf.invoice("scanned.pdf")
                ask.assert_not_called()

    def test_scanned_pdf_remains_in_input_after_recipe(self):
        for name in ("good.pdf", "scanned.pdf"):
            (self.root / name).write_bytes(b"placeholder")
        spec = self.root / "recipe.yaml"
        spec.write_text("steps:\n  - invoices: '*.pdf'\n  - save: result.csv\n  - move: {files: '*.pdf', to: archive}\n", encoding="utf-8")

        def extract_text(path):
            return " \n " if Path(path).name == "scanned.pdf" else "株式会社テスト\n合計 100"

        with patch.object(pdf, "text", side_effect=extract_text), patch.object(pdf.llm, "ask", return_value=None) as ask:
            df, ctx = recipe.run_full(spec)
            self.assertEqual(ask.call_count, 1)
        self.assertEqual(df["total"].tolist(), [100])
        self.assertIn("OCR未対応", ctx["failed_files"][0]["error"])
        self.assertTrue((self.root / "scanned.pdf").exists())
        self.assertTrue((self.root / "archive" / "good.pdf").exists())

    def test_zero_invoice_amounts_remain_zero(self):
        for result in (None, {"subtotal": 0, "tax": 0, "total": 0}):
            with self.subTest(llm_result=result), patch.object(pdf, "text", return_value="株式会社テスト\n小計 0\n消費税 0\n合計 0"), patch.object(pdf.llm, "ask", return_value=result):
                invoice = pdf.invoice("zero.pdf")
            self.assertEqual([invoice[key] for key in ("subtotal", "tax", "total")], [0, 0, 0])
        self.assertEqual(pdf._num(0), 0)

    def test_missing_invoice_total_is_failed_and_stays_in_input(self):
        for name in ("good.pdf", "unknown.pdf"):
            (self.root / name).write_bytes(b"placeholder")
        spec = self.root / "recipe.yaml"
        spec.write_text("steps:\n  - invoices: '*.pdf'\n  - save: result.csv\n  - move: {files: '*.pdf', to: archive}\n", encoding="utf-8")

        def extract_text(path):
            return "株式会社テスト\n合計 100" if Path(path).name == "good.pdf" else "株式会社テスト\n請求額を判別できない文字"

        with patch.object(pdf, "text", side_effect=extract_text), patch.object(pdf.llm, "ask", return_value=None):
            df, ctx = recipe.run_full(spec)
        self.assertEqual(df["total"].tolist(), [100])
        self.assertIn("請求合計金額", ctx["failed_files"][0]["error"])
        self.assertTrue((self.root / "unknown.pdf").exists())
        self.assertTrue((self.root / "archive" / "good.pdf").exists())

    def test_missing_total_in_ai_response_is_not_success(self):
        with patch.object(pdf, "text", return_value="請求書の文字"), patch.object(pdf.llm, "ask", return_value={"issuer": "テスト", "total": "判別不能"}):
            with self.assertRaisesRegex(ValueError, "請求合計金額"):
                pdf.invoice("invoice.pdf")

    def test_fractional_invoice_amounts_are_not_truncated(self):
        with patch.object(pdf, "text", return_value="テスト\n小計 1,000.25\n消費税 100.25\n合計 1,100.50"), patch.object(pdf.llm, "ask", return_value=None):
            result = pdf.invoice("invoice.pdf")
        self.assertEqual([result[key] for key in ("subtotal", "tax", "total")], [1000.25, 100.25, 1100.5])

    def test_fullwidth_csv_amounts_are_included_in_totals(self):
        df = pd.DataFrame({"amount": ["１，２００", "￥３００", "－５０"]})
        result = recipe.STEPS["to_number"](df, ["amount"], {})
        self.assertEqual(result["amount"].tolist(), [1200, 300, -50])
        self.assertEqual(result["amount"].sum(), 1450)

    def test_empty_invoice_input_preserves_previous_output(self):
        output = self.root / "result.csv"
        output.write_text("total\n100\n", encoding="utf-8")
        before = output.read_bytes()
        spec = self.root / "recipe.yaml"
        spec.write_text("steps:\n  - invoices: '*.pdf'\n  - save: result.csv\n", encoding="utf-8")
        with self.assertRaisesRegex(FileNotFoundError, "処理対象"):
            recipe.run_full(spec)
        self.assertEqual(output.read_bytes(), before)

    def test_move_does_not_archive_file_arriving_after_load(self):
        (self.root / "first.csv").write_text("amount\n100\n", encoding="utf-8")
        spec = self.root / "recipe.yaml"
        spec.write_text("steps:\n  - load: '*.csv'\n  - save: result.json\n  - move: {files: '*.csv', to: archive}\n", encoding="utf-8")
        original = io.write_any

        def arrival(df, path, **kwargs):
            result = original(df, path, **kwargs)
            (self.root / "late.csv").write_text("amount\n999\n", encoding="utf-8")
            return result

        with patch.object(io, "write_any", side_effect=arrival):
            df, ctx = recipe.run_full(spec)
        self.assertEqual(df["amount"].tolist(), [100])
        self.assertTrue((self.root / "late.csv").exists())
        self.assertFalse((self.root / "archive" / "late.csv").exists())
        self.assertTrue((self.root / "archive" / "first.csv").exists())

    def test_move_keeps_existing_same_name_archive(self):
        (self.root / "invoice.csv").write_text("amount\n200\n", encoding="utf-8")
        archive = self.root / "archive"
        archive.mkdir()
        previous = archive / "invoice.csv"
        previous.write_text("amount\n100\n", encoding="utf-8")
        before = previous.read_bytes()
        spec = self.root / "recipe.yaml"
        spec.write_text("steps:\n  - load: '*.csv'\n  - move: {files: '*.csv', to: archive}\n", encoding="utf-8")
        recipe.run_full(spec)
        self.assertEqual(previous.read_bytes(), before)
        self.assertEqual((archive / "invoice-2.csv").read_text(encoding="utf-8"), "amount\n200\n")
        self.assertFalse((self.root / "invoice.csv").exists())

    def test_failed_archive_copy_keeps_input(self):
        source = self.root / "invoice.csv"
        source.write_text("amount\n100\n", encoding="utf-8")
        before = source.read_bytes()
        spec = self.root / "recipe.yaml"
        spec.write_text("steps:\n  - load: '*.csv'\n  - move: {files: '*.csv', to: archive}\n", encoding="utf-8")
        with patch.object(recipe.shutil, "copyfileobj", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                recipe.run_full(spec)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(list((self.root / "archive").iterdir()), [])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(server, "ROOT", self.root)
        self.root_patch.start()
        self.auth_patch = patch.dict(os.environ, {"OW_API_TOKEN": "test-token"})
        self.auth_patch.start()
        self.client = TestClient(server.app)
        self.headers = {"x-token": "test-token"}

    def tearDown(self):
        self.client.close()
        self.auth_patch.stop()
        self.root_patch.stop()
        self.temp.cleanup()

    def test_same_filename_files_and_requests_remain_distinct(self):
        upload = lambda: [("file", ("invoice.csv", b"amount\n100\n", "text/csv")),
                          ("file", ("invoice.csv", b"amount\n200\n", "text/csv"))]
        for _ in range(2):
            response = self.client.post("/merge", files=upload(), params={"out": ""}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual([row["amount"] for row in response.json()["data"]], [100, 200])
        self.assertEqual(len(list((self.root / "in" / "api").glob("*/*/invoice.csv"))), 4)

    def test_merge_continues_and_reports_failed_upload(self):
        files = [("file", ("good.csv", b"amount\n100\n", "text/csv")),
                 ("file", ("bad.csv", b'a\n"unfinished\n', "text/csv"))]
        response = self.client.post("/merge", files=files, params={"out": ""}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"], 1)
        self.assertEqual(len(response.json()["failed_files"]), 1)
        self.assertTrue((self.root / "error.log").exists())

    def test_all_bad_uploads_return_failure(self):
        response = self.client.post("/merge", files={"file": ("bad.csv", b'a\n"unfinished\n', "text/csv")}, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(response.json()["detail"]["failed_files"]), 1)

    def test_output_cannot_escape_root(self):
        for path in ("../escaped.csv", str(self.root.parent / "escaped.csv")):
            response = self.client.post("/merge", files={"file": ("a.csv", b"amount\n100\n", "text/csv")}, params={"out": path}, headers=self.headers)
            self.assertEqual(response.status_code, 400)

    def test_api_still_requires_configured_token(self):
        response = self.client.post("/merge", files={"file": ("a.csv", b"amount\n100\n", "text/csv")})
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
