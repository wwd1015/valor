"""Sharing: a prefilled Gmail compose link the user opens, edits and sends. Never sends."""

from __future__ import annotations

import json
from urllib.parse import quote

from valor import service, store
from valor.agent import tasks
from valor.config import settings
from valor.integrations import google
from valor.report import render


def gmail_compose_url(to: list[str], cc: list[str], subject: str, body: str) -> str:
    q = f"view=cm&fs=1&to={quote(','.join(to))}&su={quote(subject)}&body={quote(body)}"
    if cc:
        q += f"&cc={quote(','.join(cc))}"
    return f"https://mail.google.com/mail/?{q}"


def report_link(report: dict | None) -> str:
    if report and report.get("external_url"):
        return report["external_url"]
    folder = settings()["google"].get("drive_folder_url")
    if folder:
        return f"{folder} (file the report there: {report['docx_path'].rsplit('/', 1)[-1] if report else 'report'})"
    return "[add the Google Drive link to the report here]"


def draft(case_id: str, actor: str, use_agent: bool = True) -> dict:
    rep = render.latest_report(case_id)
    if not rep:
        raise service.ReviewError("Generate a report first; the email links to it.")
    findings = json.loads(rep["findings"])
    link = report_link(rep)
    prefix = settings()["share"]["subject_prefix"]
    data, meta = tasks.draft_email(findings, link, prefix, use_agent=use_agent)
    store.audit(case_id, actor, "email_drafted", details={"report_id": rep["id"], **meta})
    return {"subject": data["subject"], "body": data["body"], "report_link": link, "source": meta["mode"],
            "unverified": meta.get("unverified_numbers", [])}


def log_open(case_id: str, actor: str, to: list[str], subject: str) -> None:
    store.audit(case_id, actor, "email_compose_opened", details={"to": to, "subject": subject,
                                                                  "note": "Opened in Gmail for the user to edit and send"})


def apps_script_draft(case_id: str, actor: str, to, cc, subject, body) -> dict:
    if not google.enabled():
        raise service.ReviewError("Apps Script is not configured (google.apps_script_url in config/settings.yaml).")
    rep = render.latest_report(case_id)
    res = google.create_draft(to, cc, subject, body, rep.get("external_url") if rep else None)
    store.audit(case_id, actor, "gmail_draft_created", details={"to": to, "subject": subject, **res})
    return res
