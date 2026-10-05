#!/usr/bin/env python3
"""Write fake Claude Code and Cursor transcripts for trying the app or taking screenshots.

    python3 tools/demo_data.py /tmp/dfx-demo          # one-off
    python3 tools/demo_data.py /tmp/dfx-demo --live   # keep appending every second or so

Claude Code: three sessions, one with Task subagents and a workflow, streamed assistant
messages (several records per message.id), mostly Opus with Sonnet subagents, busier in the
last ten minutes. Cursor: two sessions without timestamps or usage, as Cursor writes them.

Then run the app against it:
    DFX_CURSOR_ROOT=/tmp/dfx-demo/cursor DFX_CLAUDE_ROOT=/tmp/dfx-demo/claude \
    DFX_CONFIG=/tmp/dfx-demo/config.json python -m dfx_agent_enhancer
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import datetime, timezone

N = [0]


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def line(o: dict) -> str:
    return json.dumps(o, separators=(",", ":")) + "\n"


def claude_turn(t: float, sid: str, model: str, sidechain: bool) -> str:
    """A user record, then one streamed assistant message: a text block and a tool_use block
    written as two records with the same message.id and a growing output_tokens."""
    N[0] += 1
    mid = "msg_demo_%06d" % N[0]
    base = {"isSidechain": sidechain, "sessionId": sid, "cwd": "/Users/you/code/demo"}
    out = int(random.lognormvariate(6.6, 0.9))
    usage = {"input_tokens": 4, "cache_read_input_tokens": 40000 + 50 * N[0], "cache_creation_input_tokens": 600}
    text = ""
    text += line({"type": "user", **base, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_prev", "content": "ok"}]}, "timestamp": iso(t)})
    text += line({**base, "type": "assistant", "timestamp": iso(t + 2), "message": {
        "id": mid, "model": model, "role": "assistant", "content": [{"type": "text", "text": "working"}],
        "usage": {**usage, "output_tokens": 1}}})
    text += line({**base, "type": "assistant", "timestamp": iso(t + 4), "message": {
        "id": mid, "model": model, "role": "assistant",
        "content": [{"type": "tool_use", "id": "toolu_%06d" % N[0], "name": "Bash", "input": {}}],
        "usage": {**usage, "output_tokens": out}}})
    return text


def cursor_line(kind: str) -> str:
    if kind == "user":
        return line({"role": "user", "message": {"content": [{"type": "text", "text": "next step"}]}})
    return line({"role": "assistant", "message": {"content": [{"type": "tool_use", "name": "ReadFile", "input": {"path": "x"}}]}})


def history(path: str, sid: str, model: str, sidechain: bool, now: float, start: float, busy_from: float) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        t = start
        while t < now - 5:
            f.write(claude_turn(t, sid, model, sidechain))
            t += random.uniform(8, 40) if t > busy_from else random.uniform(150, 900)


def main() -> None:
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "/tmp/dfx-demo")
    live = "--live" in sys.argv
    now = time.time()
    projects = os.path.join(root, "claude", "projects")
    names = ("api", "web", "docs")       # one project folder per session: the menu lists them by name
    sids = ["5e55e55e-0000-4000-8000-00000000000%d" % i for i in (1, 2, 3)]
    claude_files = []
    # session 1: the main driver, with Task subagents and a workflow, busy for the last 10 min
    for i, sid in enumerate(sids):
        p = os.path.join(projects, "-Users-you-code-" + names[i], sid + ".jsonl")
        history(p, sid, "claude-opus-5", False, now, now - (8 - 2 * i) * 3600, now - (600 if i < 2 else 0))
        claude_files.append((p, sids[i], "claude-opus-5", False))
    sub = os.path.join(projects, "-Users-you-code-api", sids[0], "subagents")
    agents = [os.path.join(sub, "agent-a%02d.jsonl" % k) for k in range(3)]
    agents += [os.path.join(sub, "workflows", "wf_demo", "agent-w%02d.jsonl" % k) for k in range(2)]
    for k, p in enumerate(agents):
        model = "claude-sonnet-5" if k % 2 else "claude-opus-5"
        history(p, sids[0], model, True, now, now - 900 - 300 * k, now - 900)
        claude_files.append((p, sids[0], model, True))
    with open(os.path.join(sub, "workflows", "wf_demo", "journal.jsonl"), "w") as f:
        f.write(line({"kind": "started", "workflow": "wf_demo"}))
    # Cursor: no timestamps, no usage
    cdir = os.path.join(root, "cursor", "projects", "Users-you-code-demo", "agent-transcripts")
    cur_files = []
    for sid in ("c0ffee00-0000-4000-8000-000000000001", "c0ffee00-0000-4000-8000-000000000002"):
        p = os.path.join(cdir, sid, sid + ".jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            for i in range(30):
                f.write(cursor_line("user" if i % 6 == 0 else "assistant"))
        cur_files.append(p)
    print("wrote", root, flush=True)
    while live:
        time.sleep(random.uniform(0.6, 2.0))
        p, sid, model, side = random.choice(claude_files[:2] + claude_files[3:])
        with open(p, "a") as f:
            f.write(claude_turn(time.time() - 4, sid, model, side))
        if random.random() < 0.3:
            with open(random.choice(cur_files), "a") as f:
                f.write(cursor_line(random.choice(["user", "assistant", "assistant"])))


if __name__ == "__main__":
    main()
