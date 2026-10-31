/**
 * Drive の「取込」フォルダに置かれた CSV（Shift_JIS/UTF-8）をシートへ追記 → 処理済みフォルダへ移動 → Chatwork/Slack通知
 * 設置: 時間主導型トリガーで importCsv を毎朝
 */
const C = { IN: '取込フォルダID', DONE: '処理済みフォルダID', SHEET: 'データ', SLACK: '', CHATWORK_TOKEN: '', CHATWORK_ROOM: '' };

function importCsv() {
  const sh = SpreadsheetApp.getActive().getSheetByName(C.SHEET) || SpreadsheetApp.getActive().insertSheet(C.SHEET);
  const files = DriveApp.getFolderById(C.IN).getFilesByType(MimeType.CSV);
  let n = 0;
  while (files.hasNext()) {
    const f = files.next();
    let text = f.getBlob().getDataAsString('UTF-8');
    if (text.indexOf('�') >= 0) text = f.getBlob().getDataAsString('Shift_JIS');
    const rows = Utilities.parseCsv(text);
    const body = sh.getLastRow() > 0 ? rows.slice(1) : rows;
    if (body.length) sh.getRange(sh.getLastRow() + 1, 1, body.length, body[0].length).setValues(body);
    n += body.length;
    f.moveTo(DriveApp.getFolderById(C.DONE));
  }
  if (n) notify_(`CSV取込: ${n}行を追加しました`);
}

function notify_(text) {
  if (C.SLACK) UrlFetchApp.fetch(C.SLACK, { method: 'post', contentType: 'application/json', payload: JSON.stringify({ text }) });
  if (C.CHATWORK_TOKEN) UrlFetchApp.fetch(`https://api.chatwork.com/v2/rooms/${C.CHATWORK_ROOM}/messages`, { method: 'post', headers: { 'X-ChatWorkToken': C.CHATWORK_TOKEN }, payload: { body: text } });
}
