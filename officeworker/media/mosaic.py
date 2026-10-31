"""動画・画像の自動モザイク（追従つき）。
NudeNet の censor（1枚ずつ塗る）を土台に、動画向けに次を足した:
  1パス目: 全フレーム（step 毎）を検出 → IoU でつないで「トラック」にする
  2パス目: トラックの途切れ（検出漏れ）を前後の位置から補間、出入りの前後も pad フレーム延長してから塗る
  レポート: 補間した区間・長い途切れ・低スコア区間を「要確認区間」として CSV と静止画で出す → 人はそこだけ見ればよい
"""
import csv
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import ff


@dataclass
class Opts:
    style: str = "pixelate"      # pixelate / blur / black / stamp
    block: int = 0               # モザイクの1マス(px)。0 なら長辺/80（日本の慣習の目安 = 長辺/100 以上）
    margin: float = 0.15         # 検出枠を上下左右に広げる割合
    step: int = 1                # 何フレームおきに検出するか（2 で約半分の時間）
    max_gap: float = 1.0         # この秒数までの検出途切れは補間して塗り続ける
    pad: float = 0.25            # トラックの出現前・消失後も塗る秒数
    iou: float = 0.1             # 同じ対象とみなす重なり
    low_score: float = 0.45      # これ未満のスコアだけで続いた区間は要確認
    stamp: str = ""              # style=stamp の画像
    crf: int = 18


@dataclass
class Track:
    frames: dict = field(default_factory=dict)   # frame -> (x1,y1,x2,y2,score)
    label: str = ""

    def last(self):
        f = max(self.frames)
        return f, self.frames[f]


def _iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _near(a, b, w):
    """重なりが無くても、中心が枠の大きさ程度の距離なら同じ対象（速い動き対策）"""
    ca, cb = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    size = max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1], w / 50)
    return math.dist(ca, cb) < size


def link(dets: dict, max_gap_frames: int, iou=0.1, width=1920):
    """フレームごとの検出 {f: [(x1,y1,x2,y2,label,score)]} → トラック"""
    tracks: list[Track] = []
    for f in sorted(dets):
        open_tracks = [t for t in tracks if f - t.last()[0] <= max_gap_frames]
        used = set()
        for d in sorted(dets[f], key=lambda d: -d[5]):
            box = d[:4]
            best = max(((t, _iou(t.last()[1], box)) for t in open_tracks if id(t) not in used and t.label == d[4]),
                       key=lambda x: x[1], default=(None, 0))
            t = best[0] if best[1] >= iou else next(
                (t for t in open_tracks if id(t) not in used and t.label == d[4] and _near(t.last()[1], box, width)), None)
            if t is None:
                t = Track(label=d[4])
                tracks.append(t)
            t.frames[f] = (*box, d[5])
            used.add(id(t))
    return tracks


def boxes_by_frame(tracks, total, pad_frames, max_gap_frames, step=1, low_score=0.45):
    """補間・延長後に各フレームで塗る箱と、要確認区間を返す"""
    paint = {}
    review = []  # (start_f, end_f, reason)
    for t in tracks:
        fs = sorted(t.frames)
        for a, b in zip(fs, fs[1:]):
            gap = b - a
            for f in range(a, b + 1):
                r = (f - a) / gap if gap else 0
                box = tuple(t.frames[a][i] * (1 - r) + t.frames[b][i] * r for i in range(4))
                paint.setdefault(f, []).append(box)
            if gap > step * 2:
                review.append((a, b, f"検出が{gap}フレーム途切れ→補間で塗った（{t.label}）"))
        for f in range(max(0, fs[0] - pad_frames), fs[0]):
            paint.setdefault(f, []).append(t.frames[fs[0]][:4])
        for f in range(fs[-1] + 1, min(total, fs[-1] + pad_frames + 1)):
            paint.setdefault(f, []).append(t.frames[fs[-1]][:4])
        if len(fs) == 1:
            paint.setdefault(fs[0], []).append(t.frames[fs[0]][:4])
        if len(fs) <= 2:
            review.append((fs[0], fs[-1], f"一瞬だけ検出（見逃し・誤検出の可能性）（{t.label}）"))
        scores = [t.frames[f][4] for f in fs]
        if scores and max(scores) < low_score:
            review.append((fs[0], fs[-1], f"低スコアのみ（{t.label}）"))
    # 同じラベルのトラック同士の長い空白（補間しない途切れ）＝ 露出の可能性
    by_label = {}
    for t in tracks:
        by_label.setdefault(t.label, []).append((min(t.frames), max(t.frames)))
    for label, spans in by_label.items():
        spans.sort()
        for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
            if 0 < s2 - e1 <= max_gap_frames * 4 and s2 - e1 > max_gap_frames:
                review.append((e1, s2, f"同じ対象が{s2 - e1}フレーム見えていない（塗っていない）（{label}）"))
    return paint, review


def _expand(box, margin, w, h):
    x1, y1, x2, y2 = box[:4]
    mx, my = (x2 - x1) * margin, (y2 - y1) * margin
    return max(0, int(x1 - mx)), max(0, int(y1 - my)), min(w, int(x2 + mx)), min(h, int(y2 + my))


def apply(frame, boxes, o: Opts, stamp_img=None):
    import cv2
    h, w = frame.shape[:2]
    block = o.block or max(4, round(max(w, h) / 80))
    for b in boxes:
        x1, y1, x2, y2 = _expand(b, o.margin, w, h)
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        roi = frame[y1:y2, x1:x2]
        if o.style == "pixelate":
            small = cv2.resize(roi, (max(1, (x2 - x1) // block), max(1, (y2 - y1) // block)), interpolation=cv2.INTER_LINEAR)
            frame[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
        elif o.style == "blur":
            k = max(31, ((x2 - x1) // 3) | 1)
            frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)
        elif o.style == "stamp" and stamp_img is not None:
            s = cv2.resize(stamp_img, (x2 - x1, y2 - y1))
            if s.shape[2] == 4:
                a = s[:, :, 3:4] / 255.0
                frame[y1:y2, x1:x2] = (s[:, :, :3] * a + roi * (1 - a)).astype(np.uint8)
            else:
                frame[y1:y2, x1:x2] = s
        else:
            frame[y1:y2, x1:x2] = 0
    return frame


def detect_video(src, detector, o: Opts, progress=True):
    import cv2
    meta = ff.info(src)
    cap = cv2.VideoCapture(str(src))
    dets, f = {}, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if f % o.step == 0:
            dets[f] = detector.detect(frame)
        if progress and f % 300 == 0:
            print(f"  検出 {f}/{meta['frames']} フレーム", flush=True)
        f += 1
    cap.release()
    meta["frames"] = f
    return dets, meta


def censor_video(src, dst, detector, o: Opts | None = None, review_dir=None):
    """-> {"review": [...], "tracks": n, "frames": n}"""
    import cv2
    o = o or Opts()
    src, dst = Path(src), Path(dst)
    dets, meta = detect_video(src, detector, o)
    fps, total, w, h = meta["fps"], meta["frames"], meta["width"], meta["height"]
    gap, pad = int(o.max_gap * fps), int(o.pad * fps)
    tracks = link(dets, gap, o.iou, w)
    paint, review = boxes_by_frame(tracks, total, pad, gap, o.step, o.low_score)
    stamp_img = cv2.imread(o.stamp, cv2.IMREAD_UNCHANGED) if o.style == "stamp" and o.stamp else None

    dst.parent.mkdir(parents=True, exist_ok=True)
    audio = ff.has_audio(src)
    cmd = [ff.exe(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-"]
    cmd += ["-i", str(src), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k"] if audio else []
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(o.crf), "-pix_fmt", "yuv420p", "-shortest", str(dst)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cap = cv2.VideoCapture(str(src))
    shots = []
    review_frames = {s for s, e, _ in review} | {(s + e) // 2 for s, e, _ in review}
    f = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = apply(frame, paint.get(f, []), o, stamp_img)
            if review_dir and f in review_frames and len(shots) < 60:
                p = Path(review_dir) / f"review_{f / fps:08.2f}s.jpg"
                p.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(p), cv2.resize(frame, (w * 480 // max(h, 1), 480)))
                shots.append(str(p))
            proc.stdin.write(frame.tobytes())
            f += 1
    finally:
        cap.release()
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg の書き出しに失敗しました")
    rows = merge_review(review, fps)
    if review_dir:
        write_review_csv(rows, Path(review_dir) / "要確認区間.csv")
    return {"review": rows, "tracks": len(tracks), "frames": total, "fps": fps, "shots": shots}


def merge_review(review, fps, join=0.5):
    """近い要確認区間はまとめて、秒で返す"""
    rows = []
    for s, e, reason in sorted(review):
        s_t, e_t = s / fps, e / fps
        if rows and s_t - rows[-1]["end"] <= join:
            rows[-1]["end"] = max(rows[-1]["end"], e_t)
            if reason not in rows[-1]["reason"]:
                rows[-1]["reason"] += " / " + reason
        else:
            rows.append({"start": s_t, "end": e_t, "reason": reason})
    return rows


def _ts(t):
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_review_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["開始", "終了", "理由", "確認結果（OK/要修正）"])
        for r in rows:
            w.writerow([_ts(max(0, r["start"] - 0.5)), _ts(r["end"] + 0.5), r["reason"], ""])


def censor_image(src, dst, detector, o: Opts | None = None):
    import cv2
    o = o or Opts()
    img = cv2.imread(str(src))
    boxes = [d[:4] for d in detector.detect(img)]
    cv2.imwrite(str(dst), apply(img, boxes, o))
    return len(boxes)
