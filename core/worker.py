"""The task worker: claims background tasks from the core API and runs them (python -m core.worker).

It only talks to the API (never the database file), so a worker can run on another machine later. Handlers:

- agent: a headless Claude Code session (`claude -p`) in its own workspace, data/tasks/<id>/. It can read that
  workspace and any `dirs` the task names, search and fetch the web, and write only in its workspace; nothing else
  unless the task lists more `tools`. The final answer, the transcript and any files it wrote stay in the workspace.
- revalue: today's FT prices for hand-written holdings (investments.revalue).
- premium-bonds: has the holder number won? (investments.premium_bonds; asks NS&I only when a result is due).
"""
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import telemetry

from music_sync.service import load_env

from . import client

log = logging.getLogger("core.worker")
ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = ROOT / "data" / "tasks"
SLOTS = int(os.environ.get("CORE_WORKER_SLOTS", "2"))
BEAT_S = 20
POLL_S = 5
AGENT_TOOLS = ["Read(./**)", "Glob", "Grep", "WebSearch", "WebFetch", "Write(./**)", "Edit(./**)"]
AGENT_PROMPT = ("You are running as a background task for the user's home system, with nobody watching. Work in the "
                "current directory. Put the deliverable in result.md (clear, concise, with sources for anything from "
                "the web), and end with a short summary of what you did and found. Don't ask questions: make "
                "reasonable assumptions and state them.")


class Context:
    """What a handler gets: the task, a way to report progress, and whether it's been cancelled."""

    def __init__(self, task: dict, worker: str):
        self.task, self.worker = task, worker
        self.cancelled = threading.Event()
        self._lines: list[str] = []
        self._progress = self._message = None
        self._lock = threading.Lock()

    def log(self, line: str):
        with self._lock:
            self._lines.append(line)

    def progress(self, fraction: float | None = None, message: str | None = None):
        with self._lock:
            self._progress, self._message = fraction, message or self._message

    def beat(self):
        with self._lock:
            lines, self._lines = self._lines, []
            body = {"worker": self.worker, "progress": self._progress, "message": self._message, "events": lines}
        try:
            if client.call("POST", f"/v1/tasks/{self.task['id']}/heartbeat", body)["cancel"]:
                self.cancelled.set()
        except Exception as e:  # core restarting: keep working, the lease outlasts a short gap
            log.warning("heartbeat for task %s failed: %s", self.task["id"], e)
            with self._lock:
                self._lines = lines + self._lines


def run_agent(ctx: Context):
    inp = ctx.task["input"] or {}
    prompt = str(inp.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("an agent task needs input.prompt")
    claude = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
    work = WORKSPACES / str(ctx.task["id"])
    work.mkdir(parents=True, exist_ok=True)
    (work / "prompt.md").write_text(prompt + "\n")
    dirs = [str(Path(d).expanduser().resolve()) for d in inp.get("dirs") or []]
    missing = [d for d in dirs if not Path(d).is_dir()]
    if missing:
        raise ValueError(f"no such folder: {', '.join(missing)}")
    tools = AGENT_TOOLS + [f"Read(/{d}/**)" for d in dirs] + list(inp.get("tools") or [])
    cmd = [claude, "-p", prompt, "--output-format", "stream-json", "--verbose", "--append-system-prompt", AGENT_PROMPT,
           "--allowedTools", *tools]
    for d in dirs:
        cmd += ["--add-dir", d]
    if inp.get("model"):
        cmd += ["--model", str(inp["model"])]
    timeout = min(float(inp.get("timeout_min") or 30), 180) * 60
    ctx.progress(0.05, "starting Claude")
    started, turns, final = time.monotonic(), 0, None
    with open(work / "transcript.jsonl", "w") as transcript:
        proc = subprocess.Popen(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                start_new_session=True, env=agent_env())
        killer = threading.Thread(target=_watch, args=(proc, ctx, started + timeout), daemon=True)
        killer.start()
        for line in proc.stdout:
            transcript.write(line)
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                turns += 1
                for part in ev.get("message", {}).get("content", []):
                    if part.get("type") == "tool_use":
                        ctx.log(f"{part.get('name')}: {_brief(part.get('input'))}")
                ctx.progress(min(0.9, 0.05 + turns * 0.03), f"working ({turns} steps)")
            elif ev.get("type") == "result":
                final = ev
        proc.wait()
    if ctx.cancelled.is_set():
        return None
    if time.monotonic() - started >= timeout:
        raise TimeoutError(f"stopped after {timeout / 60:.0f} minutes")
    if not final or final.get("is_error") or proc.returncode:
        raise RuntimeError((final or {}).get("result") or f"claude exited with {proc.returncode}")
    text = final.get("result") or ""
    if not (work / "result.md").exists():
        (work / "result.md").write_text(text + "\n")
    files = sorted(str(p.relative_to(work)) for p in work.rglob("*") if p.is_file()
                   and p.name not in ("prompt.md", "transcript.jsonl"))
    return {"summary": text[-4000:], "workspace": str(work), "files": files, "turns": final.get("num_turns"),
            "cost_usd": final.get("total_cost_usd"), "seconds": round(time.monotonic() - started)}


def agent_env() -> dict:
    """The worker's environment without this repo's secrets (.env), so an agent given a shell can't read them."""
    secret = set()
    env_file = ROOT / ".env"
    for raw in env_file.read_text().splitlines() if env_file.exists() else []:
        if "=" in raw and not raw.lstrip().startswith("#"):
            secret.add(raw.split("=", 1)[0].strip())
    return {k: v for k, v in os.environ.items() if k not in secret and "TOKEN" not in k and "SECRET" not in k
            and "PASSWORD" not in k} | {"CLAUDE_CODE_ENTRYPOINT": "home-tasks"}


def _watch(proc: subprocess.Popen, ctx: Context, deadline: float):
    """Stop the agent if the task is cancelled or runs out of time."""
    while proc.poll() is None:
        if ctx.cancelled.is_set() or time.monotonic() > deadline:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                os.killpg(proc.pid, signal.SIGKILL)
            return
        time.sleep(1)


def _brief(value) -> str:
    if isinstance(value, dict):
        value = value.get("query") or value.get("url") or value.get("file_path") or value.get("pattern") or value
    return str(value)[:160]


def run_revalue(ctx: Context):
    from investments.__main__ import revalue
    from investments.prices import Prices
    ctx.progress(0.1, "fetching prices")
    return {"priced": revalue(Prices())}


def run_premium_bonds(ctx: Context):
    from investments.premium_bonds import check
    ctx.progress(0.1, "checking")
    return check()


HANDLERS = {"agent": run_agent, "revalue": run_revalue, "premium-bonds": run_premium_bonds}
FINISHED = telemetry.meter().create_counter("home.tasks.finished", description="tasks finished, by kind and outcome")
DURATION = telemetry.meter().create_histogram("home.task.duration", unit="s", description="how long tasks took")


def work_on(task: dict, worker: str):
    ctx = Context(task, worker)
    stop, started = threading.Event(), time.monotonic()

    def beats():
        while not stop.wait(BEAT_S):
            ctx.beat()
    threading.Thread(target=beats, daemon=True).start()
    result, error = None, None
    try:
        result = HANDLERS[task["kind"]](ctx)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        log.warning("task %s (%s) failed: %s", task["id"], task["kind"], error)
    finally:
        stop.set()
    ctx.beat()  # flush the last log lines
    body = {"worker": worker, "result": result, "error": error, "cancelled": ctx.cancelled.is_set()}
    for attempt in range(5):
        try:
            client.call("POST", f"/v1/tasks/{task['id']}/finish", body)
            break
        except Exception as e:
            log.warning("couldn't report task %s finished (%s); retrying", task["id"], e)
            time.sleep(2 ** attempt)
    outcome = "cancelled" if ctx.cancelled.is_set() else "failed" if error else "done"
    FINISHED.add(1, {"kind": task["kind"], "outcome": outcome})
    DURATION.record(time.monotonic() - started, {"kind": task["kind"], "outcome": outcome})
    log.info("task %s (%s) %s", task["id"], task["kind"], outcome)


def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    telemetry.setup("core.worker")
    worker = f"{socket.gethostname().split('.')[0]}-{os.getpid()}"
    running: list[threading.Thread] = []
    log.info("worker %s: %d slots, kinds %s", worker, SLOTS, ", ".join(HANDLERS))
    while True:
        running = [t for t in running if t.is_alive()]
        task = None
        if len(running) < SLOTS:
            try:
                task = client.call("POST", "/v1/tasks/claim", {"worker": worker, "kinds": list(HANDLERS)})["task"]
            except Exception as e:  # core not up yet
                log.debug("claim failed: %s", e)
        if task:
            log.info("task %s (%s): %s", task["id"], task["kind"], task["title"])
            t = threading.Thread(target=work_on, args=(task, worker), daemon=True, name=f"task-{task['id']}")
            t.start()
            running.append(t)
            continue  # there may be more ready
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
