/**
 * Gmail の添付ファイル（請求書PDFなど）を Drive フォルダへ自動保存し、一覧シートに記録
 * 設置: スプレッドシート > Apps Script → 時間主導型トリガーで saveAttachments を1時間ごと
 */
const CFG = {
  QUERY: 'has:attachment filename:pdf -label:saved newer_than:7d',  // 例: from:billing@example.com を足す
  FOLDER_ID: 'ここにDriveフォルダID',
  LABEL: 'saved',
  SHEET: '受信ログ',
};

function saveAttachments() {
  const folder = DriveApp.getFolderById(CFG.FOLDER_ID);
  const label = GmailApp.getUserLabelByName(CFG.LABEL) || GmailApp.createLabel(CFG.LABEL);
  const ss = SpreadsheetApp.getActive();
  const sh = ss.getSheetByName(CFG.SHEET) || ss.insertSheet(CFG.SHEET);
  if (sh.getLastRow() === 0) sh.appendRow(['受信日時', '差出人', '件名', 'ファイル名', 'URL']);
  GmailApp.search(CFG.QUERY, 0, 50).forEach(th => {
    th.getMessages().forEach(m => {
      m.getAttachments().forEach(a => {
        const f = folder.createFile(a.copyBlob()).setName(Utilities.formatDate(m.getDate(), 'JST', 'yyyyMMdd_') + a.getName());
        sh.appendRow([m.getDate(), m.getFrom(), m.getSubject(), f.getName(), f.getUrl()]);
      });
    });
    th.addLabel(label);
  });
}
