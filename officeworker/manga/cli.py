"""python -m officeworker manga-translate / manga-render"""
from pathlib import Path

import yaml

RIGHTS_TEMPLATE = """# 作品ごとの受付記録。条件を満たさない作品は扱わない
title: ""
author: ""
author_permission: false          # 作者（権利者）から翻訳・海外販売の許諾を得た（契約書・DMの保管場所を notes に）
no_minor_sexual_content: false    # 18歳未満に見える/設定の登場人物の性的描写を含まないことを確認した
revenue_share: ""                 # 例: 作者70% / 当方30%（販売プラットフォーム手数料控除後）
platforms: []                     # 例: dlsite-en / patreon / itch.io
notes: ""
"""


def check_rights(path, sample):
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(RIGHTS_TEMPLATE, encoding="utf-8")
        raise SystemExit(f"受付記録がありません。{p} を作成しました。確認して true にしてから再実行してください")
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if d.get("no_minor_sexual_content") is not True:
        raise SystemExit("no_minor_sexual_content が true ではありません。18歳未満に見える登場人物の性的描写を含む作品は扱いません")
    if not sample and d.get("author_permission") is not True:
        raise SystemExit("author_permission が true ではありません。許諾前は --sample（2ページ・透かし入り、作者への提案用）だけ作れます")
    return d


def add_parsers(sp):
    p = sp.add_parser("manga-translate", help="漫画ページ → 検出・OCR・翻訳・写植（台本 script.json/csv も出力）")
    p.add_argument("src", help="ページ画像のフォルダ（ファイル名の番号順）")
    p.add_argument("-o", "--out", default="out/manga")
    p.add_argument("--lang", default="en", choices=["en", "zh-Hans", "zh-Hant", "ko"])
    p.add_argument("--ocr", default="auto", choices=["auto", "manga_ocr", "llm"])
    p.add_argument("--glossary", default="", help="用語集CSV（ja,en,zh-Hans,zh-Hant,ko,note）")
    p.add_argument("--style", default="", help="訳の方針（例: casual, keep honorifics）")
    p.add_argument("--font", default="")
    p.add_argument("--rights", default="rights.yaml")
    p.add_argument("--sample", action="store_true", help="作者への提案用: 先頭2ページだけ・SAMPLE 透かし")
    p = sp.add_parser("manga-render", help="直した台本（script.json か同名CSV）から描き直す")
    p.add_argument("src"); p.add_argument("--script", required=True)
    p.add_argument("-o", "--out", default="out/manga"); p.add_argument("--font", default="")
    p.add_argument("--pdf", action="store_true", help="全ページを1つのPDFにも")


def run(a):
    from . import pipeline as pl
    out = Path(a.out)
    if a.cmd == "manga-translate":
        check_rights(a.rights, a.sample)
        script = pl.build_script(a.src, a.lang, a.ocr, a.glossary, a.style, limit=2 if a.sample else None)
        out.mkdir(parents=True, exist_ok=True)
        pl.save_script(script, out / "script.json")
        pages = pl.render(a.src, script, out / "pages", a.font or None, watermark="SAMPLE" if a.sample else "")
        pl.save_script(script, out / "script.json")  # 文字サイズを記録
        small = sum(1 for p in script["pages"] for r in p["regions"] if r.get("font_size", 99) <= 10)
        print(f"\n完了: {out / 'pages'}（{len(pages)}ページ）\n台本: {out / 'script.csv'} を直して manga-render で描き直せます"
              + (f"\n文字が小さい吹き出し {small}個（訳を短くするか手で調整）" if small else ""))
        return pages
    if a.cmd == "manga-render":
        script = pl.load_script(a.script)
        pages = pl.render(a.src, script, out / "pages", a.font or None)
        if a.pdf:
            print(f"PDF: {pl.to_pdf(pages, out / 'translated.pdf')}")
        print(f"完了: {out / 'pages'}（{len(pages)}ページ）")
        return pages
