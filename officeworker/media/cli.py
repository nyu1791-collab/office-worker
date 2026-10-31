"""python -m officeworker mosaic / clips / creator-job"""
import json
from pathlib import Path

from . import intake

VIDEO = (".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm")
IMAGE = (".jpg", ".jpeg", ".png", ".webp")


def add_parsers(sp):
    p = sp.add_parser("mosaic", help="動画/画像に自動モザイク（追従・要確認区間レポート付き）")
    p.add_argument("src", help="ファイルかフォルダ")
    p.add_argument("-o", "--out", default="out/mosaic")
    _common(p)
    p = sp.add_parser("clips", help="モザイク済み動画から縦型ショートを切り出し")
    p.add_argument("src"); p.add_argument("-o", "--out", default="out/clips")
    p.add_argument("-n", type=int, default=3); p.add_argument("--len", type=float, default=20.0)
    p.add_argument("--mode", choices=["blur", "crop", "none"], default="blur")
    p.add_argument("--intake", default="intake.yaml")
    p = sp.add_parser("creator-job", help="案件フォルダ一括: in/ の動画 → モザイク → 切り抜き → 納品フォルダ")
    p.add_argument("job", help="jobs/<案件>（中に in/ と intake.yaml）")
    p.add_argument("-n", type=int, default=3); p.add_argument("--len", type=float, default=20.0)
    p.add_argument("--mode", choices=["blur", "crop", "none"], default="blur")
    _common(p, intake_default=None)


def _common(p, intake_default="intake.yaml"):
    p.add_argument("--detector", default="nudenet", help="nudenet / yolo:モデル.pt / face / nudenet+face")
    p.add_argument("--classes", default="jp", help="jp（性器・肛門）/ jp+breast / カンマ区切りのクラス名")
    p.add_argument("--threshold", type=float, default=0.3)
    p.add_argument("--style", choices=["pixelate", "blur", "black", "stamp"], default="pixelate")
    p.add_argument("--stamp", default="", help="style=stamp の画像(PNG)")
    p.add_argument("--block", type=int, default=0, help="モザイクの1マス(px)。0=長辺/80")
    p.add_argument("--step", type=int, default=1, help="何フレームおきに検出（2で約半分の時間）")
    p.add_argument("--max-gap", type=float, default=1.0, help="この秒数までの検出途切れは補間")
    if intake_default:
        p.add_argument("--intake", default=intake_default)


def _opts(a):
    from .mosaic import Opts
    return Opts(style=a.style, block=a.block, step=a.step, max_gap=a.max_gap, stamp=a.stamp)


def _detector(a):
    from . import detect
    classes = a.classes if a.classes in detect.PRESETS else [c.strip() for c in a.classes.split(",") if c.strip()]
    return detect.build(a.detector, classes, a.threshold)


def run(a):
    if a.cmd == "mosaic":
        intake.check(a.intake)
        return mosaic_paths(Path(a.src), Path(a.out), a)
    if a.cmd == "clips":
        intake.check(a.intake)
        from . import clips
        for c in clips.make(a.src, a.out, a.n, a.len, a.mode, Path(a.src).stem):
            print(f"  {c['file']}  （{c['start']}秒から）")
        return
    if a.cmd == "creator-job":
        return creator_job(Path(a.job), a)


def mosaic_paths(src, out, a, review_root=None):
    from . import mosaic
    det, o = _detector(a), _opts(a)
    files = [src] if src.is_file() else sorted(p for p in src.iterdir() if p.suffix.lower() in VIDEO + IMAGE)
    results = []
    for f in files:
        dst = out / f"{f.stem}_mosaic{f.suffix if f.suffix.lower() in IMAGE else '.mp4'}"
        print(f"▶ {f.name}")
        if f.suffix.lower() in IMAGE:
            n = mosaic.censor_image(f, dst, det, o)
            print(f"  → {dst}（{n}か所）")
            results.append({"src": str(f), "out": str(dst), "boxes": n})
            continue
        review_dir = (review_root or out / "review") / f.stem
        r = mosaic.censor_video(f, dst, det, o, review_dir)
        print(f"  → {dst}  対象{r['tracks']}件 / 要確認区間 {len(r['review'])}件（{review_dir / '要確認区間.csv'}）")
        results.append({"src": str(f), "out": str(dst), "review": r["review"], "review_csv": str(review_dir / "要確認区間.csv")})
    return results


def creator_job(job, a):
    info = intake.check(job / "intake.yaml")
    out = job / "out"
    results = mosaic_paths(job / "in", out / "mosaic", a, review_root=out / "review")
    from . import clips
    for r in results:
        if r["out"].endswith(".mp4"):
            r["clips"] = clips.make(r["out"], out / "clips", a.n, a.len, a.mode, Path(r["src"]).stem)
    (out / "job.json").write_text(json.dumps({"intake": info, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    total_review = sum(len(r.get("review", [])) for r in results)
    print(f"\n完了: {out}\n  要確認区間 合計 {total_review}件 → out/review/*/要確認区間.csv の時刻だけ目視し、"
          f"必要なら編集ソフトで補正して納品")
    return results
