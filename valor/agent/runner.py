"""Run one judgment/language task through Claude Code in headless mode (`claude -p`).

The app never calls Bedrock directly: the `claude` CLI on the user's laptop is already set up
for Bedrock (CLAUDE_CODE_USE_BEDROCK etc.), and this module only shells out to it.

Each call:
  * runs in an empty temp directory with no tools, no project settings and no session file,
    so the model sees only the prompt we build;
  * asks for JSON matching a schema (`--json-schema`), returned as `structured_output`;
  * is recorded in var/agent_runs/<run_id>.json and the agent_runs table.

Mode (config/settings.yaml `agent.mode`, or VALOR_AGENT_MODE):
  auto   -> claude if the CLI is on PATH, else the deterministic mock; a failed call falls back
  claude -> claude only; failures raise
  mock   -> deterministic mock only
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
import uuid
from string import Template
from typing import Any, Callable

from valor import store
from valor.config import PROMPTS_DIR, path_setting, settings


class AgentError(RuntimeError):
    pass


def prompt_text(name: str, **vars) -> str:
    return Template((PROMPTS_DIR / f"{name}.md").read_text()).safe_substitute(**vars)


def mode() -> str:
    cfg = settings()["agent"]
    m = cfg["mode"]
    if m == "auto":
        return "claude" if shutil.which(cfg["claude_bin"]) else "mock"
    return m


def _claude(prompt: str, schema: dict, system: str) -> tuple[dict, dict]:
    cfg = settings()["agent"]
    cmd = [cfg["claude_bin"], "-p", prompt,
           "--output-format", "json",
           "--json-schema", json.dumps(schema),
           "--append-system-prompt", system,
           "--tools", "",
           "--setting-sources", "",
           "--no-session-persistence",
           "--max-turns", str(cfg.get("max_turns", 3))]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    workdir = tempfile.mkdtemp(prefix="valor-agent-")   # empty cwd: no project files, no CLAUDE.md
    proc = subprocess.run(cmd, cwd=workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=cfg.get("timeout_s", 180))
    if not proc.stdout.strip():
        raise AgentError(f"claude exited {proc.returncode}: {proc.stderr[-400:]}")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise AgentError(f"claude returned non-JSON output: {proc.stdout[:300]}") from e
    if out.get("is_error"):
        raise AgentError(f"claude reported an error ({out.get('subtype')}): {str(out.get('result'))[:300]}")
    data = out.get("structured_output")
    if data is None:
        try:
            data = json.loads(out.get("result") or "")
        except json.JSONDecodeError as e:
            raise AgentError(f"no structured output: {str(out.get('result'))[:300]}") from e
    meta = {"model": out.get("model") or cfg.get("model") or "cli-default",
            "cost_usd": out.get("total_cost_usd"), "turns": out.get("num_turns")}
    return data, meta


def call(task: str, case_id: str | None, prompt: str, schema: dict, mock: Callable[[], Any],
         use_agent: bool = True) -> tuple[Any, dict]:
    """Run `task`; return (data, meta). meta["mode"] is "claude", "mock" or "mock-fallback"."""
    run_id = f"{task}-{uuid.uuid4().hex[:10]}"
    system = prompt_text("system")
    m = mode() if use_agent else "mock"
    started = time.time()
    status, err, extra = "ok", None, {}
    if m == "mock":
        data, used = mock(), "mock"
    else:
        try:
            data, extra = _claude(prompt, schema, system)
            used = "claude"
        except Exception as e:  # noqa: BLE001 - any failure is recorded; auto mode degrades to mock
            if settings()["agent"]["mode"] == "claude":
                _record(run_id, case_id, task, "claude", time.time() - started, "error", prompt, None, str(e), {})
                raise AgentError(str(e)) from e
            data, used, status, err = mock(), "mock-fallback", "fallback", str(e)
    duration = time.time() - started
    _record(run_id, case_id, task, used, duration, status, prompt, data, err, extra)
    return data, {"mode": used, "run_id": run_id, "duration_s": round(duration, 1), "error": err, **extra}


def _record(run_id, case_id, task, used, duration, status, prompt, data, err, extra) -> None:
    d = path_setting("storage", "agent_runs_dir")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{run_id}.json"
    path.write_text(json.dumps({"run_id": run_id, "task": task, "mode": used, "prompt": prompt, "output": data,
                                "error": err, **extra}, indent=1, default=str))
    store.execute("INSERT INTO agent_runs (id, case_id, ts, task, mode, model, duration_s, status, prompt_hash, "
                  "output_path, error, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, case_id, store.now(), task, used, extra.get("model"), round(duration, 2), status,
                   hashlib.sha256(prompt.encode()).hexdigest()[:16], str(path), err, extra.get("cost_usd")))
