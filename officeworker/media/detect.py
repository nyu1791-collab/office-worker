"""検出器。どれも detect(frame_bgr) -> [(x1, y1, x2, y2, label, score)] を返す。
- nudenet : NudeNet（notAI-tech/NudeNet）の学習済みモデル。既定は性器・肛門の露出のみ（日本の基準）
- yolo:<path> : ultralytics の自作/配布 YOLO モデル（学習済み .pt / .onnx）
- face    : OpenCV 同梱の顔検出（顔出しNGのキャスト・出演者の顔隠し用）
複数指定は "nudenet+face" のように + でつなぐ。"""
import os

GENITAL = ["FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED"]
PRESETS = {"jp": GENITAL, "jp+breast": GENITAL + ["FEMALE_BREAST_EXPOSED"]}


class NudeNet:
    def __init__(self, classes=None, threshold=0.3):
        from nudenet import NudeDetector
        self.d = NudeDetector()
        self.classes = set(PRESETS.get(classes, classes) if isinstance(classes, str) else (classes or GENITAL))
        self.threshold = threshold

    def detect(self, frame):
        out = []
        for r in self.d.detect(frame):
            if r["class"] in self.classes and r["score"] >= self.threshold:
                x, y, w, h = r["box"]
                out.append((x, y, x + w, y + h, r["class"], float(r["score"])))
        return out


class Yolo:
    def __init__(self, model, classes=None, threshold=0.3):
        from ultralytics import YOLO
        self.m = YOLO(model)
        self.classes = set(classes) if classes else None
        self.threshold = threshold

    def detect(self, frame):
        res = self.m(frame, verbose=False, conf=self.threshold)[0]
        out = []
        for b in res.boxes:
            label = res.names[int(b.cls)]
            if self.classes is None or label in self.classes:
                x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
                out.append((x1, y1, x2, y2, label, float(b.conf)))
        return out


class Face:
    def __init__(self, **_):
        import cv2
        self.c = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))

    def detect(self, frame):
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        m = max(24, min(frame.shape[:2]) // 20)
        return [(x, y, x + w, y + h, "FACE", 1.0) for x, y, w, h in self.c.detectMultiScale(gray, 1.1, 5, minSize=(m, m))]


class Multi:
    def __init__(self, parts):
        self.parts = parts

    def detect(self, frame):
        return [d for p in self.parts for d in p.detect(frame)]


def build(spec="nudenet", classes=None, threshold=0.3):
    parts = []
    for name in spec.split("+"):
        if name == "nudenet":
            parts.append(NudeNet(classes, threshold))
        elif name.startswith("yolo:"):
            parts.append(Yolo(name[5:], classes if isinstance(classes, list) else None, threshold))
        elif name == "face":
            parts.append(Face())
        else:
            raise ValueError(f"不明な検出器: {name}（nudenet / yolo:モデルパス / face）")
    return parts[0] if len(parts) == 1 else Multi(parts)
