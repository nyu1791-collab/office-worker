# 商品: 写メ日記・出勤情報の一括投稿（夜職店舗向け）

キャストが店舗の LINE に「写真」と「一言メモ」を送る → AI がその子の文体で日記にする → 本人が LINE で **OK** → 複数媒体へ一括投稿。
毎日の「出勤表」も、メモの「20時から出勤」から自動で作る。

| 項目 | 内容 |
|---|---|
| 料金の目安 | 初期 5〜10万円（媒体設定・キャスト登録・文体調整）＋ 月 2〜3万円（保守・サーバー）※要調整 |
| デモ | 1週間無料（`outbox` 書き出しだけで動かせる） |
| 必要なもの | 店舗の LINE 公式アカウント（Messaging API）、各媒体の写メ日記メール投稿アドレス、常時起動のPC/サーバー |

## しくみ
| 段階 | 内容 |
|---|---|
| 写真 | 向き補正、**位置情報(EXIF)を削除**、明るさ補正、顔出しNGの子は顔に自動モザイク、店舗ロゴの透かし |
| 文章 | キャストごとの文体（`persona`）、メモの内容だけを使う（書いていない割引・料金を作らない）、露骨な表現なし |
| 媒体ごと | NG語の伏せ字、文字数・タイトル長の上限に合わせて整える |
| 投稿 | メール投稿（公式・最も安定）／ X ／ ブラウザ自動操作（管理画面のみの媒体）／ フォルダ書き出し |
| 記録 | 媒体ごとに 成功・失敗・結果不明 を記録。成功済みには二度送らない。`diary-retry` で失敗分だけ再送 |

## 導入（店舗1件 目安2〜3時間）
1. `setup.ps1 -WithDiary`
2. `python -m officeworker diary-post --cast sample --memo テスト` → `diary_data/diary.yaml` と `casts.yaml` ができる
3. 店舗名・ロゴ・媒体、キャスト（**身分証で18歳以上の確認・掲載の同意を取ってから** `age_verified` / `photo_consent` を true）
4. LINE Developers で Messaging API チャネル → `.env` に `LINE_CHANNEL_SECRET` `LINE_CHANNEL_ACCESS_TOKEN`
5. `python -m officeworker diary-serve` ＋ `cloudflared tunnel --url http://localhost:8766` → 出た https URL + `/callback` を Webhook URL に
6. キャストが LINE を友だち追加 → 何か送ると ID が返る → `casts.yaml` の `line_user_id` に貼る
7. 媒体のメール投稿アドレスを各キャストの `portals` に。SMTP（`.env` の `SMTP_*`）の送信元を媒体に登録

## コマンド
`diary-post --cast ID --photo x.jpg --memo "..."` / `diary-retry [job]` / `diary-schedule [--yes]` / `diary-serve` / `diary-login 媒体名`

## 注意
- 各媒体の利用規約（自動投稿・外部ツール）を確認し、メール投稿など公式の手段を優先する
- 写真・日記は本人の同意の範囲で。退店したキャストは casts.yaml から外す
