import json
import os
import shutil
from datetime import datetime

import pytest

from dfx_agent_enhancer import snapshot, sources

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
NOW = datetime.fromisoformat("2026-10-04T12:05:00+00:00").timestamp()
SID = "5f0c9a3e-0000-4000-8000-000000000002"
PROJ = "projects/-Users-you-code-my-app"
CLAUDE_FILE = PROJ + "/" + SID + ".jsonl"
CURSOR_FILE = ("projects/Users-you-code-my-app/agent-transcripts/0b7d2c1e-0000-4000-8000-000000000001/"
               "0b7d2c1e-0000-4000-8000-000000000001.jsonl")


@pytest.fixture
def roots(tmp_path):
    """Copy the fixtures so tests can set mtimes and append lines."""
    cur, cla = tmp_path / "cursor", tmp_path / "claude"
    shutil.copytree(os.path.join(FIX, "cursor"), cur)
    shutil.copytree(os.path.join(FIX, "claude"), cla)
    for p in (cur / CURSOR_FILE, cla / CLAUDE_FILE):
        os.utime(p, (NOW, NOW))
    return str(cur), str(cla)


def scan(roots, now=NOW):
    s = snapshot.Scanner(*roots)
    s.refresh(now)
    return s


def rows(snap):
    return {r["id"]: r for r in snap["rows"]}


def iso(t):
    return datetime.fromtimestamp(t).astimezone().isoformat()


def asst(t, mid, out, sid=SID, model="claude-opus-5", tool=None, **extra):
    content = [{"type": "tool_use", "id": tool, "name": "Bash", "input": {}}] if tool else [{"type": "text", "text": "x"}]
    return compact({"type": "assistant", "timestamp": iso(t), "sessionId": sid, **extra,
                    "message": {"id": mid, "model": model, "role": "assistant", "content": content,
                                "usage": {"input_tokens": 3, "cache_read_input_tokens": 50000, "output_tokens": out}}})


def user(t, sid=SID):
    return compact({"type": "user", "sessionId": sid,
                    "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
                    "timestamp": iso(t)})


def compact(o):
    """Claude Code writes compact JSON, top-level type before the content, timestamp after it."""
    return json.dumps(o, separators=(",", ":")) + "\n"


def write(path, text, mtime=NOW, mode="a"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(text)
    os.utime(path, (mtime, mtime))


# ---------------------------------------------------------------- Claude Code

def test_claude_tokens_tools_and_errors(roots):
    snap = snapshot.build(scan(("/nonexistent", roots[1])), "now", now=NOW)
    r = rows(snap)
    assert r["tokens"]["value"] == 120 + 45 + 300       # output tokens only, never cache reads
    assert r["tools"]["value"] == 1
    assert r["errors"]["value"] == 0                    # a failed tool result is routine, not an error
    assert r["errors"]["led"] == "green"
    assert r["sessions"]["value"] == 1                  # last record 80 s ago: working now
    assert snap["now"]["active"] == 1
    assert snap["menuTitle"] == "1 active"
    assert snap["readout"]["text"] == "1 active · 1 open" and snap["readout"]["led"] == "green"
    # tokens are a rate: 30 s buckets, so the bucket totals are doubled
    assert sum(snap["spectrum"]["tokens"]["values"]) == 2 * 465
    assert "Models: Opus 5 100%." in r["tokens"]["tip"]


def test_subagent_and_workflow_tokens_are_included(roots):
    base = os.path.join(roots[1], PROJ, SID, "subagents")
    write(os.path.join(base, "agent-a1.jsonl"), user(NOW - 100) + asst(NOW - 90, "msg_sub_1", 700, tool="toolu_s1"))
    write(os.path.join(base, "workflows", "wf_1", "agent-a2.jsonl"),
          asst(NOW - 60, "msg_wf_1", 1000, model="claude-sonnet-5"))
    # metadata and the workflow journal are not transcripts
    write(os.path.join(base, "workflows", "wf_1", "journal.jsonl"), asst(NOW - 60, "msg_journal", 99999))
    write(os.path.join(base, "agent-a1.meta.json"), "{}")
    snap = snapshot.build(scan(roots), "now", now=NOW)
    r = rows(snap)
    assert r["tokens"]["value"] == 465 + 700 + 1000
    assert r["subagents"]["value"] == 2
    assert r["tools"]["value"] == 2
    # model shares sit in the TOKENS row tooltip, for the shown window: 1165 Opus vs 1000 Sonnet
    assert "Models: Opus 5 54%, Sonnet 5 46%." in r["tokens"]["tip"]
    assert "79% from subagents" in r["tokens"]["tip"]      # 1700 of 2165
    # subagents fold into their parent: still one Claude session (plus one Cursor session)
    assert rows(snapshot.build(scan(roots), "1h", now=NOW))["sessions"]["value"] == 2


def test_streamed_duplicate_message_ids_count_once(roots):
    """One API message is written as one record per content block with the same message.id and
    a growing output_tokens; the max is the final count."""
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 40, "msg_stream", 1) + asst(NOW - 35, "msg_stream", 1, tool="toolu_x"))
    s = scan(("/nonexistent", roots[1]))
    assert rows(snapshot.build(s, "now", now=NOW))["tokens"]["value"] == 465 + 1
    write(p, asst(NOW - 20, "msg_stream", 250, tool="toolu_x"), mtime=NOW + 2)   # same tool block repeated
    s.refresh(NOW + 2)
    snap = snapshot.build(s, "now", now=NOW + 2)
    assert rows(snap)["tokens"]["value"] == 465 + 250
    assert rows(snap)["tools"]["value"] == 1 + 1
    # each record adds what is new at its own time: 1 lands at -40 s, 249 at -20 s
    vals = snap["spectrum"]["tokens"]["values"]
    assert vals[-2:] == [2, 498]                        # per minute
    assert snap["spectrum"]["tokens"]["tips"][-1].endswith("\n249 tokens · 498/min")


def test_synthetic_replays_do_not_count_tool_calls(roots):
    """A resumed session can get a <synthetic> record that repeats many earlier tool_use blocks
    (same ids, zero usage, not an API error); they are not new tool calls."""
    p = os.path.join(roots[1], CLAUDE_FILE)
    old = "".join(asst(NOW - 100 + i, "m%d" % i, 5, tool="toolu_r%d" % i) for i in range(20))
    write(p, old)
    replay = json.loads(asst(NOW - 30, "6b1f0c1e-uuid", 0, model="<synthetic>"))
    replay["message"]["content"] = [{"type": "tool_use", "id": "toolu_r%d" % i, "name": "Bash", "input": {}}
                                    for i in range(20)]
    write(p, compact(replay))
    r = rows(snapshot.build(scan(("/nonexistent", roots[1])), "now", now=NOW))
    assert r["tools"]["value"] == 1 + 20
    assert r["errors"]["value"] == 0


def test_synthetic_api_errors(roots):
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 30, "err1", 0, model="<synthetic>", isApiErrorMessage=True, error="server_error"))
    snap = snapshot.build(scan(("/nonexistent", roots[1])), "now", now=NOW)
    r = rows(snap)
    assert r["errors"]["value"] == 1 and r["errors"]["led"] == "red"
    assert r["tokens"]["value"] == 465
    assert "Models: Opus 5 100%." in r["tokens"]["tip"]  # <synthetic> adds nothing
    # 20 min later the error is out of NOW (green) and older than 15 min in 1H (amber)
    later = NOW + 1200
    s = scan(("/nonexistent", roots[1]), later)
    assert rows(snapshot.build(s, "now", now=later))["errors"]["led"] == "green"
    assert rows(snapshot.build(s, "1h", now=later))["errors"]["led"] == "amber"


def test_live_from_session_files_not_mtime(roots):
    cla = roots[1]
    # an idle open session: bookkeeping lines without a timestamp touched its transcript just now
    write(os.path.join(cla, CLAUDE_FILE), '{"type":"mode","mode":"normal"}\n{"type":"ai-title","title":"x"}\n',
          mtime=NOW + 600)
    later = NOW + 600
    s = scan(("/nonexistent", cla), later)
    assert snapshot.build(s, "now", now=later)["now"]["active"] == 0
    write(os.path.join(cla, "sessions", "111.json"), json.dumps(
        {"pid": 111, "sessionId": SID, "status": "idle", "kind": "interactive"}), mode="w")
    write(os.path.join(cla, "sessions", "222.json"), json.dumps(
        {"pid": 222, "sessionId": "busy-session", "status": "busy", "statusUpdatedAt": (later - 60) * 1000}), mode="w")
    write(os.path.join(cla, "sessions", "333.json"), json.dumps(
        {"pid": 333, "sessionId": "dead", "status": "busy"}), mode="w")
    write(os.path.join(cla, "sessions", "111.abcdef.key"), "not json", mode="w")
    procs = sources.Procs(claude_pids=frozenset({111, 222}))
    agents = sources.read_claude_sessions(cla, procs.claude_pids)
    assert sorted(a.pid for a in agents) == [111, 222]
    snap = snapshot.build(s, "now", procs=procs, agents=agents, now=later)
    assert (snap["now"]["active"], snap["now"]["open"]) == (1, 2)
    r = rows(snap)["sessions"]
    assert r["value"] == 1 and r["led"] == "green" and r["tip"] == "1 session working now, 2 open"
    assert snap["readout"]["text"] == "1 active · 2 open"
    idle = [a for a in agents if not a.busy]
    snap = snapshot.build(s, "now", "tokens", procs=procs, agents=idle, now=later)
    r = rows(snap)["sessions"]
    assert r["value"] == 0 and r["led"] == "amber"
    assert snap["readout"] == {"text": "Idle · 1 open", "led": "amber",
                               "tip": "No session working now, 1 open. 0 output tokens in the last minute."}
    assert snap["deckText"] == {"big": "IDLE", "small": ""} and snap["menuTitle"] == ""


def test_busy_without_recent_records_is_open_not_working(roots):
    """Claude Code keeps "busy" for hours while a session waits; past 30 min of silence
    (no record in any transcript, no status change) the session is open, not working."""
    cla = roots[1]
    write(os.path.join(cla, "sessions", "111.json"), json.dumps(
        {"pid": 111, "sessionId": SID, "status": "busy", "statusUpdatedAt": (NOW - 7200) * 1000}), mode="w")
    procs = sources.Procs(claude_pids=frozenset({111}))
    agents = sources.read_claude_sessions(cla, procs.claude_pids)
    assert agents[0].since == NOW - 7200
    s = scan(("/nonexistent", cla))
    # last record 12:03:40, 80 s before NOW: working; 20 min later busy still counts; 40 min later not
    for dt, live in ((0, 1), (1200, 1), (2400, 0)):
        snap = snapshot.build(s, "now", procs=procs, agents=agents, now=NOW + dt)
        assert (snap["now"]["active"], snap["now"]["open"]) == (live, 1), dt


def test_claude_config_dir(monkeypatch):
    monkeypatch.delenv("CURSOR_SCOPE_CLAUDE_ROOT", raising=False)
    monkeypatch.delenv("DFX_CLAUDE_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/somewhere-else")
    assert sources.claude_root() == "/tmp/somewhere-else"


def test_malformed_last_line_does_not_raise(roots):
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, '{"type":"assistant","timestamp":"2026-10-04T12:04:00.000Z","message":{"id":"msg_fx_04","usage":{"outp')
    snap = snapshot.build(scan(roots), "now", now=NOW)
    assert rows(snap)["tokens"]["value"] == 465


def test_now_excludes_yesterday(roots):
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 86400, "msg_old", 9999, sid="old"))
    s = scan(("/nonexistent", roots[1]))
    assert rows(snapshot.build(s, "now", now=NOW))["tokens"]["value"] == 465
    assert rows(snapshot.build(s, "week", now=NOW))["tokens"]["value"] == 465 + 9999


# ---------------------------------------------------------------- Cursor and merging

def test_merged_sessions_from_both_sources(roots):
    s = scan(roots)
    snap = snapshot.build(s, "1h", now=NOW)
    assert rows(snap)["sessions"]["value"] == 2         # one Claude + one Cursor session
    assert max(snap["spectrum"]["sessions"]["values"]) == 2
    assert rows(snap)["tools"]["value"] == 1 + 2       # Claude tool_use + Cursor tool_use blocks
    text = json.dumps(snap).lower()
    assert '"cursor"' not in text and '"claude"' not in text   # nothing keyed by source


def test_cursor_only_has_no_tokens_and_defaults_to_sessions(roots):
    p = os.path.join(roots[0], CURSOR_FILE)
    os.utime(p, (NOW - 600, NOW - 600))
    s = scan((roots[0], "/nonexistent"))
    hour = snapshot.build(s, "1h", now=NOW)
    t = rows(hour)["tokens"]
    assert t["value"] is None and t["fill"] == 0 and t["led"] == "off"
    assert hour["metric"] == "sessions"                 # the only spectrum Cursor can fill
    assert hour["spectrum"]["tokens"]["known"] is False
    assert hour["now"]["rate"] is None                  # no source reports usage
    assert "Cursor activity, no usage data" in "".join(hour["spectrum"]["tokens"]["tips"])
    assert snapshot.build(s, "1h", "tokens", now=NOW)["deckText"] == {"big": "NO DATA", "small": ""}
    assert rows(hour)["sessions"]["value"] == 1
    assert rows(hour)["tools"]["value"] == 2
    # no timestamps in Cursor records: bytes on disk at launch are dated by mtime, never in NOW
    now = snapshot.build(s, "now", now=NOW)
    assert sum(now["spectrum"]["sessions"]["values"]) == 0
    assert rows(now)["tools"]["value"] == 0


def test_cursor_lines_seen_while_running_count_in_now(roots):
    s = scan((roots[0], "/nonexistent"))
    p = os.path.join(roots[0], CURSOR_FILE)
    write(p, '{"role":"assistant","message":{"content":[{"type":"tool_use","name":"Grep","input":{}}]}}\n'
             '{"type":"turn_ended","status":"error","error":"boom"}\n', mtime=NOW + 4)
    s.refresh(NOW + 4)
    snap = snapshot.build(s, "now", now=NOW + 4)
    assert rows(snap)["tools"]["value"] == 1
    assert rows(snap)["errors"]["value"] == 1           # a failed Cursor turn
    assert snap["now"]["active"] == 1
    assert snap["deckText"] == {"big": "1", "small": "ACTIVE"}    # Cursor only: the sessions graph


def test_cursor_subagents_fold_into_their_session(roots):
    d = os.path.join(roots[0], os.path.dirname(CURSOR_FILE), "subagents")
    write(os.path.join(d, "sub1.jsonl"), '{"role":"assistant","message":{"content":[]}}\n', mtime=NOW - 600)
    s = scan((roots[0], "/nonexistent"))
    r = rows(snapshot.build(s, "1h", now=NOW))
    assert r["sessions"]["value"] == 1 and r["subagents"]["value"] == 1


def test_resumed_old_cursor_transcript_counts_only_new_lines_in_now(roots):
    """A transcript skipped at startup (older than the week) that is written to later must not
    dump its whole history into NOW: only the appended line was seen happening."""
    os.utime(os.path.join(roots[0], CURSOR_FILE), (NOW - 600, NOW - 600))     # not live: only old1 is
    p = os.path.join(roots[0], "projects", "Users-you-code-old", "agent-transcripts", "old1", "old1.jsonl")
    write(p, '{"role":"user","message":{}}\n{"role":"assistant","message":{}}\n' * 25, mtime=NOW - 10 * 86400)
    s = scan((roots[0], "/nonexistent"))
    assert p not in s.files
    write(p, '{"role":"assistant","message":{}}\n', mtime=NOW + 40)
    s.refresh(NOW + 40)     # past RESCAN_SECS: full walk
    snap = snapshot.build(s, "now", now=NOW + 40)
    assert snap["spectrum"]["sessions"]["values"][-1] == 1
    assert sum(r[sources.EVENTS] for r in s.files[p].bins.values()) == 1
    assert sum(r[sources.EVENTS] for r in s.files[p].est.values()) == 50   # dated 10 days ago


def test_file_created_while_running_counts_in_now(roots):
    os.utime(os.path.join(roots[0], CURSOR_FILE), (NOW - 600, NOW - 600))
    s = scan((roots[0], "/nonexistent"))
    p = os.path.join(roots[0], "projects", "Users-you-code-my-app", "agent-transcripts", "new1", "new1.jsonl")
    write(p, '{"role":"user","message":{}}\n{"role":"assistant","message":{}}\n', mtime=NOW + 35)
    s.refresh(NOW + 35)
    assert snapshot.build(s, "now", now=NOW + 35)["now"]["active"] == 1


def test_new_subagent_is_picked_up_between_full_walks(roots):
    s = scan(roots)
    p = os.path.join(roots[1], PROJ, SID, "subagents", "agent-new.jsonl")
    write(p, asst(NOW + 1, "msg_new", 500), mtime=NOW + 2)
    s.refresh(NOW + 2)      # not a full walk: only the hot set and hot sessions' subagent folders
    assert p in s.files
    assert rows(snapshot.build(s, "now", now=NOW + 2))["subagents"]["value"] == 1


def test_nothing_installed():
    s = snapshot.Scanner("/nonexistent-a", "/nonexistent-b")
    s.refresh(NOW)
    snap = snapshot.build(s, "now", now=NOW)
    r = rows(snap)
    assert r["tokens"]["value"] == 0 and r["tokens"]["led"] == "off"
    assert r["sessions"]["value"] == 0 and r["sessions"]["led"] == "off"
    assert snap["loading"] is False
    assert snap["readout"] == {"text": "No sessions", "led": "off", "tip": "No sessions open."}
    assert snap["deckText"] == {"big": "NO DATA", "small": ""}
    for key in ("tab", "deck", "live", "open", "hasLog"):
        assert key not in snap


# ---------------------------------------------------------------- spectrum and scales

@pytest.mark.parametrize("window,bucket,start", [("now", 30, "-5m"), ("1h", 360, "-1h"), ("week", 60480, "-7d")])
def test_spectrum_metric_per_window(roots, window, bucket, start):
    s = scan(roots)
    for metric in snapshot.METRICS:
        snap = snapshot.build(s, window, metric, now=NOW)
        assert snap["metric"] == metric
        assert snap["bucketSecs"] == bucket
        assert snap["axis"][0] == {"x": 0, "text": start} and snap["axis"][-1] == {"x": 1, "text": "now"}
        for m, sp in snap["spectrum"].items():
            assert len(sp["values"]) == len(sp["heights"]) == len(sp["tips"]) == 10
            assert len(sp["labels"]) == 4 and all(len(x) <= 2 for x in sp["labels"])
            assert all(0 <= h <= 1 for h in sp["heights"])
        assert snap["spectrum"]["tokens"]["tab"] == "Tokens/min ×1k"
        assert snap["spectrum"]["tokens"]["labels"] == ["4", "3", "2", "1"]     # the 4k/min floor
        assert snap["spectrum"]["sessions"]["tab"] == "Active sessions"
        assert len(snap["rows"]) == 5
        assert snap["deckTip"].endswith(", %s. Click to expand." % snapshot.SHOWN[window])
    tok = snapshot.build(s, window, "tokens", now=NOW)["spectrum"]["tokens"]
    assert sum(tok["values"]) == round(465 * 60 / bucket) or window == "week"
    assert tok["fullScale"] >= max(tok["values"])


def test_today_starts_at_first_event(roots):
    s = scan(roots)
    snap = snapshot.build(s, "today", now=NOW)
    # first event 12:01 UTC, floored to 12:00; the span is at least an hour, so it starts at end - 1 h
    start = datetime.fromtimestamp(NOW + 10 - 3600)
    assert snap["axis"][0]["text"] == "%d:%02d" % (start.hour, start.minute)
    assert snap["bucketSecs"] == 360
    assert sum(snap["spectrum"]["tokens"]["values"]) == pytest.approx(465 / 6, abs=1)   # per minute: 6 min buckets
    later = NOW + 3 * 3600      # three hours later the window starts at the first event
    s = scan(roots, later)
    snap = snapshot.build(s, "today", now=later)
    start = datetime.fromtimestamp(datetime.fromisoformat("2026-10-04T12:00:00+00:00").timestamp())
    assert snap["axis"][0]["text"] == "%d:%02d" % (start.hour, start.minute)
    assert snap["bucketSecs"] == 1120        # 3 h 5 min 10 s / 10, rounded up to the 10 s grid


def test_active_sessions_use_a_90s_lookback(roots):
    s = scan(("/nonexistent", roots[1]))
    vals = snapshot.build(s, "now", "sessions", now=NOW)["spectrum"]["sessions"]["values"]
    # events at 12:01:00 .. 12:03:40; buckets of 30 s from 12:00:10; each looks back 90 s
    assert vals == [0, 1, 1, 1, 1, 1, 1, 1, 1, 1]


def test_linear_height():
    assert snapshot.height(40000, 40000) == 1.0 and snapshot.height(90000, 40000) == 1.0
    assert snapshot.height(30000, 40000) == 0.75        # the 3/4 label row: twice as tall is twice the value
    assert snapshot.height(10000, 40000) == 0.25
    assert snapshot.height(1, 40000) == snapshot.STUB   # above 0 but under 2 px: a 2 px stub
    assert snapshot.height(0, 40000) == 0


def test_full_scale_rises_at_once_and_falls_one_step_a_minute():
    sc = {}
    k = ("now", "tokens")
    seen = {}
    for t in range(0, 124, 2):      # built on every 2 s poll
        target = 40000 if t == 0 else (80000 if t >= 123 - 1 else 4000)
        seen[t] = snapshot.stable(sc, k, target, snapshot.fs_down, t)
    assert seen[0] == 40000 and seen[30] == 40000
    assert seen[60] == 20000 and seen[100] == 20000     # one step down after a minute
    assert seen[120] == 12000 and seen[122] == 80000    # and up again at once
    assert snapshot.fs_up(2001, 4000) == 4000           # the tokens floor
    assert snapshot.fs_up(40001, 4000) == 80000 and snapshot.fs_up(80001, 4000) == 120000
    assert snapshot.fs_down(8) == 4 and snapshot.fs_down(4) == 4


def test_full_scale_of_a_window_not_shown_starts_over():
    sc = {("1h", "tokens"): (8_000_000, 0, 0)}
    assert snapshot.stable(sc, ("1h", "tokens"), 40000, snapshot.fs_down, 3600) == 40000


@pytest.mark.parametrize("fs,unit,mult,labels", [
    (4000, 1000, 1000, ["4", "3", "2", "1"]),
    (40000, 1000, 1000, ["40", "30", "20", "10"]),
    (80000, 1000, 1000, ["80", "60", "40", "20"]),
    (120000, 1000, 10000, ["12", "9", "6", "3"]),        # 80k -> 120k: the tab goes to x10k
    (800000, 1000, 10000, ["80", "60", "40", "20"]),
    (1200000, 1000, 100000, ["12", "9", "6", "3"]),      # 800k -> 1.2M: x100k
    (8, 1, 1, ["8", "6", "4", "2"]),
    (20, 1, 1, ["20", "15", "10", "5"]),
    (120, 1, 10, ["12", "9", "6", "3"]),
])
def test_scale_labels_are_integers_of_at_most_two_digits(fs, unit, mult, labels):
    assert fs in snapshot.FS_STEPS
    assert snapshot.scale_labels(fs, unit) == (mult, labels)


def test_full_scale_steps():
    assert snapshot.FS_STEPS[:12] == (4, 8, 12, 20, 40, 80, 120, 200, 400, 800, 1200, 2000)
    for fs in snapshot.FS_STEPS:
        assert fs % 4 == 0
        for unit in (1, 1000):
            if fs >= 4 * unit:
                assert all(len(x) <= 2 and x.isdigit() for x in snapshot.scale_labels(fs, unit)[1])


def test_tokens_tab_names_the_multiplier(roots):
    s = scan(("/nonexistent", roots[1]))
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 12, "big", 50000))          # 50k in one 30 s bucket: 100k/min
    s.refresh(NOW)
    sp = snapshot.build(s, "now", "tokens", now=NOW)["spectrum"]["tokens"]
    assert sp["fullScale"] == 120000 and sp["tab"] == "Tokens/min ×10k" and sp["labels"] == ["12", "9", "6", "3"]
    assert sp["tip"].endswith("Top of scale: 120k/min.")
    assert sp["values"][-1] == 100000 and sp["heights"][-1] == 0.833


def test_loading_is_per_window(roots):
    """Files are parsed newest first, so NOW is ready while older files of the week still wait."""
    s = snapshot.Scanner(*roots)
    s.apply(*s.listing(NOW), NOW, budget=0)
    assert s.backlog and snapshot.build(s, "now", now=NOW)["loading"] is True
    s.apply(*s.listing(NOW + 2), NOW + 2)
    s.backlog = [(NOW - 2 * 86400, 100, "/x/old.jsonl", "claude")]
    assert snapshot.build(s, "now", now=NOW + 2)["loading"] is False
    assert snapshot.build(s, "week", now=NOW + 2)["loading"] is True


def test_today_totals_start_at_midnight(roots, tmp_path):
    """Before 01:00 TODAY's spectrum spans the last hour, but its totals are today's only."""
    t = datetime(2026, 10, 5, 0, 20, 5).timestamp()     # local time
    p = os.path.join(roots[1], PROJ, "s2.jsonl")
    write(p, asst(t - 1800, "y1", 1000, sid="s2") + asst(t - 900, "t1", 10, sid="s2"), mtime=t)
    s = scan(("/nonexistent", roots[1]), t)
    snap = snapshot.build(s, "today", "tokens", now=t)
    assert rows(snap)["tokens"]["value"] == 10
    assert sum(snap["spectrum"]["tokens"]["values"]) == pytest.approx(1010 / 6, abs=1)   # the bars still cover the axis span
    assert snap["axis"][0]["text"] == "23:20"


def test_sessions_scale_labels(roots):
    snap = snapshot.build(scan(roots), "1h", "sessions", now=NOW)
    sp = snap["spectrum"]["sessions"]
    assert sp["fullScale"] == 4 and sp["labels"] == ["4", "3", "2", "1"]
    assert sp["heights"][-1] == 0.5                     # 2 of 4: half the track


def test_row_fill_is_log_scaled():
    assert snapshot.row_fill(0, 10, 0.5) == 0
    assert snapshot.row_fill(10, 10, 0.5) == 1.0
    assert 0.2 < snapshot.row_fill(1, 10, 0.5) < 0.3
    assert snapshot.row_fill(1, 5e5, 500) == 0.04     # never below a visible sliver


# ---------------------------------------------------------------- v3: axis, bar tooltips, readouts

def local(*a):
    return int(datetime(*a).timestamp())


def texts(ticks):
    return [t["text"] for t in ticks]


def test_axis_now_and_hour():
    end = local(2026, 10, 5, 20, 40, 10)
    now = snapshot.axis("now", end - 300, end, end - 300)
    assert texts(now) == ["-5m", "-4m", "-3m", "-2m", "-1m", "now"]
    assert [t["x"] for t in now] == [0, 0.2, 0.4, 0.6, 0.8, 1]
    hour = snapshot.axis("1h", end - 3600, end, end - 3600)
    assert texts(hour) == ["-1h", "-45m", "-30m", "-15m", "now"] and hour[2]["x"] == 0.5


def test_axis_today_picks_whole_clock_times():
    start, end = local(2026, 10, 5, 8, 30), local(2026, 10, 5, 14, 5, 10)
    ticks = snapshot.axis("today", start, end, start)
    # 1 h steps would give 6 labels; 2 h gives at most 4
    assert texts(ticks) == ["8:30", "10:00", "12:00", "14:00", "now"]
    assert ticks[1]["x"] == pytest.approx((local(2026, 10, 5, 10) - start) / (end - start), abs=1e-4)
    # right after midnight the 1 h minimum span reaches into yesterday
    end = local(2026, 10, 5, 0, 20, 10)
    assert texts(snapshot.axis("today", end - 3600, end, end - 3600)) == ["23:20", "23:30", "23:45", "0:00", "0:15", "now"]


def test_axis_week_names_each_day_at_noon():
    end = local(2026, 10, 5, 14, 5, 10)              # a Monday afternoon
    ticks = snapshot.axis("week", end - 7 * 86400, end, end - 7 * 86400)
    assert texts(ticks) == ["-7d", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon", "now"]
    noon = local(2026, 10, 5, 12)
    assert ticks[-2]["x"] == pytest.approx((noon - (end - 7 * 86400)) / (7 * 86400), abs=1e-4)


def test_bucket_ranges():
    t = local(2026, 10, 5, 20, 39, 30)
    assert snapshot.bucket_range("now", t, t + 30, False) == "20:39:30–20:40:00"
    assert snapshot.bucket_range("now", t, t + 30, True) == "20:39:30–now"
    assert snapshot.bucket_range("1h", t, t + 360, False) == "20:39–20:45"
    w = local(2026, 10, 6, 14, 24)                   # a Tuesday
    assert snapshot.bucket_range("week", w, w + 60480, False) == "Tue 14:24 – Wed 7:12"   # no leading zero, as the axis


def test_bar_tooltips_say_what_each_bucket_holds(roots):
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, user(NOW - 650))                       # Claude activity without tokens, 1H bucket 8
    os.utime(os.path.join(roots[0], CURSOR_FILE), (NOW - 900, NOW - 900))     # Cursor only, bucket 7
    s = scan(roots)
    sp = snapshot.build(s, "1h", "tokens", now=NOW)["spectrum"]
    tips = sp["tokens"]["tips"]
    assert tips[-1].split("\n")[1] == "465 tokens · 78/min"           # 6 min buckets
    assert tips[-1].split("\n")[0].endswith("–now")
    assert tips[8].split("\n")[1] == "no tokens"
    assert tips[7].split("\n")[1] == "Cursor activity, no usage data"  # the Cursor file, dated by its mtime
    assert tips[0].split("\n")[1] == "no activity"
    assert sp["sessions"]["tips"][-1].split("\n")[1] == "1 session active"
    assert sp["sessions"]["tips"][0].split("\n")[1] == "no activity"


def test_deck_and_readout_follow_the_graph(roots):
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 30, "fresh", 12000))
    s = scan(("/nonexistent", roots[1]))
    tok = snapshot.build(s, "week", "tokens", now=NOW)
    assert tok["now"] == {"active": 1, "open": 1, "rate": 12000}
    assert tok["deckText"] == {"big": "12k", "small": "/min"}
    assert tok["readout"]["tip"].endswith("12,000 output tokens in the last minute.")
    assert tok["deckTip"] == "Tokens/min, last 7 days. Click to expand."
    ses = snapshot.build(s, "week", "sessions", now=NOW)
    assert ses["deckText"] == {"big": "1", "small": "ACTIVE"}
    # an active session whose last minute had no tokens (a long tool call) reads 0/min, not IDLE
    later = NOW + 50                                # the record is 80 s old: still active
    assert snapshot.build(s, "now", "tokens", now=later)["deckText"] == {"big": "0", "small": "/min"}
    # a session Claude Code reports busy that wrote nothing in the lookback (a long tool call):
    # the last SESSIONS bar counts it too, so the bar, the deck and the tab agree
    agents = [A(9, "busy-sid", True, NOW - 300, "busy")]
    procs = sources.Procs(claude_pids=frozenset({9}))
    ses = snapshot.build(s, "now", "sessions", procs, agents, now=NOW)
    assert ses["deckText"] == {"big": "2", "small": "ACTIVE"} and ses["readout"]["text"] == "2 active · 2 open"
    assert ses["spectrum"]["sessions"]["values"][-1] == 2
    assert ses["spectrum"]["sessions"]["tips"][-1].endswith("2 sessions active")
    # loading: nothing parsed yet
    cold = snapshot.Scanner("/nonexistent", roots[1])
    snap = snapshot.build(cold, "now", "tokens", now=NOW)
    assert snap["deckText"]["big"] == "…" and snap["readout"]["text"] == "Loading…" and snap["menuTitle"] == ""


# ---------------------------------------------------------------- v3: chime, menu

A = sources.Agent


def test_stops_claude_busy_to_idle_or_waiting():
    st = snapshot.Stops()
    assert st.update([A(1, "s1", True, NOW - 100, "busy")], set(), NOW) == []
    assert st.update([A(1, "s1", False, NOW + 2, "idle")], set(), NOW + 2) == [("claude", "s1")]
    st = snapshot.Stops()                               # waiting on a permission prompt or a question
    st.update([A(3, "s3", True, NOW - 60, "busy")], set(), NOW)
    assert st.update([A(3, "s3", False, NOW, "waiting")], set(), NOW + 2) == [("claude", "s3")]


def test_stops_ignore_short_turns_exits_and_sessions_idle_at_launch():
    st = snapshot.Stops()
    st.update([A(2, "s2", True, 0, "busy")], set(), NOW)        # no statusUpdatedAt: busy from now
    assert st.update([A(2, "s2", False, 0, "idle")], set(), NOW + 4) == []      # busy 4 s < 15 s
    st.update([A(4, "s4", True, NOW - 60, "busy")], set(), NOW)
    assert st.update([], set(), NOW + 2) == []                  # the process exited
    assert snapshot.Stops().update([A(5, "s5", False, NOW - 9, "idle")], set(), NOW) == []


def test_stops_cursor_after_a_minute_of_work():
    st, k = snapshot.Stops(), ("cursor", "c1")
    st.update([], {k}, NOW)
    assert st.update([], set(), NOW + 40) == []                 # worked 40 s < 60 s
    st.update([], {k}, NOW + 100)
    st.update([], {k}, NOW + 160)
    assert st.update([], set(), NOW + 170) == [k]


def test_session_names(roots):
    s = scan(roots)
    claude, cursor = ("claude", SID), ("cursor", "0b7d2c1e-0000-4000-8000-000000000001")
    assert snapshot.session_names(s, [A(1, SID, True, 0, "busy", "brave-otter-12", "/x/y")], {claude}) == ["brave-otter-12"]
    assert snapshot.session_names(s, [A(1, SID, True, 0, "busy", "", "/x/my-app")], {claude}) == ["my-app"]
    # no session file: the transcript's project folder, without the home directory
    assert snapshot.session_names(s, [], {claude, cursor}) == ["code-my-app", "code-my-app"]


def test_menu_lines(roots):
    s = scan(("/nonexistent", roots[1]))
    agents = [A(1, SID, True, NOW - 30, "busy", "brave-otter-12", "/x")]
    working, opened = snapshot.live_state(s, sources.Procs(), agents, NOW)
    lines = snapshot.menu_lines(s, agents, working, opened, NOW)
    assert lines[0] == ("1 active · 1 open · 0 tokens/min", 0)
    assert lines[1][0].startswith("Today: ") and lines[1][0].endswith("465 tokens · 1 tool call · 0 errors")
    assert lines[2] == ("brave-otter-12", 1)
    write(os.path.join(roots[1], CLAUDE_FILE), asst(NOW - 20, "r1", 41000))
    s = scan(("/nonexistent", roots[1]))
    working, opened = snapshot.live_state(s, sources.Procs(), agents, NOW)
    assert snapshot.menu_lines(s, agents, working, opened, NOW)[0][0].endswith(" · 41k tokens/min")   # as the deck


def test_token_rate_covers_exactly_the_last_minute(roots):
    """10 s bins: the bin that is partly older than a minute counts for its part inside it, so a
    steady stream reads its true rate at any point in a bin and the value slides, not jumps."""
    p = os.path.join(roots[1], CLAUDE_FILE)
    for dt in (0, 3, 7, 9):            # 100 tokens every 2 s up to now: 3,000/min
        t = NOW + dt
        write(p, "".join(asst(t - 1 - 2 * k, "m%d" % k, 100) for k in range(60)), mtime=t, mode="w")
        rate = snapshot.token_rate(scan(("/nonexistent", roots[1]), t), t)
        assert 2900 <= rate <= 3100, (dt, rate)
    # a burst at 12:04:05 (bin 12:04:00-:10) and 1,000 tokens at 12:04:59
    write(p, asst(NOW - 55, "b", 7000) + asst(NOW - 1, "c", 1000), mode="w")
    s = scan(("/nonexistent", roots[1]))
    assert snapshot.token_rate(s, NOW) == 8000              # 12:05:00: its bin is all inside the minute
    assert snapshot.token_rate(s, NOW + 3) == 1000 + 4900   # 12:05:03: 7/10 of its bin is
    assert snapshot.token_rate(s, NOW + 10) == 1000         # 12:05:10: out


# ---------------------------------------------------------------- ps, names

PS = """  PID  %CPU    RSS COMM
  101  12.5 400000 /Applications/Cursor.app/Contents/MacOS/Cursor
  102   7.3 200000 /Applications/Cursor.app/Contents/Frameworks/Cursor Helper (Renderer).app/Contents/MacOS/Cursor Helper (Renderer)
  103  40.0  90000 /Users/you/Applications/CursorScope.app/Contents/MacOS/CursorScope
  104   3.0 300000 claude
  105  50.0 300000 /Applications/Claude.app/Contents/MacOS/Claude
  106   9.9  30000 /usr/bin/python3
  107   0.0  30000 /Users/you/.local/bin/claude
"""


def test_ps_ignores_macos_cursor_ui_service():
    """macOS always runs CursorUIViewService (text input); it is not the Cursor app."""
    ps = ("  PID  %CPU    RSS COMM\n"
          " 1079   0.0  14160 /System/Library/PrivateFrameworks/TextInputUIMacHelper.framework/Versions/A/"
          "XPCServices/CursorUIViewService.xpc/Contents/MacOS/CursorUIViewService\n"
          "  501   5.0   1000 /usr/bin/python3\n")
    p = sources.parse_ps(ps, own_pid=501)
    assert p.cursor_up is False and p.cursor_cpu == 0.0


def test_ps_cursor_cpu_and_claude_pids():
    p = sources.parse_ps(PS, own_pid=106)
    assert p.cursor_cpu == 19.8 and p.cursor_up is True
    assert p.claude_pids == frozenset({104, 107})        # the claude CLI, not Claude.app


def test_pretty_model():
    assert sources.pretty_model("claude-opus-5-5") == "Opus 5.5"
    assert sources.pretty_model("claude-opus-5") == "Opus 5"
    assert sources.pretty_model("claude-sonnet-4-5-20250929") == "Sonnet 4.5"
    assert sources.pretty_model("claude-fable-5-1") == "Fable 5.1"
    assert sources.pretty_model("claude-opus-4-6[1m]") == "Opus 4.6"
    assert sources.pretty_model("openai/gpt-5") == "gpt-5"


def test_identify():
    root = "/r"
    assert sources.identify("claude", root, "/r/projects/p/abc.jsonl") == ("abc", False)
    assert sources.identify("claude", root, "/r/projects/p/abc/subagents/agent-1.jsonl") == ("abc", True)
    assert sources.identify("claude", root, "/r/projects/p/abc/subagents/workflows/wf_1/agent-2.jsonl") == ("abc", True)
    assert sources.identify("cursor", root, "/r/projects/p/agent-transcripts/id/id.jsonl") == ("id", False)
    assert sources.identify("cursor", root, "/r/projects/p/agent-transcripts/id/subagents/s.jsonl") == ("id", True)
    assert sources.identify("cursor", root, "/r/projects/p/agent-transcripts/flat.jsonl") == ("flat", False)
