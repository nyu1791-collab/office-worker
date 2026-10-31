"""写メ日記・出勤情報の一括投稿（事業1）の中核。
キャストの写真＋一言メモ → 写真処理 → キャストの文体で日記文 → 媒体ごとの規則（NG語・文字数）に合わせて各媒体へ。
媒体ごとに 成功/失敗/結果不明 を記録し、成功済みの媒体には二度送らない（content-engine の配信記録と同じ考え方）。"""
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import yaml

from .. import llm

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "products" / "shop-diary" / "templates"


def data_dir():
    """既定はリポジトリ直下の diary_data（どのフォルダから起動しても同じ場所）"""
    import os
    p = Path(os.getenv("DIARY_DIR") or ROOT / "diary_data")
    return p if p.is_absolute() else ROOT / p


def load_config():
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name in ("diary.yaml", "casts.yaml"):
        if not (d / name).exists():
            shutil.copy(TEMPLATES / name, d / name)
            print(f"設定の雛形を作成: {d / name}（店舗名・媒体・キャストを書き換えてください）")
    cfg = yaml.safe_load((d / "diary.yaml").read_text(encoding="utf-8")) or {}
    casts = (yaml.safe_load((d / "casts.yaml").read_text(encoding="utf-8")) or {}).get("casts", [])
    cfg["casts"] = {c["id"]: c for c in casts}
    return cfg


def find_cast(cfg, cast_id=None, line_user_id=None):
    for c in cfg["casts"].values():
        if (cast_id and c["id"] == cast_id) or (line_user_id and c.get("line_user_id") == line_user_id):
            return c
    return None


def check_cast(cast):
    """18歳以上の確認と写真掲載の同意が記録されていないキャストは投稿しない"""
    missing = [k for k, msg in (("age_verified", "身分証での18歳以上の確認"), ("photo_consent", "写真掲載の同意"))
               if cast.get(k) is not True]
    if missing:
        raise PermissionError(f"{cast.get('name', cast.get('id'))}: casts.yaml の {', '.join(missing)} が true ではないため投稿できません")


# ---------------- 文章 ----------------
PROMPT = """あなたは「{store}」に在籍する「{name}」本人として、ポータルサイトの写メ日記を書きます。
# 文体・キャラクター
{persona}
# 今日の一言メモ（必ず内容を反映。書かれていない予定・料金・割引は作らない）
{memo}
# 日時
{now}
# ルール
- {min_chars}〜{max_chars}文字。改行を多めに読みやすく、絵文字は文体設定どおり
- 露骨な性的表現・サービス内容の具体的な描写は書かない（各媒体の規約違反になる）
- 次の語は使わない: {ng}
- 最後は来店・指名につながる一言で締める
JSON のみ: {{"title": "20字以内のタイトル", "body": "本文"}}"""


def write_text(cfg, cast, memo, retries=4):
    store = cfg.get("store", {})
    lim = cfg.get("text", {})
    ng = sorted(set(cfg.get("ng_words", [])) | {w for p in cfg.get("portals", {}).values() for w in p.get("ng_words", [])})
    res = llm.ask(PROMPT.format(store=store.get("name", ""), name=cast.get("name", cast["id"]),
                                persona=cast.get("persona", "丁寧で明るい"), memo=memo or "（なし）",
                                now=datetime.now().strftime("%m月%d日 %H時"), min_chars=lim.get("min_chars", 200),
                                max_chars=lim.get("max_chars", 450), ng="、".join(ng) or "（なし）"),
                  json_mode=True, temperature=0.9, task="write", retries=retries)
    if isinstance(res, dict) and len(str(res.get("body", "")).strip()) >= 30:
        return {"title": str(res.get("title") or memo[:20] or "今日の日記").strip(), "body": str(res["body"]).strip()}
    sign = cast.get("signature", "")
    return {"title": (memo or "今日の日記")[:20],
            "body": f"{memo}\n\n今日も{cast.get('name', '')}に会いに来てね♪\nご予約お待ちしてます！" + (f"\n{sign}" if sign else "")}


def for_portal(text, portal_cfg, global_ng):
    """媒体ごと: NG語を伏せ字、文字数上限で文末を整えて切る"""
    title, body = text["title"], text["body"]
    for w in set(global_ng) | set(portal_cfg.get("ng_words", [])):
        if w:
            title, body = title.replace(w, "○" * len(w)), body.replace(w, "○" * len(w))
    mx = portal_cfg.get("max_chars")
    if mx and len(body) > mx:
        cut = body[:mx]
        k = max(cut.rfind(c) for c in "。！？!?♪\n")
        body = cut[:k + 1] if k > mx * 0.6 else cut[:mx - 1] + "…"
    tm = portal_cfg.get("title_max")
    return {"title": title[:tm] if tm else title, "body": body}


SHIFT_RE = re.compile(r"(\d{1,2})(?:[:：時](\d{2})?)\s*(?:分)?\s*(?:から|〜|~|-|ー)\s*(?:(\d{1,2})(?:[:：時](\d{2})?)?\s*(?:分)?\s*(?:まで)?)?")


def parse_shift(memo):
    """「20時から出勤」「19:30〜LAST」→ ("20:00", "") / ("19:30", "")"""
    m = SHIFT_RE.search(memo or "")
    if not m or "出勤" not in memo and "から" not in memo and "〜" not in memo:
        return None
    start = f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    end = f"{int(m.group(3)):02d}:{m.group(4) or '00'}" if m.group(3) else ""
    return start, end


# ---------------- 記録 ----------------
def jobs_dir():
    p = data_dir() / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_job(job):
    d = jobs_dir() / job["id"]
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "job.json")


def load_job(job_id):
    return json.loads((jobs_dir() / job_id / "job.json").read_text(encoding="utf-8"))


def all_jobs():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(jobs_dir().glob("*/job.json"))]


def create_job(cfg, cast, photo_bytes, memo, source="cli", retries=4):
    from ..media import photo
    check_cast(cast)
    job = {"id": datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6], "cast": cast["id"], "memo": memo,
           "source": source, "created": datetime.now().isoformat(timespec="seconds"), "status": "draft",
           "deliveries": {name: {"status": "pending"} for name in cast.get("portals", {}) if name in cfg.get("portals", {})}}
    d = jobs_dir() / job["id"]
    d.mkdir(parents=True, exist_ok=True)
    if photo_bytes:
        im = cfg.get("image", {})
        store = cfg.get("store", {})
        logo = store.get("logo")
        out = photo.prepare(photo_bytes, im.get("max_side", 1280), im.get("auto_enhance", True), cast.get("hide_face", False),
                            str(data_dir() / logo) if logo and not Path(logo).is_absolute() else logo,
                            store.get("logo_scale", 0.18), store.get("watermark_opacity", 0.65),
                            store.get("watermark_position", "br"), store.get("watermark_text"))
        (d / "photo.jpg").write_bytes(out)
        job["photo"] = str(d / "photo.jpg")
    job["text"] = write_text(cfg, cast, memo, retries)
    shift = parse_shift(memo)
    if shift:
        job["shift"] = {"date": datetime.now().strftime("%Y-%m-%d"), "start": shift[0], "end": shift[1]}
    save_job(job)
    return job


def deliver(cfg, job):
    """pending/failed の媒体だけ送る。送る直前に in_progress を保存し、途中停止で二重投稿しない"""
    from . import posters
    cast = cfg["casts"][job["cast"]]
    check_cast(cast)
    job["status"] = "approved"
    for name, dl in job["deliveries"].items():
        if dl["status"] not in ("pending", "failed"):
            continue
        pcfg = {**cfg["portals"].get(name, {}), **(cast.get("portals", {}).get(name) or {})}
        text = for_portal(job["text"], pcfg, cfg.get("ng_words", []))
        dl.update(status="in_progress", at=datetime.now().isoformat(timespec="seconds"))
        dl.pop("error", None)
        save_job(job)
        try:
            dl["result"] = posters.post(pcfg.get("method", "folder"), name, pcfg, cast, text, job.get("photo"), job["id"])
            dl["status"] = "succeeded"
        except posters.Uncertain as e:
            dl.update(status="uncertain", error=str(e))
        except Exception as e:
            dl.update(status="failed", error=str(e)[:300])
        save_job(job)
    if not job["deliveries"]:  # 投稿先が1つも無いのに「投稿済み」にしない
        job["status"] = "no_targets"
        save_job(job)
        return job
    done = all(d["status"] == "succeeded" for d in job["deliveries"].values())
    job["status"] = "posted" if done else "partial"
    save_job(job)
    return job


def summary(job):
    if not job["deliveries"]:
        return "投稿先が未設定です（casts.yaml の portals）"
    marks = {"succeeded": "✓", "failed": "✗", "uncertain": "?", "pending": "…", "in_progress": "…"}
    return "\n".join(f"{marks.get(d['status'], d['status'])} {n}" + (f"（{d.get('error', '')[:60]}）" if d.get("error") else "")
                     for n, d in job["deliveries"].items())
