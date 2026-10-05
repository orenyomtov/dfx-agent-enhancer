#!/usr/bin/env python3
"""Write fake Claude Code and Cursor transcripts for trying the app or taking screenshots.

    python3 tools/demo_data.py /tmp/dfx-demo             # one-off, history up to now
    python3 tools/demo_data.py /tmp/dfx-demo --live      # keep appending every second or so
    python3 tools/demo_data.py /tmp/dfx-demo --at 17:20  # history up to 17:20 today (for screenshots
                                                         # of TODAY; build the snapshot with that now)

Claude Code: three sessions, one with Task subagents and a workflow, streamed assistant
messages (several records per message.id) with usage as Claude Code writes it (1-hour cache
writes, a context that grows until it is compacted), Opus 5.5 with Sonnet 5.5 and Haiku 4.5
subagents, busier in the last ten minutes. Cursor: two sessions without timestamps or usage, as
Cursor writes them.

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
CTX: dict = {}           # file -> cached context size, grows each turn until a compaction


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def line(o: dict) -> str:
    return json.dumps(o, separators=(",", ":")) + "\n"


def claude_turn(t: float, sid: str, model: str, sidechain: bool, key: str = "") -> str:
    """A user record, then one streamed assistant message: a text block and a tool_use block
    written as two records with the same message.id and a growing output_tokens (the input and
    cache counts repeat)."""
    N[0] += 1
    mid = "msg_demo_%06d" % N[0]
    base = {"isSidechain": sidechain, "sessionId": sid, "cwd": "/Users/you/code/demo"}
    out = int(random.lognormvariate(6.3, 0.9))
    write = int(random.lognormvariate(7.4, 0.9))           # new turns written to the cache
    read = CTX.get(key, random.randint(18000, 30000))
    CTX[key] = read + write if read + write < 160000 else random.randint(25000, 40000)   # compacted
    usage = {"input_tokens": random.randint(1, 9), "cache_creation_input_tokens": write, "cache_read_input_tokens": read,
             "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": write},
             "service_tier": "standard", "speed": "standard"}
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


def history(path: str, sid: str, model: str, sidechain: bool, now: float, start: float, busy) -> None:
    """Turns from start to now: one every 8-40 s inside the busy blocks ((from, to) hours before
    now), a trickle outside them."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        t = start
        while t < now - 5:
            f.write(claude_turn(t, sid, model, sidechain, path))
            hot = any(now - a * 3600 <= t < now - b * 3600 for a, b in busy)
            t += random.uniform(8, 40) if hot else random.uniform(300, 1200)
    os.utime(path, (now, now))


def main() -> None:
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "/tmp/dfx-demo")
    live = "--live" in sys.argv
    now = time.time()
    if "--at" in sys.argv:
        h, m = map(int, sys.argv[sys.argv.index("--at") + 1].split(":"))
        now = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0).timestamp()
    projects = os.path.join(root, "claude", "projects")
    names = ("api", "web", "docs")       # one project folder per session: the menu lists them by name
    sids = ["5e55e55e-0000-4000-8000-00000000000%d" % i for i in (1, 2, 3)]
    claude_files = []
    # work blocks in hours before now; sessions 1 and 2 are busy again in the last 10 minutes
    busy = [((7.5, 6.2), (3.2, 1.6), (0.17, 0)), ((5.2, 4.1), (2.2, 0.6), (0.17, 0)), ((4, 2.6),)]
    # session 1: the main driver, with Task subagents and a workflow
    for i, sid in enumerate(sids):
        p = os.path.join(projects, "-Users-you-code-" + names[i], sid + ".jsonl")
        history(p, sid, "claude-opus-5-5", False, now, now - (8 - 2 * i) * 3600, busy[i])
        claude_files.append((p, sids[i], "claude-opus-5-5", False))
    sub = os.path.join(projects, "-Users-you-code-api", sids[0], "subagents")
    agents = [os.path.join(sub, "agent-a%02d.jsonl" % k) for k in range(3)]
    agents += [os.path.join(sub, "workflows", "wf_demo", "agent-w%02d.jsonl" % k) for k in range(2)]
    for k, p in enumerate(agents):
        model = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5-20251001", "claude-sonnet-5-5")[k]
        history(p, sids[0], model, True, now, now - 3.2 * 3600 + 600 * k, ((3.1 - 0.2 * k, 1.8), (0.25, 0)))
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
        os.utime(p, (now - 240, now - 240))
        cur_files.append(p)
    print("wrote", root, flush=True)
    while live:
        time.sleep(random.uniform(0.6, 2.0))
        p, sid, model, side = random.choice(claude_files[:2] + claude_files[3:])
        with open(p, "a") as f:
            f.write(claude_turn(time.time() - 4, sid, model, side, p))
        if random.random() < 0.3:
            with open(random.choice(cur_files), "a") as f:
                f.write(cursor_line(random.choice(["user", "assistant", "assistant"])))


if __name__ == "__main__":
    main()
