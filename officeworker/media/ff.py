"""ffmpeg の場所を解決（PATH → imageio-ffmpeg 同梱版）。Windows でも ffmpeg を別途入れずに動く。"""
import json
import shutil
import subprocess


def exe():
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args, **kw):
    return subprocess.run([exe(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True, **kw)


def has_audio(path):
    r = subprocess.run([exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, errors="replace")
    return "Audio:" in r.stderr


def info(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        return {"fps": fps if fps > 1 else 30.0, "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
    finally:
        cap.release()


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)
