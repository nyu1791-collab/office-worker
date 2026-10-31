"""商品「売上CSV集計」の検収テスト: 同梱サンプル → expected.json と一致すること。"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PRODUCT = Path(__file__).resolve().parents[1] / "products" / "sales-csv-to-excel"
sys.path.insert(0, str(PRODUCT))


class SalesProductAcceptance(unittest.TestCase):
    def run_product(self, indir):
        import run
        out = Path(self.tmp.name) / "out"
        cwd = os.getcwd()
        argv = sys.argv
        sys.argv = ["run.py", "--input", str(indir), "--output", str(out)]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ctx = run.main()
        finally:
            sys.argv = argv
            os.chdir(cwd)
        return ctx, pd.read_excel(ctx["vars"]["file"], sheet_name=None)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.indir = Path(self.tmp.name) / "in"
        shutil.copytree(PRODUCT / "sample" / "in", self.indir)
        self.expected = json.loads((PRODUCT / "sample" / "expected.json").read_text(encoding="utf-8"))

    def test_sample_matches_expected(self):
        ctx, book = self.run_product(self.indir)
        e = self.expected
        self.assertEqual(list(book), e["sheets"])
        self.assertEqual(len(book["明細"]), e["detail_rows"])
        self.assertEqual(book["明細"]["金額"].sum(), e["total"])
        store = {r["店舗"]: [r["売上合計"], r["件数"]] for _, r in book["店舗別"].iterrows()}
        self.assertEqual(store, e["by_store"])
        day = {r["日付"]: [r["売上合計"], r["件数"]] for _, r in book["日別"].iterrows()}
        self.assertEqual(day, e["by_date"])
        cross = book["日別×店舗"].set_index("日付")
        self.assertEqual(cross.loc["合計", "合計"], e["total"])
        self.assertEqual(len(book["要確認"]), e["invalid_rows"])
        self.assertEqual([Path(f).name for f in ctx["skipped_duplicates"]], e["skipped_duplicates"])
        self.assertEqual([Path(f["file"]).name for f in ctx["failed_files"]], e["failed_files"])
        self.assertTrue((self.indir / "スタッフ連絡先.csv").exists())  # 読めないファイルは入力に残す

    def test_same_input_gives_same_result_and_no_stale_sheets(self):
        _, first = self.run_product(self.indir)
        (self.indir / "池袋_202610.csv").write_bytes("売上日,店舗名,商品名,金額\n2026/10/1,池袋,A,900\n".encode("cp932"))
        _, second = self.run_product(self.indir)
        self.assertEqual(len(second["要確認"]), 0)  # 前回の要確認行が残らない
        _, third = self.run_product(self.indir)
        for name in second:
            pd.testing.assert_frame_equal(second[name], third[name])

    def test_legit_repeated_sales_are_not_deduplicated(self):
        _, book = self.run_product(self.indir)
        coffee = book["明細"].query("店舗 == '渋谷' and 商品 == 'コーヒー'")
        self.assertEqual(len(coffee), 2)  # 同じ日・店・商品・金額の2件目も売上


if __name__ == "__main__":
    unittest.main()
