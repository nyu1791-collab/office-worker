/**
 * シート関数 =GEMINI("要約して: " & A2) で AI を使えるようにする
 * 設置: Apps Script > プロジェクトの設定 > スクリプトプロパティに GEMINI_API_KEY
 */
function GEMINI(prompt, model) {
  const key = PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY');
  const m = model || 'gemini-2.5-flash';
  const res = UrlFetchApp.fetch(`https://generativelanguage.googleapis.com/v1beta/models/${m}:generateContent?key=${key}`, {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    payload: JSON.stringify({ contents: [{ parts: [{ text: String(prompt) }] }] }),
  });
  const j = JSON.parse(res.getContentText());
  return j.candidates ? j.candidates[0].content.parts[0].text.trim() : JSON.stringify(j.error || j);
}
