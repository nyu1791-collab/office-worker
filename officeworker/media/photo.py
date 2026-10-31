"""投稿用の写真処理: 向き補正 → 位置情報(EXIF)除去 → 縮小 → 明るさ補正 → 顔隠し → 透かし。"""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps, ImageStat


def prepare(src, max_side=1280, enhance=True, hide_face=False, logo=None, logo_scale=0.18, opacity=0.65,
            position="br", text=None, quality=88) -> bytes:
    img = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
    img = ImageOps.exif_transpose(img).convert("RGB")  # 回転を反映。新しい画像として保存するので EXIF（GPS 等）は残らない
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    if enhance:
        img = auto_enhance(img)
    if hide_face:
        img = hide_faces(img)
    if logo and Path(logo).exists():
        img = put_logo(img, logo, logo_scale, opacity, position)
    elif text:
        img = put_text(img, text, opacity, position)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def auto_enhance(img):
    """暗い店内写真を自然に明るく（白飛びさせない程度に）"""
    lum = ImageStat.Stat(img.convert("L")).mean[0]
    if lum < 115:
        img = ImageEnhance.Brightness(img).enhance(min(1.45, 125 / max(lum, 1)))
    img = ImageOps.autocontrast(img, cutoff=0.5)
    return ImageEnhance.Color(img).enhance(1.06)


def hide_faces(img):
    import cv2
    import numpy as np
    from .detect import Face
    from .mosaic import Opts, apply
    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    boxes = [d[:4] for d in Face().detect(bgr)]
    out = apply(bgr, boxes, Opts(style="pixelate", margin=0.3))
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))


def _pos(img, w, h, position, pad):
    W, H = img.size
    x = pad if "l" in position else W - w - pad
    y = pad if "t" in position else H - h - pad
    return int(x), int(y)


def put_logo(img, logo, scale, opacity, position):
    mark = Image.open(logo).convert("RGBA")
    w = int(img.size[0] * scale)
    mark = mark.resize((w, max(1, int(mark.size[1] * w / mark.size[0]))), Image.LANCZOS)
    alpha = mark.getchannel("A").point(lambda a: int(a * opacity))
    mark.putalpha(alpha)
    base = img.convert("RGBA")
    base.alpha_composite(mark, _pos(base, *mark.size, position, int(img.size[0] * 0.03)))
    return base.convert("RGB")


def put_text(img, text, opacity, position):
    base = img.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    size = max(14, img.size[0] // 28)
    font = None
    for p in ("C:/Windows/Fonts/meiryob.ttc", "C:/Windows/Fonts/meiryo.ttc", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(p).exists():
            font = ImageFont.truetype(p, size)
            break
    font = font or ImageFont.load_default()
    w, h = d.textbbox((0, 0), text, font=font)[2:]
    x, y = _pos(base, w, h, position, int(img.size[0] * 0.03))
    a = int(255 * opacity)
    d.text((x, y), text, font=font, fill=(255, 255, 255, a), stroke_width=2, stroke_fill=(0, 0, 0, a))
    base.alpha_composite(layer)
    return base.convert("RGB")
