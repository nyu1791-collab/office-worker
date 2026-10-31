"""python -m officeworker diary-post / diary-retry / diary-schedule / diary-serve / diary-login"""
from datetime import datetime
from pathlib import Path

from . import core


def add_parsers(sp):
    p = sp.add_parser("diary-post", help="写真＋メモ → 日記文 → 各媒体へ（LINE を使わない手動/テスト用）")
    p.add_argument("--cast", required=True); p.add_argument("--photo", default="")
    p.add_argument("--memo", default=""); p.add_argument("--yes", action="store_true", help="確認なしで投稿")
    p = sp.add_parser("diary-retry", help="失敗した媒体だけ再投稿（結果不明は除く）")
    p.add_argument("job", nargs="?")
    p = sp.add_parser("diary-schedule", help="今日の出勤表（文章＋写真コラージュ）を作って投稿")
    p.add_argument("--date", default=""); p.add_argument("--yes", action="store_true")
    p = sp.add_parser("diary-serve", help="LINE Webhook を起動")
    p.add_argument("--port", type=int, default=8766); p.add_argument("--host", default="127.0.0.1")
    p = sp.add_parser("diary-login", help="browser 投稿する媒体に一度ログインして保存")
    p.add_argument("portal")


def run(a):
    cfg = core.load_config()
    if a.cmd == "diary-post":
        cast = core.find_cast(cfg, cast_id=a.cast)
        if not cast:
            raise SystemExit(f"casts.yaml に {a.cast} がありません")
        job = core.create_job(cfg, cast, Path(a.photo).read_bytes() if a.photo else None, a.memo)
        print(f"【{job['text']['title']}】\n{job['text']['body']}\n\n投稿先: {', '.join(job['deliveries'])}")
        if not a.yes and input("投稿しますか？ y/N: ").strip().lower() != "y":
            print(f"保存のみ: {job['id']}（diary-retry {job['id']} で投稿）")
            return job
        job = core.deliver(cfg, job)
        print(core.summary(job))
        return job
    if a.cmd == "diary-retry":
        # 番号なしでは、本人が OK 済み（approved / partial）のものだけ。未承認の下書きは番号を指定した時だけ投稿
        jobs = [core.load_job(a.job)] if a.job else [j for j in core.all_jobs() if j["status"] in ("partial", "approved")]
        for j in jobs:
            j = core.deliver(cfg, j)
            print(f"{j['id']}\n{core.summary(j)}")
            for n, d in j["deliveries"].items():
                if d["status"] in ("uncertain", "in_progress"):
                    print(f"  {n}: 結果不明。媒体側で確認し、未投稿なら job.json の status を failed に直して再実行")
        return
    if a.cmd == "diary-schedule":
        return schedule(cfg, a.date or datetime.now().strftime("%Y-%m-%d"), a.yes)
    if a.cmd == "diary-serve":
        import uvicorn
        from .line_app import app
        uvicorn.run(app, host=a.host, port=a.port)
    if a.cmd == "diary-login":
        from playwright.sync_api import sync_playwright
        pcfg = cfg.get("portals", {}).get(a.portal, {})
        prof = core.data_dir() / "browser_profile" / a.portal
        prof.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(prof), headless=False)
            (ctx.pages[0] if ctx.pages else ctx.new_page()).goto(pcfg.get("url", "about:blank"))
            input(f"{a.portal} の管理画面にログインしたら Enter: ")
            ctx.close()


def schedule(cfg, date, yes=False):
    """その日のメモから出勤時刻を拾い、出勤表の文章とコラージュ画像を作る"""
    from PIL import Image
    latest = {}
    for j in core.all_jobs():
        if j.get("shift", {}).get("date") == date:
            latest[j["cast"]] = j
    if not latest:
        raise SystemExit(f"{date} の出勤情報がありません（メモに「20時から出勤」等を書くと拾います）")
    rows = sorted(latest.values(), key=lambda j: j["shift"]["start"])
    store = cfg.get("store", {}).get("name", "")
    lines = [f"{date[5:].replace('-', '/')} 本日の出勤情報【{store}】", ""]
    for j in rows:
        c = cfg["casts"].get(j["cast"], {})
        lines.append(f"{c.get('name', j['cast'])}  {j['shift']['start']}〜{j['shift']['end'] or 'LAST'}")
    lines += ["", cfg.get("schedule", {}).get("footer", "ご予約お待ちしております")]
    text = "\n".join(lines)
    # コラージュ（最大12人、3列）
    cell, cols = 360, 3
    photos = [j for j in rows if j.get("photo") and Path(j["photo"]).exists()][:12]
    out_dir = core.jobs_dir().parent / "schedule" / date
    out_dir.mkdir(parents=True, exist_ok=True)
    img_path = None
    if photos:
        from ..media.photo import put_text
        r = (len(photos) + cols - 1) // cols
        canvas = Image.new("RGB", (cell * cols, cell * r + 10), (20, 20, 20))
        for i, j in enumerate(photos):
            im = Image.open(j["photo"]).convert("RGB")
            s = min(im.size)
            im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2)).resize((cell - 6, cell - 6))
            name = cfg["casts"].get(j["cast"], {}).get("name", j["cast"])
            im = put_text(im, f"{name} {j['shift']['start']}〜", 1.0, "bl")
            canvas.paste(im, ((i % cols) * cell + 3, (i // cols) * cell + 3))
        img_path = out_dir / "schedule.jpg"
        canvas.save(img_path, quality=88)
    (out_dir / "schedule.txt").write_text(text, encoding="utf-8")
    print(text + (f"\n画像: {img_path}" if img_path else ""))
    targets = cfg.get("schedule", {}).get("portals", ["folder"])
    if not yes and input("投稿しますか？ y/N: ").strip().lower() != "y":
        return text
    from . import posters
    for name in targets:
        pcfg = cfg.get("portals", {}).get(name, {"method": "folder"})
        try:
            res = posters.post(pcfg.get("method", "folder"), name, pcfg, {"id": "schedule", "name": store},
                               core.for_portal({"title": f"本日の出勤情報 {date}", "body": text}, pcfg, cfg.get("ng_words", [])),
                               str(img_path) if img_path else None, f"schedule_{date}")
            print(f"✓ {name}: {res}")
        except Exception as e:
            print(f"✗ {name}: {e}")
    return text
