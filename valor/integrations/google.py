"""Google Workspace hooks via an Apps Script web app (apps_script/Code.gs).

Disabled unless `google.apps_script_url` is set in config/settings.yaml. The script:
  action=export_doc   {title, html}                         -> {url}   Google Doc from the report HTML
  action=create_draft {to, cc, subject, body, file_url}     -> {draft_id, url}   a Gmail draft, never sent
No Gemini dependency; Apps Script runs as the signed-in user.
"""

from __future__ import annotations

import json
import urllib.request

from valor.config import settings


def enabled() -> bool:
    return bool(settings()["google"].get("apps_script_url"))


def _post(payload: dict) -> dict:
    url = settings()["google"]["apps_script_url"]
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - whitelisted internal endpoint
        return json.loads(r.read().decode())


def export_doc(title: str, html: str) -> dict:
    return _post({"action": "export_doc", "title": title, "html": html})


def create_draft(to: list[str], cc: list[str], subject: str, body: str, file_url: str | None) -> dict:
    return _post({"action": "create_draft", "to": to, "cc": cc, "subject": subject, "body": body, "file_url": file_url})
