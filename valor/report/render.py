"""Render structured findings into a report template.

Templates are Jinja2 + Markdown files in templates/reports/ (`*.md.j2`); uploaded templates go
to templates/reports/uploaded/. The first line may declare metadata:
    {# name: Credit memo | description: Full memo for the approval file | layout: memo #}
layout `slides` splits the document into slides at each `---` line.
Templates render in a sandboxed Jinja environment, so an uploaded template cannot run code.

Outputs: .md, .html (print to PDF from the browser) and .docx (python-docx).
"""

from __future__ import annotations

import re
from pathlib import Path

import markdown as md
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from valor import service, store
from valor.agent import tasks
from valor.config import TEMPLATES_DIR, path_setting
from valor.report import findings as findings_mod

UPLOAD_DIR = TEMPLATES_DIR / "uploaded"
META = re.compile(r"^\{#(.*?)#\}", re.S)


def _env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    env.filters["cell"] = lambda s: str(s if s is not None else "").replace("|", "/").replace("\n", " ")
    return env


def template_meta(path: Path) -> dict:
    text = path.read_text()
    meta = {"id": path.name, "path": str(path), "name": path.name.replace(".md.j2", "").replace("_", " ").title(),
            "description": "", "layout": "memo", "uploaded": path.parent == UPLOAD_DIR}
    m = META.match(text)
    if m:
        for part in m.group(1).split("|"):
            if ":" in part:
                k, v = part.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta


def list_templates() -> list[dict]:
    paths = sorted(TEMPLATES_DIR.glob("*.md.j2")) + sorted(UPLOAD_DIR.glob("*.md.j2"))
    return [template_meta(p) for p in paths]


def find_template(tid: str) -> Path:
    for p in (TEMPLATES_DIR / tid, UPLOAD_DIR / tid):
        if p.exists():
            return p
    raise service.ReviewError(f"template {tid} not found")


def save_uploaded(filename: str, content: bytes, sample_findings: dict | None = None) -> dict:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(filename).name)
    if not name.endswith(".md.j2"):
        name = name.rsplit(".", 1)[0] + ".md.j2"
    text = content.decode("utf-8")
    try:
        tpl = _env().from_string(text)
        if sample_findings:
            tpl.render(**sample_findings)
    except Exception as e:  # noqa: BLE001
        raise service.ReviewError(f"Template did not render: {e}") from e
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / name).write_text(text)
    return template_meta(UPLOAD_DIR / name)


HTML_SHELL = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT@9..144,300..700,0..100&family=Hanken+Grotesk:wght@400..700&display=swap" rel="stylesheet">
<style>
:root {{ --ink9:#1b2633; --ink5:#56637a; --ink2:#dbe1e9; --ink1:#eef2f6; --paper:#f6f8fa; --green:#004977; --brass:#b08a2e; }}
body {{ background:var(--paper); color:var(--ink9); font:14px/1.6 "Hanken Grotesk",system-ui,sans-serif; margin:0; padding:32px 16px; }}
main {{ max-width:820px; margin:0 auto; background:#fff; border:1px solid var(--ink2); border-radius:6px; padding:36px 44px; }}
h1,h2,h3 {{ font-family:"Fraunces",Georgia,serif; font-variation-settings:"opsz" 96,"SOFT" 40; font-weight:500; letter-spacing:-.012em; line-height:1.25; }}
h1 {{ font-size:26px; font-weight:400; margin:0 0 12px; padding-bottom:12px; border-bottom:3px double #b5c0cd; }}
h2 {{ font-size:18px; margin:28px 0 8px; padding-bottom:4px; border-bottom:1px solid var(--ink2); }}
h3 {{ font-size:15px; }}
table {{ border-collapse:collapse; width:100%; font-size:12px; margin:12px 0; font-variant-numeric:tabular-nums; }}
th {{ background:var(--ink1); text-align:left; font-weight:600; }}
td,th {{ border:1px solid var(--ink2); padding:4px 8px; vertical-align:top; }}
code {{ font-family:ui-monospace,Menlo,monospace; font-size:11px; background:var(--ink1); padding:0 4px; border-radius:3px; }}
blockquote {{ margin:12px 0; padding:8px 12px; border-left:4px solid #f59e0b; background:#fffbeb; }}
blockquote p {{ margin:0; }}
hr {{ border:0; border-top:1px solid var(--ink2); margin:24px 0; }}
.slide {{ min-height:520px; border:1px solid var(--ink2); border-top:3px solid var(--green); border-radius:6px; padding:28px 36px; margin:0 0 28px; page-break-after:always; background:#fff; }}
@media print {{ body {{ background:#fff; padding:0; }} main {{ border:0; padding:0; max-width:none; }} .slide {{ border:0; min-height:auto; }} }}
</style></head><body><main>{body}</main></body></html>"""


def _render_md(path: Path, f: dict) -> str:
    text = META.sub("", path.read_text(), count=1)
    return _env().from_string(text).render(**f)


def to_html(markdown_text: str, layout: str, title: str) -> str:
    if layout == "slides":
        slides = [s for s in re.split(r"^---\s*$", markdown_text, flags=re.M) if s.strip()]
        body = "".join(f'<section class="slide">{md.markdown(s, extensions=["tables"])}</section>' for s in slides)
    else:
        body = md.markdown(markdown_text, extensions=["tables"])
    return HTML_SHELL.format(title=title, body=body)


def to_docx(markdown_text: str, layout: str, out: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Pt, RGBColor

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10.5)
    lines = markdown_text.splitlines()
    i = 0

    def add_runs(par, text):
        for j, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
            run = par.add_run(re.sub(r"[*`_]{1,2}(.+?)[*`_]{1,2}", r"\1", part))
            run.bold = j % 2 == 1

    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1
            continue
        if re.match(r"^---\s*$", ln):
            if layout == "slides":
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            i += 1
            continue
        h = re.match(r"^(#{1,4})\s+(.*)", ln)
        if h:
            doc.add_heading(re.sub(r"\*\*|`", "", h.group(2)), level=min(len(h.group(1)), 3))
            i += 1
            continue
        if ln.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            rows = [[c.strip() for c in r.strip("|").split("|")] for r in block if not re.match(r"^\|[\s:|-]+\|$", r)]
            if rows:
                t = doc.add_table(rows=len(rows), cols=len(rows[0]))
                t.style = "Light List"
                for r, row in enumerate(rows):
                    for cidx, cell in enumerate(row[:len(rows[0])]):
                        t.cell(r, cidx).text = ""
                        add_runs(t.cell(r, cidx).paragraphs[0], cell)
                        for run in t.cell(r, cidx).paragraphs[0].runs:
                            run.font.size = Pt(9)
                            if r == 0:
                                run.bold = True
            continue
        if re.match(r"^\s*[-*]\s+", ln):
            add_runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*]\s+", "", ln))
            i += 1
            continue
        if ln.startswith(">"):
            p = doc.add_paragraph()
            add_runs(p, ln.lstrip("> "))
            for run in p.runs:
                run.italic = True
                run.font.color.rgb = RGBColor(0x00, 0x49, 0x77)
            i += 1
            continue
        para = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||>|\s*[-*]\s|---)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        add_runs(doc.add_paragraph(), " ".join(para))
    doc.save(out)


def generate(case_id: str, template_id: str, actor: str, use_agent: bool = True) -> dict:
    f = findings_mod.build(case_id, actor)
    if use_agent:
        narrative, meta = tasks.draft_narrative(f)
    else:
        narrative, meta = None, {"mode": "none"}
    f["narrative"] = narrative or {"executive_summary": f["summary_line"], "methodology_commentary": "",
                                   "key_judgements": "", "conclusion": f["conclusion"]["statement"]}
    f["narrative_source"] = meta["mode"]
    f["narrative_unverified"] = meta.get("unverified_numbers", [])

    path = find_template(template_id)
    tmeta = template_meta(path)
    text = _render_md(path, f)
    out_dir = path_setting("storage", "reports_dir") / case_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = store.now().replace(":", "").replace("-", "")[:15]
    base = out_dir / f"{case_id}_{path.name.replace('.md.j2', '')}_{stamp}"
    title = f"{f['deal']['borrower']} · {tmeta['name']}"
    (base.with_suffix(".md")).write_text(text)
    (base.with_suffix(".html")).write_text(to_html(text, tmeta["layout"], title))
    to_docx(text, tmeta["layout"], base.with_suffix(".docx"))

    rid = store.execute("INSERT INTO reports (case_id, ts, actor, template, html_path, docx_path, md_path, findings, "
                        "findings_hash, narrative_source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (case_id, store.now(), actor, template_id, str(base.with_suffix(".html")),
                         str(base.with_suffix(".docx")), str(base.with_suffix(".md")),
                         __import__("json").dumps(f, default=str), f["findings_hash"], meta["mode"]))
    store.audit(case_id, actor, "report_generated", details={
        "report_id": rid, "template": template_id, "findings_hash": f["findings_hash"], "narrative": meta["mode"],
        "unverified_numbers": f["narrative_unverified"], "case_status": f["status"]})
    return {"id": rid, "html": str(base.with_suffix(".html")), "docx": str(base.with_suffix(".docx")),
            "md": str(base.with_suffix(".md")), "findings": f, "template": tmeta}


def latest_report(case_id: str) -> dict | None:
    return store.one("SELECT * FROM reports WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case_id,))


def export_google(case_id: str, actor: str) -> str:
    """Send the latest report's HTML to the Apps Script web app, which creates a Google Doc."""
    from valor.integrations import google
    if not google.enabled():
        raise service.ReviewError("Apps Script is not configured (google.apps_script_url in config/settings.yaml).")
    rep = latest_report(case_id)
    if not rep:
        raise service.ReviewError("Generate a report first.")
    case = service.get_case(case_id)
    res = google.export_doc(f"{case['borrower_name']} · {case_id} · valuation review", Path(rep["html_path"]).read_text())
    store.execute("UPDATE reports SET external_url = ? WHERE id = ?", (res.get("url"), rep["id"]))
    store.audit(case_id, actor, "report_exported", details={"report_id": rep["id"], **res})
    return res.get("url", "")
