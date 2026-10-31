"""受付チェック。成人確認と同意の記録が無い素材は処理しない（児童の性的画像の取扱い・無断公開を防ぐ最低限の関門）。"""
from pathlib import Path

import yaml

REQUIRED = {
    "performers_all_18_or_over": "出演者全員が18歳以上であることを本人確認書類で確認した",
    "consent_recorded": "出演者全員の撮影・公開への同意を記録した",
    "rights_confirmed": "依頼者が素材の権利者（または権利者の許諾あり）である",
}
TEMPLATE = """# 受付記録（案件ごとに1つ。true にできない項目があれば受けない）
client: ""                      # 依頼者名
work: ""                        # 作品名・ファイル名
performers_all_18_or_over: false   # 出演者全員を身分証で18歳以上と確認
id_checked_on: ""               # 確認日
consent_recorded: false         # 出演者全員の撮影・公開の同意を記録（保管場所を notes に）
rights_confirmed: false         # 依頼者が権利者、または権利者の許諾がある
platforms: []                   # 公開先（myfans / candfans / fantia / x 等）
notes: ""
"""


def check(path):
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(TEMPLATE, encoding="utf-8")
        raise SystemExit(f"受付記録がありません。{p} を作成したので、確認して true にしてから再実行してください")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    missing = [f"- {k}: {msg}" for k, msg in REQUIRED.items() if data.get(k) is not True]
    if missing:
        raise SystemExit("受付記録が未完了のため処理しません:\n" + "\n".join(missing) + f"\n（{p}）")
    return data
