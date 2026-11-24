/**
 * Valor ⇄ Google Workspace hook (PLACEHOLDER, untested against a live bank tenant).
 *
 * Deploy: script.google.com → New project → paste this file → enable the Advanced Drive
 * service (Drive API v2) → Deploy → Web app (execute as: user accessing; access: your domain).
 * Put the web-app URL in config/settings.yaml → google.apps_script_url.
 *
 * Actions (POST JSON):
 *   {action: "export_doc",   title, html}                      → {url, id}
 *   {action: "create_draft", to[], cc[], subject, body, file_url} → {draft_id, url}
 * It never sends email: create_draft only creates a Gmail draft for the user to review.
 * No Gemini dependency.
 */

const FOLDER_ID = ''; // optional: Drive folder for exported reports

function doPost(e) {
  const req = JSON.parse(e.postData.contents);
  let out;
  if (req.action === 'export_doc') out = exportDoc_(req.title, req.html);
  else if (req.action === 'create_draft') out = createDraft_(req);
  else out = { error: 'unknown action ' + req.action };
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

function exportDoc_(title, html) {
  const blob = Utilities.newBlob(html, 'text/html', title + '.html');
  const meta = { title: title, mimeType: MimeType.GOOGLE_DOCS };
  if (FOLDER_ID) meta.parents = [{ id: FOLDER_ID }];
  const file = Drive.Files.insert(meta, blob, { convert: true });
  return { id: file.id, url: 'https://docs.google.com/document/d/' + file.id + '/edit' };
}

function createDraft_(req) {
  const options = { cc: (req.cc || []).join(',') };
  if (req.file_url) {
    const m = req.file_url.match(/[-\w]{25,}/);
    if (m) options.attachments = [DriveApp.getFileById(m[0]).getAs(MimeType.PDF)];
  }
  const draft = GmailApp.createDraft((req.to || []).join(','), req.subject, req.body, options);
  return { draft_id: draft.getId(), url: 'https://mail.google.com/mail/#drafts' };
}
