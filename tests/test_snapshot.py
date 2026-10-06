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


def usd(out, inp=3, read=50000, rates=(5, 25, 0.5)):
    """What asst() costs: input, cache read and output at (input, output, cache read) $/MTok;
    the default rates are Claude Opus 5's."""
    return (inp * rates[0] + read * rates[2] + out * rates[1]) / 1e6


# the fixture transcript: three Claude Opus 5 messages with 5-minute cache writes (no TTL split)
FIX_USD = ((5 * 5 + 2000 * 6.25 + 10000 * 0.5 + 120 * 25) + (7 * 5 + 500 * 6.25 + 12000 * 0.5 + 45 * 25)
           + (9 * 5 + 300 * 6.25 + 12500 * 0.5 + 300 * 25)) / 1e6       # $0.04648


def write(path, text, mtime=NOW, mode="a"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(text)
    os.utime(path, (mtime, mtime))


# ---------------------------------------------------------------- Claude Code

def test_claude_spend_tools_and_errors(roots):
    snap = snapshot.build(scan(("/nonexistent", roots[1])), "now", now=NOW)
    r = rows(snap)
    assert r["spend"]["value"] == pytest.approx(FIX_USD)  # input, cache writes and reads, output
    assert "465 output tokens" in r["spend"]["tip"] and "API list prices" in r["spend"]["tip"]
    assert r["tools"]["value"] == 1
    assert r["errors"]["value"] == 0                    # a failed tool result is routine, not an error
    assert r["errors"]["led"] == "green"
    assert r["sessions"]["value"] == 1                  # last record 80 s ago: working now
    assert snap["now"]["active"] == 1
    assert snap["menuTitle"] == "1 active"
    assert snap["readout"]["text"] == "1 active · 1 open" and snap["readout"]["led"] == "green"
    # spend is a rate, $/h: 30 s buckets, so the bucket totals times 120
    assert sum(snap["spectrum"]["spend"]["values"]) == pytest.approx(120 * FIX_USD, abs=0.02)
    assert "Models: Opus 5 100%." in r["spend"]["tip"]


def test_subagent_and_workflow_spend_is_included(roots):
    base = os.path.join(roots[1], PROJ, SID, "subagents")
    write(os.path.join(base, "agent-a1.jsonl"), user(NOW - 100) + asst(NOW - 90, "msg_sub_1", 700, tool="toolu_s1"))
    write(os.path.join(base, "workflows", "wf_1", "agent-a2.jsonl"),
          asst(NOW - 60, "msg_wf_1", 1000, model="claude-sonnet-5"))
    # metadata and the workflow journal are not transcripts
    write(os.path.join(base, "workflows", "wf_1", "journal.jsonl"), asst(NOW - 60, "msg_journal", 99999))
    write(os.path.join(base, "agent-a1.meta.json"), "{}")
    snap = snapshot.build(scan(roots), "now", now=NOW)
    r = rows(snap)
    opus, sonnet = FIX_USD + usd(700), usd(1000, rates=(2, 10, 0.2))
    assert r["spend"]["value"] == pytest.approx(opus + sonnet)
    assert "2,165 output tokens" in r["spend"]["tip"]
    assert r["subagents"]["value"] == 2
    assert r["tools"]["value"] == 2
    # model shares of the spend sit in the SPEND row tooltip, for the shown window
    assert "Models: Opus 5 82%, Sonnet 5 18%." in r["spend"]["tip"]
    assert "57% from subagents" in r["spend"]["tip"]
    # subagents fold into their parent: still one Claude session (plus one Cursor session)
    assert rows(snapshot.build(scan(roots), "1h", now=NOW))["sessions"]["value"] == 2


def test_streamed_duplicate_message_ids_count_once(roots):
    """One API message is written as one record per content block with the same message.id: the
    input and cache counts repeat and output_tokens grows. Per field the max counts, once."""
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 40, "msg_stream", 1) + asst(NOW - 35, "msg_stream", 1, tool="toolu_x"))
    s = scan(("/nonexistent", roots[1]))
    assert rows(snapshot.build(s, "now", now=NOW))["spend"]["value"] == pytest.approx(FIX_USD + usd(1))
    write(p, asst(NOW - 20, "msg_stream", 250, tool="toolu_x"), mtime=NOW + 2)   # same tool block repeated
    s.refresh(NOW + 2)
    snap = snapshot.build(s, "now", now=NOW + 2)
    assert rows(snap)["spend"]["value"] == pytest.approx(FIX_USD + usd(250))     # the cache read once
    assert "715 output tokens" in rows(snap)["spend"]["tip"]
    assert rows(snap)["tools"]["value"] == 1 + 1
    # each record adds what is new at its own time: input, cache and 1 output token land at -40 s,
    # 249 output tokens at -20 s
    vals = snap["spectrum"]["spend"]["values"]
    assert vals[-2:] == pytest.approx([120 * usd(1), 120 * 249 * 25 / 1e6], abs=0.01)   # $/h
    assert snap["spectrum"]["spend"]["tips"][-1].endswith("\n$0.01 · $0.7/h\n249 output tokens")


def test_cost_of_a_message_from_its_usage():
    """Input, 5-minute and 1-hour cache writes, cache reads and output at the model's list prices,
    plus web searches; fast mode doubles the token part."""
    u = {"input_tokens": 10, "cache_creation_input_tokens": 3000, "cache_read_input_tokens": 100000,
         "cache_creation": {"ephemeral_5m_input_tokens": 1000, "ephemeral_1h_input_tokens": 2000},
         "output_tokens": 500, "server_tool_use": {"web_search_requests": 2}}
    v = sources.usage(u)
    assert v == (10, 1000, 2000, 100000, 500, 2)
    rates, exact = sources.price("claude-opus-5-5")
    assert exact and rates == (4, 20, 0.20)
    tokens = (10 * 4 + 1000 * 5 + 2000 * 8 + 100000 * 0.20 + 500 * 20) / 1e6
    assert sources.usd(rates, v) == pytest.approx(tokens + 0.02)
    assert sources.usd(rates, v, 2.0) == pytest.approx(2 * tokens + 0.02)
    # no TTL split: the write is priced as the default 5-minute one
    del u["cache_creation"]
    assert sources.usage(u)[1:3] == (3000, 0)
    assert sources.usd(sources.price("claude-fable-5-1")[0], (0, 0, 0, 1_000_000, 0, 0)) == pytest.approx(0.25)
    assert sources.usage(None) == (0,) * 6


def test_cache_fields_and_ttl_split_count_once_per_streamed_message(roots):
    p = os.path.join(roots[1], CLAUDE_FILE)
    rec = json.loads(asst(NOW - 30, "msg_1h", 100, model="claude-opus-5-5"))
    rec["message"]["usage"].update({"cache_creation_input_tokens": 4000,
                                    "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 4000}})
    write(p, compact(rec))
    rec["message"]["usage"]["output_tokens"] = 300           # the next block of the same message
    write(p, compact(rec))
    snap = snapshot.build(scan(("/nonexistent", roots[1])), "now", now=NOW)
    want = (3 * 4 + 4000 * 8 + 50000 * 0.20 + 300 * 20) / 1e6
    assert rows(snap)["spend"]["value"] == pytest.approx(FIX_USD + want)
    assert "Opus 5.5" in rows(snap)["spend"]["tip"]


def test_model_prices_by_id_and_family_fallback(roots):
    price = sources.price
    assert price("claude-haiku-4-5-20251001") == ((1, 5, 0.10), True)
    assert price("claude-opus-4-6[1m]") == ((5, 25, 0.50), True)
    assert price("claude-opus-4-5@20251101") == ((5, 25, 0.50), True)
    assert price("us.anthropic.claude-sonnet-4-5-v1:0") == ((3, 15, 0.30), True)
    assert price("claude-opus-4-20250514") == ((15, 75, 1.50), True)
    assert price("claude-sonnet-5") == ((2, 10, 0.20), True) and price("claude-fable-5") == ((10, 50, 1), True)
    # the older version-first form and the -0 aliases
    assert price("claude-3-5-haiku-20241022") == ((0.80, 4, 0.08), True)
    assert price("claude-opus-4-0") == ((15, 75, 1.50), True) and price("claude-sonnet-4-0") == ((3, 15, 0.30), True)
    # a version not in the table: the newest price of its family, marked as an estimate
    assert price("claude-opus-6") == (sources.PRICES["opus-5-5"], False)
    assert price("claude-sonnet-9-1") == (sources.PRICES["sonnet-5-5"], False)
    assert price("gpt-5") is None and price("<synthetic>") is None
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 30, "u1", 1000, model="claude-sonnet-9") + asst(NOW - 20, "u2", 1000, model="glm-4.6"))
    r = rows(snapshot.build(scan(("/nonexistent", roots[1])), "now", now=NOW))["spend"]
    assert r["value"] == pytest.approx(FIX_USD + usd(1000, rates=(2, 10, 0.2)))   # glm: no price, $0
    assert "Sonnet 9 " in r["tip"] and "(estimate)" in r["tip"] and "glm-4.6 (no price)" in r["tip"]


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
    assert r["spend"]["value"] == pytest.approx(FIX_USD)
    assert "Models: Opus 5 100%." in r["spend"]["tip"]  # <synthetic> adds nothing, costs $0
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
    snap = snapshot.build(s, "now", "spend", procs=procs, agents=idle, now=later)
    r = rows(snap)["sessions"]
    assert r["value"] == 0 and r["led"] == "amber"
    assert snap["readout"] == {"text": "Idle · 1 open", "led": "amber",
                               "tip": "No session working now, 1 open. Spend in the last minute: $0.00 ($0/h, approximate)."}
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
    assert rows(snap)["spend"]["value"] == pytest.approx(FIX_USD)


def test_now_excludes_yesterday(roots):
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 86400, "msg_old", 9999, sid="old"))
    s = scan(("/nonexistent", roots[1]))
    assert rows(snapshot.build(s, "now", now=NOW))["spend"]["value"] == pytest.approx(FIX_USD)
    assert rows(snapshot.build(s, "week", now=NOW))["spend"]["value"] == pytest.approx(FIX_USD + usd(9999))


# ---------------------------------------------------------------- Cursor and merging

def test_merged_sessions_from_both_sources(roots):
    s = scan(roots)
    snap = snapshot.build(s, "1h", now=NOW)
    assert rows(snap)["sessions"]["value"] == 2         # one Claude + one Cursor session
    assert max(snap["spectrum"]["sessions"]["values"]) == 2
    assert rows(snap)["tools"]["value"] == 1 + 2       # Claude tool_use + Cursor tool_use blocks
    text = json.dumps(snap).lower()
    assert '"cursor"' not in text and '"claude"' not in text   # nothing keyed by source


def test_cursor_only_has_no_spend_and_defaults_to_sessions(roots):
    p = os.path.join(roots[0], CURSOR_FILE)
    os.utime(p, (NOW - 600, NOW - 600))
    s = scan((roots[0], "/nonexistent"))
    hour = snapshot.build(s, "1h", now=NOW)
    t = rows(hour)["spend"]
    assert t["value"] is None and t["fill"] == 0 and t["led"] == "off"
    assert "Cursor does not report usage" in t["tip"]
    assert hour["metric"] == "sessions"                 # the only spectrum Cursor can fill
    assert hour["spectrum"]["spend"]["known"] is False
    assert hour["now"]["rate"] is None                  # no source reports usage
    assert "Cursor activity, no usage data" in "".join(hour["spectrum"]["spend"]["tips"])
    assert snapshot.build(s, "1h", "spend", now=NOW)["deckText"] == {"big": "NO DATA", "small": ""}
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
    assert r["spend"]["value"] == 0 and r["spend"]["led"] == "off"
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
            assert len(sp["labels"]) == 4 and all(len(x.lstrip("$")) <= 2 for x in sp["labels"])
            assert all(0 <= h <= 1 for h in sp["heights"])
        assert snap["spectrum"]["spend"]["tab"] == "Spend $/h"
        assert snap["spectrum"]["spend"]["labels"] == ["$20", "$15", "$10", "$5"]     # the $20/h floor
        assert snap["spectrum"]["sessions"]["labels"][0].isdigit()
        assert snap["spectrum"]["sessions"]["tab"] == "Active sessions"
        assert len(snap["rows"]) == 5
        assert snap["deckTip"].endswith(", %s. Click to expand." % snapshot.SHOWN[window])
    sp = snapshot.build(s, window, "spend", now=NOW)["spectrum"]["spend"]
    assert sum(sp["values"]) == pytest.approx(FIX_USD * 3600 / bucket, abs=0.02)
    assert sp["fullScale"] >= max(sp["values"])


def test_today_runs_from_midnight_to_now(roots):
    """TODAY always starts at local midnight, also long before the first event of the day."""
    s = scan(roots)
    snap = snapshot.build(s, "today", now=NOW)
    mid = snapshot.midnight(NOW)
    end = NOW + 10                                   # the end of the current 10 s bin
    assert snap["axis"][0] == {"x": 0, "text": "0:00"} and snap["axis"][-1]["text"] == "now"
    assert snap["bucketSecs"] == pytest.approx((end - mid) / 10)
    sp = snap["spectrum"]["spend"]
    assert sum(sp["values"]) == pytest.approx(FIX_USD * 3600 / snap["bucketSecs"], abs=0.02)
    assert rows(snap)["spend"]["value"] == pytest.approx(FIX_USD)


def test_today_right_after_midnight(roots):
    """Seconds and minutes after midnight TODAY covers only today: bars and totals the same span."""
    p = os.path.join(roots[1], PROJ, "s2.jsonl")
    mid = local(2026, 10, 5)
    for t, buckets, first in ((mid + 30, 10, "0:00:00–0:00:10"), (mid + 20 * 60 + 5, 121, "0:00–0:02")):
        write(p, asst(mid - 1800, "y1", 1000, sid="s2") + asst(mid - 5, "y2", 1000, sid="s2")
              + asst(t - 25, "t1", 10, sid="s2"), mtime=t, mode="w")
        s = scan(("/nonexistent", roots[1]), t)
        snap = snapshot.build(s, "today", "spend", now=t)
        assert snap["axis"][0]["text"] == "0:00" and snap["bucketSecs"] == buckets   # 10 bins at least
        sp = snap["spectrum"]["spend"]
        assert rows(snap)["spend"]["value"] == pytest.approx(usd(10))             # nothing from yesterday
        assert sum(v * buckets / 3600 for v in sp["values"]) == pytest.approx(usd(10), abs=1e-4)
        assert sp["tips"][0].startswith(first)          # seconds while the bars are under a minute
    assert texts(snap["axis"]) == ["0:00", "0:05", "0:10", "0:15", "0:20", "now"]


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


def test_spend_tab_names_the_multiplier(roots):
    s = scan(("/nonexistent", roots[1]))
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 12, "big", 40000))          # $1.03 in one 30 s bucket: $123/h
    s.refresh(NOW)
    sp = snapshot.build(s, "now", "spend", now=NOW)["spectrum"]["spend"]
    assert sp["fullScale"] == 200 and sp["tab"] == "Spend $/h ×10" and sp["labels"] == ["$20", "$15", "$10", "$5"]
    assert sp["tip"].endswith("Top of scale: $200/h.") and "Approximate API cost" in sp["tip"]
    assert sp["values"][-1] == pytest.approx(120 * usd(40000), abs=0.01) and sp["heights"][-1] == 0.615


def test_loading_is_per_window(roots):
    """Files are parsed newest first, so NOW is ready while older files of the week still wait."""
    s = snapshot.Scanner(*roots)
    s.apply(*s.listing(NOW), NOW, budget=0)
    assert s.backlog and snapshot.build(s, "now", now=NOW)["loading"] is True
    s.apply(*s.listing(NOW + 2), NOW + 2)
    s.backlog = [(NOW - 2 * 86400, 100, "/x/old.jsonl", "claude")]
    assert snapshot.build(s, "now", now=NOW + 2)["loading"] is False
    assert snapshot.build(s, "week", now=NOW + 2)["loading"] is True


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
    now = snapshot.axis("now", end - 300, end)
    assert texts(now) == ["-5m", "-4m", "-3m", "-2m", "-1m", "now"]
    assert [t["x"] for t in now] == [0, 0.2, 0.4, 0.6, 0.8, 1]
    hour = snapshot.axis("1h", end - 3600, end)
    assert texts(hour) == ["-1h", "-45m", "-30m", "-15m", "now"] and hour[2]["x"] == 0.5


def test_axis_today_picks_whole_clock_times():
    mid, end = local(2026, 10, 5), local(2026, 10, 5, 14, 5, 10)
    ticks = snapshot.axis("today", mid, end)
    # 2 h steps would give 7 labels; 3 h gives at most 4
    assert texts(ticks) == ["0:00", "3:00", "6:00", "9:00", "12:00", "now"]
    assert ticks[1]["x"] == pytest.approx(3 * 3600 / (end - mid), abs=1e-4)
    # right after midnight: 5 min steps, or no interior label at all
    assert texts(snapshot.axis("today", mid, mid + 20 * 60 + 10)) == ["0:00", "0:05", "0:10", "0:15", "0:20", "now"]
    assert texts(snapshot.axis("today", mid, mid + 100)) == ["0:00", "now"]


def test_axis_week_names_each_day_at_noon():
    end = local(2026, 10, 5, 14, 5, 10)              # a Monday afternoon
    ticks = snapshot.axis("week", end - 7 * 86400, end)
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
    sp = snapshot.build(s, "1h", "spend", now=NOW)["spectrum"]
    tips = sp["spend"]["tips"]
    assert tips[-1].split("\n")[1:] == ["$0.05 · $0.5/h", "465 output tokens"]   # 6 min buckets
    assert tips[-1].split("\n")[0].endswith("–now")
    assert tips[8].split("\n")[1] == "no spend"
    assert tips[7].split("\n")[1] == "Cursor activity, no usage data"  # the Cursor file, dated by its mtime
    assert tips[0].split("\n")[1] == "no activity"
    assert sp["sessions"]["tips"][-1].split("\n")[1] == "1 session active"
    assert sp["sessions"]["tips"][0].split("\n")[1] == "no activity"


def test_deck_and_readout_follow_the_graph(roots):
    p = os.path.join(roots[1], CLAUDE_FILE)
    write(p, asst(NOW - 30, "fresh", 12000))
    s = scan(("/nonexistent", roots[1]))
    sp = snapshot.build(s, "week", "spend", now=NOW)
    assert sp["now"]["rate"] == pytest.approx(60 * usd(12000))           # $/h over the last minute: $19.50
    assert sp["now"]["active"] == 1 and sp["now"]["open"] == 1
    assert sp["deckText"] == {"big": "$20", "small": "/h"}
    assert sp["readout"]["tip"].endswith("Spend in the last minute: $0.33 ($20/h, approximate).")
    assert sp["deckTip"] == "Spend $/h (approximate API cost; Cursor reports no usage), last 7 days. Click to expand."
    ses = snapshot.build(s, "week", "sessions", now=NOW)
    assert ses["deckText"] == {"big": "1", "small": "ACTIVE"}
    # an active session whose last minute had no spend (a long tool call) reads $0/h, not IDLE
    later = NOW + 50                                # the record is 80 s old: still active
    assert snapshot.build(s, "now", "spend", now=later)["deckText"] == {"big": "$0", "small": "/h"}
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
    snap = snapshot.build(cold, "now", "spend", now=NOW)
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
    assert lines[0] == ("1 active · 1 open · $0/h", 0)
    assert lines[1][0].startswith("Today: ") and lines[1][0].endswith("$0.05 at API prices · 1 tool call · 0 errors")
    assert lines[2] == ("brave-otter-12", 1)
    write(os.path.join(roots[1], CLAUDE_FILE), asst(NOW - 20, "r1", 41000))
    s = scan(("/nonexistent", roots[1]))
    working, opened = snapshot.live_state(s, sources.Procs(), agents, NOW)
    assert snapshot.menu_lines(s, agents, working, opened, NOW)[0][0].endswith(" · $63/h")   # as the deck


def test_spend_rate_covers_exactly_the_last_minute(roots):
    """10 s bins: the bin that is partly older than a minute counts for its part inside it, so a
    steady stream reads its true rate at any point in a bin and the value slides, not jumps."""
    p = os.path.join(roots[1], CLAUDE_FILE)
    for dt in (0, 3, 7, 9):            # a message every 2 s up to now: 30 a minute
        t = NOW + dt
        write(p, "".join(asst(t - 1 - 2 * k, "m%d" % k, 100) for k in range(60)), mtime=t, mode="w")
        rate = snapshot.spend_rate(scan(("/nonexistent", roots[1]), t), t)
        assert rate == pytest.approx(60 * 30 * usd(100), rel=0.02), dt          # $/h
    # a burst at 12:04:05 (bin 12:04:00-:10) and one message at 12:04:59
    write(p, asst(NOW - 55, "b", 7000) + asst(NOW - 1, "c", 1000), mode="w")
    s = scan(("/nonexistent", roots[1]))
    assert snapshot.spend_rate(s, NOW) == pytest.approx(60 * (usd(7000) + usd(1000)))         # 12:05:00: all inside
    assert snapshot.spend_rate(s, NOW + 3) == pytest.approx(60 * (0.7 * usd(7000) + usd(1000)))   # 7/10 of its bin
    assert snapshot.spend_rate(s, NOW + 10) == pytest.approx(60 * usd(1000))                  # 12:05:10: out


def test_today_is_the_default_window(roots):
    s = scan(roots)
    assert snapshot.build(s, now=NOW)["window"] == "today"
    assert snapshot.build(s, "bogus", now=NOW)["window"] == "today"
    assert snapshot.build(s, now=NOW)["metric"] == "spend"


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
