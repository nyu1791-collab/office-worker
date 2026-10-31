"""ffmpeg まわりと、Windows でも日本語パスで動く画像/動画の読み書き。
OpenCV の imread / imwrite / VideoCapture は Windows で日本語を含むパスを開けないため、ここを通す。
動画は ffmpeg で 固定フレームレート・回転反映済み の画素列として読む（スマホの縦動画・可変フレームレート対策）。"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

# Tag SDR output as BT.709 so players do not guess (avoids washed-out colours).
BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


def exe():
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args, **kw):
    return subprocess.run([exe(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True, **kw)


def _probe(path):
    r = subprocess.run([exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stderr


def has_audio(path):
    return bool(re.search(r"Stream #\S+.*: Audio:", _probe(path)))


def info(path):
    """-> {fps, frames, width, height, duration}（width/height は回転を反映した表示上の大きさ）"""
    s = _probe(path)
    vid = re.search(r"Stream #\S+.*?: Video: .*?(\d{2,5})x(\d{2,5})", s)
    if not vid:
        raise ValueError(f"動画として読めません: {path}")
    w, h = int(vid.group(1)), int(vid.group(2))
    line = s[vid.start(): s.find("\n", vid.start())]
    fps_m = re.search(r"([\d.]+) fps", line) or re.search(r"([\d.]+) tbr", line)
    fps = float(fps_m.group(1)) if fps_m else 30.0
    if not 1 < fps < 241:
        fps = 30.0
    rot = re.search(r"rotation of (-?[\d.]+) degrees", s) or re.search(r"rotate\s*:\s*(-?\d+)", s)
    if rot and round(abs(float(rot.group(1)))) % 180 == 90:
        w, h = h, w
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", s)
    duration = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    return {"fps": fps, "frames": int(round(duration * fps)), "width": w, "height": h, "duration": duration}


def frames(path, meta=None):
    """BGR の numpy 配列を1枚ずつ返す（固定フレームレート・回転反映済み）"""
    meta = meta or info(path)
    w, h = meta["width"], meta["height"]
    p = subprocess.Popen([exe(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-an", "-sn",
                          "-r", f"{meta['fps']}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         stdout=subprocess.PIPE, bufsize=w * h * 3 * 4)
    size = w * h * 3
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()
    finally:
        p.stdout.close()
        p.kill() if p.poll() is None else None
        p.wait()


def imread(path, flags=None):
    import cv2
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR if flags is None else flags) if data.size else None


def imwrite(path, img, ext=None):
    import cv2
    ext = ext or Path(path).suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f"画像を書き出せません: {path}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    buf.tofile(str(path))
    return path


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)
