"""X 等の集客用ショートを自動で切り出す（auto-editor の「音量で区切る」考え方を応用）。
音量（RMS）の山を探し、前後を切り抜いて縦型 9:16 にする。必ず **モザイク済み** の動画から作ること。"""
import json
from pathlib import Path

import numpy as np

from . import ff


def loudness(src, rate=8000, win=0.5):
    """-> (秒ごとの時刻配列, dB 配列)"""
    import subprocess
    if not ff.has_audio(src):
        return np.array([]), np.array([])
    raw = subprocess.run([ff.exe(), "-hide_banner", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1",
                          "-ar", str(rate), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    n = int(rate * win)
    if len(a) < n:
        return np.array([]), np.array([])
    frames = a[: len(a) // n * n].reshape(-1, n)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)
    k = max(1, int(2 / win))  # 2秒の移動平均で「盛り上がり」をならす
    db = np.convolve(db, np.ones(k) / k, mode="same")
    return np.arange(len(db)) * win + win / 2, db


def pick(times, db, duration, n=3, length=20.0, pre=0.4, edge=3.0):
    """山の時刻を n 個。互いに重ならないように。音が無ければ等間隔"""
    starts = []
    if len(db):
        order = np.argsort(-db)
        for i in order:
            t = float(times[i])
            s = max(0.0, min(duration - length, t - length * pre))
            if t < edge or t > duration - edge:
                continue
            if all(abs(s - x) >= length for x in starts):
                starts.append(s)
            if len(starts) >= n:
                break
    if len(starts) < n and duration > length:  # 足りない分は等間隔で補う
        for k in range(1, n + 1):
            s = duration * k / (n + 1) - length / 2
            s = max(0.0, min(duration - length, s))
            if all(abs(s - x) >= length for x in starts):
                starts.append(s)
            if len(starts) >= n:
                break
    return sorted(starts)


VERTICAL = {
    # 背景をぼかした縦長（元の画を切らない。誤ってモザイク外を写さない安全側）
    "blur": "[0:v]split=2[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2[bg2];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fg2];[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1[v]",
    "crop": "[0:v]crop=ih*9/16:ih,scale=1080:1920,setsar=1[v]",
    "none": "[0:v]null[v]",
}


def make(src, out_dir, n=3, length=20.0, mode="blur", prefix="clip"):
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = ff.info(src)
    duration = meta["duration"] or (meta["frames"] / meta["fps"] if meta["frames"] else 0)
    times, db = loudness(src)
    starts = pick(times, db, duration, n, min(length, duration))
    audio = ff.has_audio(src)
    out = []
    for i, s in enumerate(starts, 1):
        dst = out_dir / f"{prefix}_{i:02d}_{int(s // 60):02d}m{int(s % 60):02d}s.mp4"
        args = ["-ss", f"{s:.2f}", "-t", f"{min(length, duration):.2f}", "-i", str(src),
                "-filter_complex", VERTICAL[mode], "-map", "[v]"]
        args += ["-map", "0:a", "-c:a", "aac", "-b:a", "160k"] if audio else []
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
        ff.run(args)
        out.append({"file": str(dst), "start": round(s, 2), "length": round(min(length, duration), 2)})
    (out_dir / f"{prefix}_clips.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
