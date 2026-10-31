# 商品: 同人作品の翻訳・写植・海外販売代行

日本語の漫画/CG集を英語・中国語（簡体/繁体）・韓国語に。吹き出し検出 → OCR → 文字消し → AI翻訳 → 写植まで自動、
人は台本（CSV）で訳を直して描き直すだけ。

| 項目 | 内容 |
|---|---|
| 契約 | 作者の初期費用0、海外販売の売上の 30〜40% をいただくレベニューシェア ※要調整 |
| 販売先 | DLsite 英語版 / Patreon / itch.io など（各規約の成人向け作品の扱いを確認） |

## 受付（必須）`rights.yaml`
- `no_minor_sexual_content: true` — **18歳未満に見える/設定の登場人物の性的描写を含む作品は扱わない**
- `author_permission: true` — 作者の許諾（許諾前は `--sample` で2ページ・SAMPLE透かしの提案用だけ）

## 手順
```powershell
.\setup.ps1 -WithManga                # manga-ocr（初回にモデルを自動ダウンロード）
python -m officeworker manga-translate jobs\作品\pages --lang en --glossary jobs\作品\glossary.csv -o jobs\作品\out --rights jobs\作品\rights.yaml
# → out/pages/*.png（訳した画像）、out/script.csv（台本）
#    script.csv の tr 列を直す（skip 列に 1 でその吹き出しを触らない）
python -m officeworker manga-render jobs\作品\pages --script jobs\作品\out\script.json -o jobs\作品\out --pdf
```
- 用語集 `glossary.csv`（列: `ja,en,zh-Hans,zh-Hant,ko,note`）でキャラ名・決め台詞を固定
- 提案用サンプル: `--sample`（先頭2ページ・透かし）→ outreach の `doujin` キャンペーンで作者へ DM 下書き
- 擬音（描き文字）・吹き出しの外の文字は自動では消さない → 手作業か skip

## 仕組みの出典
処理の流れは manga-image-translator（zyddnys）・BallonsTranslator（dmMaze）を参考。OCR は manga-ocr（kha-white, Apache-2.0）
