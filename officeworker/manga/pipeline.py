"""同人誌・漫画の翻訳写植パイプライン。
流れは manga-image-translator / BallonsTranslator と同じ「検出 → OCR → 文字消し → 翻訳 → 写植」。
違いは、翻訳結果を script.json（＋編集用CSV）に残し、人が直した台本から元画像を使って何度でも描き直せること。"""
import csv
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .. import llm
from ..media import ff

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
LANGS = {"en": "English", "zh-Hans": "Simplified Chinese", "zh-Hant": "Traditional Chinese", "ko": "Korean"}
FONT_CANDIDATES = {  # 先にあるものを使う。assets/fonts に置けば最優先
    "en": ["assets/fonts/ComicNeue-Bold.ttf", "C:/Windows/Fonts/comicbd.ttf", "C:/Windows/Fonts/comic.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    "zh-Hans": ["assets/fonts/NotoSansSC-Bold.ttf", "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"],
    "zh-Hant": ["assets/fonts/NotoSansTC-Bold.ttf", "C:/Windows/Fonts/msjhbd.ttc", "C:/Windows/Fonts/msjh.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"],
    "ko": ["assets/fonts/NotoSansKR-Bold.ttf", "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"],
}


# ---------------- 検出 ----------------
def detect_bubbles(img_bgr, min_area=0.002, max_area=0.2):
    """白い吹き出し（内側に文字の黒画素があるもの）を探す。-> [{"box": [x1,y1,x2,y2], "contour": [[x,y],...]}]"""
    import cv2
    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # 紙の白さに合わせる（スキャンで黄ばんだ・グレーがかった原稿でも吹き出しを拾う）
    paper = float(np.percentile(gray, 95))
    _, white = cv2.threshold(gray, max(150, min(215, paper - 25)), 255, cv2.THRESH_BINARY)
    # 文字で白領域が分断されないよう軽く閉じる（線の太さ程度）
    k = max(3, min(h, w) // 200) | 1
    closed = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (min_area * w * h <= area <= max_area * w * h):
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < 20 or bh < 20 or max(bw / bh, bh / bw) > 6:
            continue
        hull = cv2.convexHull(c)
        if area / max(cv2.contourArea(hull), 1) < 0.75:  # 吹き出しはほぼ凸
            continue
        mask = np.zeros((h, w), np.uint8)
        cv2.drawContours(mask, [c], -1, 255, -1)
        inner = cv2.erode(mask, np.ones((5, 5), np.uint8), iterations=2)
        dark = ((gray < 120) & (inner > 0)).sum() / max((inner > 0).sum(), 1)
        if not 0.01 <= dark <= 0.45:  # 文字が入っていそうなものだけ
            continue
        out.append({"box": [int(x), int(y), int(x + bw), int(y + bh)], "contour": c.reshape(-1, 2).tolist()})
    return sort_reading_order(out, h)


def sort_reading_order(regions, page_h):
    """日本の漫画: 上の段から、同じ段の中は右から左"""
    band = max(page_h // 8, 1)
    return sorted(regions, key=lambda r: ((r["box"][1] + r["box"][3]) // 2 // band, -(r["box"][0] + r["box"][2])))


# ---------------- OCR ----------------
_mocr = None


def ocr(img_pil, regions, engine="auto"):
    """各領域の日本語を読む。auto: manga-ocr があれば使い、無ければ LLM（画像入力）"""
    global _mocr
    crops = [img_pil.crop(tuple(r["box"])) for r in regions]
    if engine in ("auto", "manga_ocr"):
        try:
            from manga_ocr import MangaOcr
            _mocr = _mocr or MangaOcr()
            return [_mocr(c) for c in crops]
        except ImportError:
            if engine == "manga_ocr":
                raise
    if not crops:
        return []
    res = llm.ask(f"{len(crops)}枚の画像は漫画の吹き出しの切り抜きです。順番どおりに日本語のセリフを書き起こし、"
                  f'JSON {{"lines": ["1枚目", ...]}} で返してください。縦書きは上から下・右から左に読む。文字が無ければ空文字。',
                  json_mode=True, temperature=0, images=crops, task="ocr")
    lines = res.get("lines") if isinstance(res, dict) else res
    if not isinstance(lines, list) or len(lines) != len(crops):
        raise RuntimeError("OCR できません（manga-ocr を入れるか、GEMINI_API_KEY/OPENROUTER_API_KEY を設定）")
    return [str(x) for x in lines]


# ---------------- 翻訳 ----------------
def load_glossary(path):
    p = Path(path) if path else None
    if not p or not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def translate(lines, lang="en", glossary=(), context="", style=""):
    """[(id, ja)] -> {id: 訳}。キー無しなら原文のまま（後で台本を直して render）"""
    if not lines:
        return {}
    gl = "\n".join(f"- {g.get('ja')} → {g.get(lang) or g.get('en')}" + (f"（{g['note']}）" if g.get("note") else "")
                   for g in glossary if g.get("ja"))
    prompt = f"""You are a professional manga localizer. Translate these Japanese speech-bubble lines into natural {LANGS.get(lang, lang)}.
- Keep each line short enough for a speech bubble; match each character's voice and the scene's tone.
- Translate sound effects / moans / interjections into natural equivalents used in {LANGS.get(lang, lang)} comics.
- Use the glossary exactly for names and terms. Keep honorifics only if the glossary says so.
{('Style: ' + style) if style else ''}
Glossary:
{gl or '(none)'}
Previous page context (do not translate, for continuity):
{context or '(none)'}

Lines (id: text):
""" + "\n".join(f"{i}: {t}" for i, t in lines) + '\n\nReturn JSON only: {"<id>": "<translation>", ...}'
    res = llm.ask(prompt, json_mode=True, temperature=0.3, task="translate")
    if not isinstance(res, dict):
        if llm.provider("translate"):
            print("  ⚠ 翻訳できませんでした（原文のまま台本に残します）。安全フィルタで止まる作品は .env に "
                  "LLM_PROVIDER_TRANSLATE=openrouter と OPENROUTER_MODEL_TRANSLATE を設定して再実行")
        return {i: t for i, t in lines}
    return {i: str(res.get(str(i), res.get(i, t))) for i, t in lines}


# ---------------- 文字消し ----------------
def clean(img_bgr, region):
    """吹き出し内の文字を消す。背景がほぼ白なら内側を白で塗り、それ以外は周囲から補完（OpenCV inpaint）"""
    import cv2
    h, w = img_bgr.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    cv2.drawContours(mask, [np.array(region["contour"], np.int32)], -1, 255, -1)
    inner = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=3)  # 吹き出しの枠線は残す
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    light = min(225, float(np.percentile(gray, 95)) - 15)
    if np.median(gray[inner > 0]) > light:
        # 吹き出しの地の色（紙の色）で塗る。真っ白で塗るとスキャン原稿で白く浮く
        bright = (inner > 0) & (gray > light)
        img_bgr[inner > 0] = np.median(img_bgr[bright], axis=0).astype(np.uint8) if bright.any() else 255
    else:
        text = cv2.dilate(((gray < 140) & (inner > 0)).astype(np.uint8) * 255, np.ones((3, 3), np.uint8), iterations=2)
        img_bgr[:] = cv2.inpaint(img_bgr, text, 5, cv2.INPAINT_TELEA)
    return img_bgr


# ---------------- 写植 ----------------
ROOT = Path(__file__).resolve().parents[2]


def font_path(lang, override=None):
    for p in ([override] if override else []) + FONT_CANDIDATES.get(lang, FONT_CANDIDATES["en"]):
        if not p:
            continue
        q = Path(p) if Path(p).is_absolute() or p.startswith("C:/") else ROOT / p
        if q.exists():
            return str(q)
    raise FileNotFoundError(f"{lang} 用のフォントがありません。assets/fonts に置くか --font で指定してください")


def _wrap(text, font, width, lang):
    if lang == "en" or lang == "ko":
        words, lines, cur = text.split(), [], ""
        for wd in words:
            cand = f"{cur} {wd}".strip()
            if font.getlength(cand) <= width or not cur:
                cur = cand
            else:
                lines.append(cur); cur = wd
        return lines + ([cur] if cur else [])
    lines, cur = [], ""
    for ch in text:  # 中国語は文字単位で折り返し。句読点を行頭にしない
        if font.getlength(cur + ch) <= width or not cur or ch in "，。！？、…」』）":
            cur += ch
        else:
            lines.append(cur); cur = ch
    return lines + ([cur] if cur else [])


def fit_text(text, box, lang, fpath, max_size=64, min_size=9, line_gap=1.12):
    x1, y1, x2, y2 = box
    # 楕円の吹き出しに収まるよう、外接矩形の約 72% を使う
    bw, bh = (x2 - x1) * 0.72, (y2 - y1) * 0.72
    best = None
    hang = "，。！？、…」』）!?,."
    for size in range(max_size, min_size - 1, -1):  # 大きい方から。折り返しで当てはまり方が単調でないため二分探索しない
        font = ImageFont.truetype(fpath, size)
        lines = _wrap(text, font, bw, lang)
        height = len(lines) * size * line_gap
        widest = max((font.getlength(l.rstrip(hang)) for l in lines), default=0)  # ぶら下げ句読点は幅に数えない
        if height <= bh and widest <= bw * 1.04:
            best = (font, lines, size)
            break
    if best is None:  # 入りきらない → 最小サイズで描き、台本に「要調整」を付ける
        font = ImageFont.truetype(fpath, min_size)
        best = (font, _wrap(text, font, bw, lang), min_size)
    return best


def typeset(img_pil, region, text, lang, fpath, stroke=2):
    # 写植はページ内で文字の大きさをそろえる（短いセリフだけ巨大にしない）
    font, lines, size = fit_text(text, region["box"], lang, fpath, max_size=max(14, img_pil.size[0] // 24))
    d = ImageDraw.Draw(img_pil)
    x1, y1, x2, y2 = region["box"]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    total = len(lines) * size * 1.12
    y = cy - total / 2
    for line in lines:
        wl = font.getlength(line)
        d.text((cx - wl / 2, y), line, font=font, fill=(0, 0, 0), stroke_width=stroke, stroke_fill=(255, 255, 255))
        y += size * 1.12
    return size


# ---------------- まとめ ----------------
def pages_in(src):
    src = Path(src)
    files = [src] if src.is_file() else sorted(p for p in src.iterdir() if p.suffix.lower() in IMAGE_EXT)
    return sorted(files, key=lambda p: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.name)])


def build_script(src, lang="en", ocr_engine="auto", glossary_path=None, style="", limit=None):
    """検出・OCR・翻訳まで（描画しない）→ 台本 dict"""
    import cv2
    glossary = load_glossary(glossary_path)
    script = {"lang": lang, "style": style, "pages": []}
    context = ""
    for page in pages_in(src)[:limit]:
        img = ff.imread(page)
        regions = detect_bubbles(img)
        pil = Image.open(page).convert("RGB")
        texts = ocr(pil, regions, ocr_engine)
        regions = [dict(r, ja=t.strip()) for r, t in zip(regions, texts) if re.search(r"[\w\u3040-\u30ff\u4e00-\u9fff]", t or "")]
        tr = translate([(i + 1, r["ja"]) for i, r in enumerate(regions)], lang, glossary, context, style)
        for i, r in enumerate(regions):
            r["id"], r["tr"] = i + 1, tr.get(i + 1, r["ja"])
        context = "\n".join(r["ja"] for r in regions[-6:])
        script["pages"].append({"file": page.name, "regions": regions})
        print(f"  {page.name}: 吹き出し {len(regions)}個")
    return script


def render(src, script, out, font=None, watermark=""):
    """台本と元画像から訳した画像を作る（何度やっても元画像から作り直す）"""
    import cv2
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    lang = script["lang"]
    fpath = font_path(lang, font)
    srcdir = Path(src) if Path(src).is_dir() else Path(src).parent
    done = []
    for page in script["pages"]:
        img = ff.imread(srcdir / page["file"])
        for r in page["regions"]:
            if r.get("skip"):
                continue
            clean(img, r)
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        for r in page["regions"]:
            if r.get("skip") or not str(r.get("tr", "")).strip():
                continue
            r["font_size"] = typeset(pil, r, str(r["tr"]).strip(), lang, fpath)
        if watermark:
            _watermark(pil, watermark)
        dst = out / (Path(page["file"]).stem + ".png")
        pil.save(dst)
        done.append(dst)
    return done


def _watermark(pil, text):
    d = ImageDraw.Draw(pil)
    w, h = pil.size
    f = ImageFont.truetype(font_path("en"), max(18, w // 18))
    for k in range(-1, 3):
        d.text((w * 0.1, h * (0.15 + k * 0.3)), text, font=f, fill=(255, 0, 0), stroke_width=2, stroke_fill=(255, 255, 255))


def save_script(script, path):
    Path(path).write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    # Excel で直せる CSV も出す（page,id,ja,tr,skip）
    with open(Path(path).with_suffix(".csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["page", "id", "ja", "tr", "skip"])
        for p in script["pages"]:
            for r in p["regions"]:
                w.writerow([p["file"], r["id"], r["ja"], r["tr"], "1" if r.get("skip") else ""])


def load_script(path):
    """script.json を読み、同名 CSV の方が新しければ訳文の修正を取り込む"""
    p = Path(path)
    script = json.loads(p.read_text(encoding="utf-8"))
    c = p.with_suffix(".csv")
    if c.exists() and c.stat().st_mtime > p.stat().st_mtime:
        with open(c, encoding="utf-8-sig", newline="") as f:
            edits = {(r["page"], str(r["id"])): r for r in csv.DictReader(f)}
        for page in script["pages"]:
            for r in page["regions"]:
                e = edits.get((page["file"], str(r["id"])))
                if e:
                    r["tr"], r["skip"] = e["tr"], bool((e.get("skip") or "").strip())
    return script


def to_pdf(images, path):
    imgs = [Image.open(p).convert("RGB") for p in images]
    if imgs:
        imgs[0].save(path, save_all=True, append_images=imgs[1:])
    return path
