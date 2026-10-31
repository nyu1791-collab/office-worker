/**
 * Googleフォーム回答 → シート記録 → 自動返信メール ＋ 担当者通知（Slack）
 * 設置: フォームの回答シート > 拡張機能 > Apps Script に貼り付け → トリガー「フォーム送信時」に onFormSubmit
 */
const CONFIG = {
  ADMIN_EMAIL: 'you@example.com',
  SLACK_WEBHOOK: '',            // 空なら通知しない
  EMAIL_COLUMN: 'メールアドレス',
  NAME_COLUMN: 'お名前',
  SUBJECT: 'お問い合わせありがとうございます',
};

function onFormSubmit(e) {
  const v = e.namedValues;
  const name = (v[CONFIG.NAME_COLUMN] || [''])[0];
  const to = (v[CONFIG.EMAIL_COLUMN] || [''])[0];
  const lines = Object.keys(v).map(k => `■${k}\n${v[k][0]}`).join('\n\n');
  if (to) {
    GmailApp.sendEmail(to, CONFIG.SUBJECT, `${name} 様\n\n以下の内容で受け付けました。\n\n${lines}\n\n担当より2営業日以内にご連絡いたします。`);
  }
  GmailApp.sendEmail(CONFIG.ADMIN_EMAIL, `【新規】${name}`, lines);
  if (CONFIG.SLACK_WEBHOOK) {
    UrlFetchApp.fetch(CONFIG.SLACK_WEBHOOK, { method: 'post', contentType: 'application/json', payload: JSON.stringify({ text: `新規問い合わせ: ${name}\n${lines}` }) });
  }
}
