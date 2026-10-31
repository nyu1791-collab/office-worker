"""事業1（写メ日記）・2（モザイク/切り抜き）・6（翻訳写植）の回帰テスト。外部通信なし。"""
import base64
import contextlib
import hashlib
import hmac
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HAVE = all(importlib.util.find_spec(m) for m in ("cv2", "PIL", "linebot"))


@unittest.skipUnless(HAVE, "requirements-diary.txt が必要")
class DiaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"DIARY_DIR": self.tmp.name, "LINE_CHANNEL_SECRET": "secret",
                                           "LINE_CHANNEL_ACCESS_TOKEN": "", "GEMINI_API_KEY": "", "OPENROUTER_API_KEY": "", "LLM_PROVIDER": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        from officeworker.diary import core
        self.core = core
        core.load_config()
        casts = Path(self.tmp.name) / "casts.yaml"
        casts.write_text(casts.read_text(encoding="utf-8").replace("age_verified: false", "age_verified: true")
                         .replace("photo_consent: false", "photo_consent: true").replace('line_user_id: ""', 'line_user_id: "Ucast"'),
                         encoding="utf-8")
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (800, 600), (60, 50, 70)).save(buf, "JPEG")
        self.photo = buf.getvalue()

    def call(self, *events):
        from fastapi.testclient import TestClient
        from officeworker.diary import line_app
        line_app.SENT.clear()
        body = json.dumps({"destination": "x", "events": list(events)})
        sig = base64.b64encode(hmac.new(b"secret", body.encode(), hashlib.sha256).digest()).decode()
        with patch.object(line_app, "image_bytes", return_value=self.photo), \
                patch.object(line_app.threading, "Thread", side_effect=lambda target, args, daemon: type("T", (), {"start": lambda s: target(*args)})()):
            r = TestClient(line_app.app).post("/callback", content=body, headers={"x-line-signature": sig, "content-type": "application/json"})
        self.assertEqual(r.status_code, 200)
        return list(line_app.SENT)

    def ev(self, user, msg):
        return {"type": "message", "mode": "active", "timestamp": 1, "webhookEventId": "e", "deliveryContext": {"isRedelivery": False},
                "source": {"type": "user", "userId": user}, "replyToken": "rt", "message": msg}

    def test_line_flow_photo_memo_preview_ok_posts_to_outbox(self):
        self.assertIn("Ustranger", self.call(self.ev("Ustranger", {"type": "text", "id": "1", "text": "hi", "quoteToken": "q"}))[0])
        self.assertIn("写真を受け取りました", self.call(self.ev("Ucast", {"type": "image", "id": "2", "quoteToken": "q",
                                                                      "contentProvider": {"type": "line"}}))[0])
        preview = self.call(self.ev("Ucast", {"type": "text", "id": "3", "text": "20時から出勤", "quoteToken": "q"}))[0]
        self.assertIn("OK で投稿", preview)
        sent = self.call(self.ev("Ucast", {"type": "text", "id": "4", "text": "OK", "quoteToken": "q"}))
        self.assertIn("✓ outbox", sent[-1])
        job = self.core.all_jobs()[0]
        self.assertEqual(job["status"], "posted")
        self.assertEqual(job["shift"]["start"], "20:00")
        self.assertTrue(list((Path(self.tmp.name) / "outbox").rglob("photo.jpg")))

    def test_portal_rules_and_shift_parse(self):
        t = self.core.for_portal({"title": "あいうえおかきくけこ", "body": "禁止語を含む。" + "長い文章です。" * 50},
                                 {"max_chars": 60, "title_max": 5, "ng_words": ["禁止語"]}, [])
        self.assertEqual(t["title"], "あいうえお")
        self.assertTrue(t["body"].startswith("○○○を含む。"))
        self.assertLessEqual(len(t["body"]), 60)
        self.assertEqual(self.core.parse_shift("19:30〜24時まで出勤"), ("19:30", "24:00"))
        self.assertIsNone(self.core.parse_shift("今日は雨"))

    def test_retry_without_id_never_posts_unapproved_drafts(self):
        import argparse
        from officeworker.diary import cli
        cfg = self.core.load_config()
        job = self.core.create_job(cfg, self.core.find_cast(cfg, cast_id="sample"), self.photo, "メモ")
        with contextlib.redirect_stdout(io.StringIO()):
            cli.run(argparse.Namespace(cmd="diary-retry", job=None))
        self.assertEqual(self.core.load_job(job["id"])["status"], "draft")
        self.assertFalse(list((Path(self.tmp.name) / "outbox").rglob("本文.txt")))

    def test_unverified_cast_is_refused(self):
        cast = dict(self.core.find_cast(self.core.load_config(), cast_id="sample"), age_verified=False)
        with self.assertRaises(PermissionError):
            self.core.create_job(self.core.load_config(), cast, self.photo, "memo")


@unittest.skipUnless(HAVE, "requirements-media.txt が必要")
class MosaicTests(unittest.TestCase):
    def test_short_gaps_are_interpolated_and_long_gaps_reported(self):
        from officeworker.media import mosaic
        dets = {f: [(f, 10, f + 20, 30, "T", 0.9)] for f in range(0, 100) if not (40 <= f < 50 or 60 <= f < 90)}
        tracks = mosaic.link(dets, max_gap_frames=15)
        paint, review = mosaic.boxes_by_frame(tracks, 120, pad_frames=3, max_gap_frames=15)
        self.assertTrue(all(f in paint for f in range(40, 50)))      # 10フレームの見逃しは補間
        self.assertNotIn(75, paint)                                   # 30フレームは塗らずに
        self.assertTrue(any("見えていない" in r[2] for r in review))   # 要確認へ
        self.assertIn(102, paint)                                     # 消えた後も pad 分は塗る

    def test_clip_picker_prefers_loud_parts_without_overlap(self):
        import numpy as np
        from officeworker.media import clips
        t = np.arange(0, 120, 0.5)
        db = np.full_like(t, -40.0); db[(t > 60) & (t < 62)] = -5
        starts = clips.pick(t, db, 120, n=3, length=20)
        self.assertTrue(any(s <= 61 <= s + 20 for s in starts))
        self.assertTrue(all(b - a >= 20 for a, b in zip(starts, starts[1:])))

    def test_japanese_paths_for_video_and_images(self):
        import numpy as np
        from officeworker.media import ff, mosaic
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "日本語フォルダ" / "動画.mp4"
            src.parent.mkdir()
            ff.run(["-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "1", "-pix_fmt", "yuv420p", str(src)])
            meta = ff.info(src)
            self.assertEqual((meta["width"], meta["height"]), (320, 240))
            self.assertEqual(sum(1 for _ in ff.frames(src, meta)), 10)

            class Box:
                def detect(self, fr): return [(10, 10, 100, 100, "T", 0.9)]
            with contextlib.redirect_stdout(io.StringIO()):
                mosaic.censor_video(src, Path(d) / "出力" / "結果.mp4", Box(), mosaic.Opts())
            self.assertEqual(ff.info(Path(d) / "出力" / "結果.mp4")["width"], 320)
            ff.imwrite(Path(d) / "画像.png", np.zeros((5, 6, 3), np.uint8))
            self.assertEqual(ff.imread(Path(d) / "画像.png").shape, (5, 6, 3))

    def test_intake_is_required(self):
        from officeworker.media import intake
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                intake.check(Path(d) / "intake.yaml")       # 雛形を作って止まる
            with self.assertRaises(SystemExit):
                intake.check(Path(d) / "intake.yaml")       # false のままは処理しない


@unittest.skipUnless(HAVE, "requirements-media.txt が必要")
class MangaTests(unittest.TestCase):
    def test_detect_clean_render_from_edited_csv(self):
        import csv
        import time
        from PIL import Image, ImageDraw
        from officeworker.manga import pipeline as pl
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / "pages").mkdir()
            img = Image.new("RGB", (800, 1000), "white"); dr = ImageDraw.Draw(img)
            dr.rectangle((20, 20, 780, 980), fill=(170, 170, 170), outline="black", width=5)
            for cx in (560, 240):
                dr.ellipse((cx - 110, 200, cx + 110, 560), fill="white", outline="black", width=4)
                for k in range(6):
                    dr.rectangle((cx - 12 + (k % 2) * 30, 260 + k * 40, cx + 6 + (k % 2) * 30, 285 + k * 40), fill="black")
            img.save(d / "pages" / "p1.png")
            with patch.object(pl, "ocr", side_effect=lambda im, regs, eng: ["右のセリフ", "左のセリフ"][:len(regs)]):
                sc = pl.build_script(d / "pages", "en")
            regs = sc["pages"][0]["regions"]
            self.assertEqual([r["ja"] for r in regs], ["右のセリフ", "左のセリフ"])   # 右から読む
            self.assertGreater(regs[0]["box"][0], regs[1]["box"][0])
            pl.save_script(sc, d / "script.json")
            time.sleep(1.1)
            rows = list(csv.DictReader(open(d / "script.csv", encoding="utf-8-sig")))
            rows[0]["tr"], rows[1]["skip"] = "Hello there!", "1"
            with open(d / "script.csv", "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
            sc2 = pl.load_script(d / "script.json")
            self.assertEqual(sc2["pages"][0]["regions"][0]["tr"], "Hello there!")
            self.assertTrue(sc2["pages"][0]["regions"][1]["skip"])
            out = pl.render(d / "pages", sc2, d / "out")
            self.assertTrue(out[0].exists())

    def test_rights_guard(self):
        from officeworker.manga import cli
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rights.yaml"
            with self.assertRaises(SystemExit):
                cli.check_rights(p, sample=True)
            p.write_text("no_minor_sexual_content: true\nauthor_permission: false\n", encoding="utf-8")
            cli.check_rights(p, sample=True)                 # 許諾前でも提案用サンプルは可
            with self.assertRaises(SystemExit):
                cli.check_rights(p, sample=False)


if __name__ == "__main__":
    unittest.main()
