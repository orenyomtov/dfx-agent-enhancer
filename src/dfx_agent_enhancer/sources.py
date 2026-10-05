"""Read-only data sources: Claude Code and Cursor transcripts, Claude's live session files, ps.

Nothing here writes anywhere or touches the network. Transcripts are reduced to 10-second
bins per file as they are read; no raw events are kept.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from typing import NamedTuple

from . import env

CURSOR = "cursor"
CLAUDE = "claude"
BIN = 10                 # seconds per bin
RECENT_IDS = 16          # streamed message ids / tool ids remembered per file (repeats are adjacent)

HEAD = 1024              # bytes of a Claude line searched for its record type

OUT, TOOLS, ERRORS, EVENTS, COST = range(5)

# Anthropic API list prices, $ per million tokens: (input, output, cache read). Cache writes are
# 1.25x input (5-minute TTL) and 2x input (1-hour TTL) for every model. Fast mode is 2x and US-only
# inference (inference_geo "us") 1.1x on every token type; web search is $10 per 1,000 searches.
# Source: platform.claude.com/docs/en/about-claude/pricing, read 2026-10-06. This is what the usage
# would cost on the API, not what a Claude subscription charges.
PRICES = {
    "fable-5-1": (10, 50, 0.25), "mythos-5-1": (10, 50, 0.25), "fable-5": (10, 50, 1), "mythos-5": (10, 50, 1),
    "opus-5-5": (4, 20, 0.20), "opus-5": (5, 25, 0.50), "opus-4-8": (5, 25, 0.50), "opus-4-7": (5, 25, 0.50),
    "opus-4-6": (5, 25, 0.50), "opus-4-5": (5, 25, 0.50), "opus-4-1": (15, 75, 1.50), "opus-4": (15, 75, 1.50),
    "sonnet-5-5": (2, 10, 0.20), "sonnet-5": (2, 10, 0.20), "sonnet-4-6": (3, 15, 0.30), "sonnet-4-5": (3, 15, 0.30),
    "sonnet-4": (3, 15, 0.30), "haiku-4-5": (1, 5, 0.10), "haiku-3-5": (0.80, 4, 0.08),
}
# an id not in the table is priced as the newest model of its family, and shown as an estimate
FAMILY = {"fable": "fable-5-1", "mythos": "mythos-5-1", "opus": "opus-5-5", "sonnet": "sonnet-5-5", "haiku": "haiku-4-5"}
SEARCH_USD = 0.01
_priced: dict = {}


def price(model: str):
    """(rates, exact) for a model id, or None when it names no Claude family. Handles dated, [1m],
    Bedrock and Vertex forms: claude-haiku-4-5-20251001, claude-opus-4-6[1m], claude-opus-4-5@20251101,
    the older version-first form claude-3-5-haiku-20241022, and aliases like claude-opus-4-0 (= opus-4)."""
    if model not in _priced:
        fam = "(fable|mythos|opus|sonnet|haiku)"
        m = re.search(fam + r"-(\d{1,2})(?!\d)(?:-(\d)(?!\d))?", model or "")
        if m:
            f, major, minor = m.groups()
        else:
            m = re.search(r"(?<!\d)(\d{1,2})(?:-(\d))?-" + fam, model or "")
            major, minor, f = m.groups() if m else (None, None, None)
        key = f and "-".join([f, major] + ([minor] if minor and minor != "0" else []))
        if key in PRICES:
            _priced[model] = (PRICES[key], True)
        else:
            f = re.search("|".join(FAMILY), (model or "").lower())
            _priced[model] = (PRICES[FAMILY[f.group(0)]], False) if f else None
    return _priced[model]


def usage(u) -> tuple:
    """(input, 5m cache write, 1h cache write, cache read, output, web searches) from message.usage.
    Without the cache_creation split, a cache write is priced as the default 5-minute one."""
    def g(d, k):
        v = d.get(k) if isinstance(d, dict) else None
        return v if isinstance(v, int) and v > 0 else 0
    if not isinstance(u, dict):
        return (0,) * 6
    write = g(u, "cache_creation_input_tokens")
    w1h = min(write, g(u.get("cache_creation"), "ephemeral_1h_input_tokens"))
    return (g(u, "input_tokens"), write - w1h, w1h, g(u, "cache_read_input_tokens"), g(u, "output_tokens"),
            g(u.get("server_tool_use"), "web_search_requests"))


def usd(rates, v, mult: float = 1.0) -> float:
    """Dollars for a usage tuple at the given (input, output, cache read) rates."""
    i, o, r = rates
    return mult * (v[0] * i + v[1] * i * 1.25 + v[2] * i * 2 + v[3] * r + v[4] * o) / 1e6 + v[5] * SEARCH_USD


# ---------------------------------------------------------------- roots

def cursor_root() -> str:
    return os.path.expanduser(env("CURSOR_ROOT") or "~/.cursor")


def claude_root() -> str:
    return os.path.expanduser(
        env("CLAUDE_ROOT")
        or os.environ.get("CLAUDE_CONFIG_DIR")
        or "~/.claude"
    )


# ---------------------------------------------------------------- listing

def _scan(d: str):
    try:
        with os.scandir(d) as it:
            return list(it)
    except OSError:
        return []


def _add(e, out: list, kind: str) -> None:
    try:
        st = e.stat(follow_symlinks=False)
        out.append((st.st_mtime, st.st_size, e.path, kind))
    except OSError:
        pass


def _walk(top: str, out: list, kind: str, want) -> None:
    """Collect files under top whose name passes want(name). Never follows symlinks."""
    stack = [top]
    while stack:
        for e in _scan(stack.pop()):
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                elif want(e.name) and e.is_file(follow_symlinks=False):
                    _add(e, out, kind)
            except OSError:
                continue


def _agent_file(name: str) -> bool:
    return name.startswith("agent-") and name.endswith(".jsonl")


def claude_session_dir(path: str) -> str | None:
    """projects/<proj>/<sid>.jsonl -> projects/<proj>/<sid>/subagents (where its agents live)."""
    if os.sep + "subagents" + os.sep in path:
        return None
    return path[:-len(".jsonl")] + os.sep + "subagents"


def walk_subagents(d: str, out: list) -> None:
    """Task and workflow agent transcripts of one Claude session (skips journal.jsonl)."""
    _walk(d, out, CLAUDE, _agent_file)


def list_transcripts(kind: str, root: str) -> list[tuple[float, int, str, str]]:
    """All transcript files of a source as (mtime, size, path, kind), newest first.

    Claude: projects/*/<sid>.jsonl and projects/*/<sid>/subagents/**/agent-*.jsonl.
    Cursor: projects/*/agent-transcripts/**/*.jsonl (subagents/ included).
    """
    out: list = []
    projects = os.path.join(root, "projects")
    for p in _scan(projects):
        try:
            if not p.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if kind == CURSOR:
            at = os.path.join(p.path, "agent-transcripts")
            if os.path.isdir(at) and not os.path.islink(at):
                _walk(at, out, CURSOR, lambda n: n.endswith(".jsonl"))
            continue
        for e in _scan(p.path):
            try:
                if e.name.endswith(".jsonl") and e.is_file(follow_symlinks=False):
                    _add(e, out, CLAUDE)
                elif e.is_dir(follow_symlinks=False):
                    sub = os.path.join(e.path, "subagents")
                    if os.path.isdir(sub):
                        walk_subagents(sub, out)
            except OSError:
                continue
    out.sort(reverse=True)
    return out


def identify(kind: str, root: str, path: str) -> tuple[str, bool]:
    """(session key, is a subagent) from a transcript's path. Subagents fold into their parent."""
    parts = os.path.relpath(path, os.path.join(root, "projects")).split(os.sep)
    if kind == CLAUDE:
        # [proj, sid.jsonl] or [proj, sid, subagents, ..., agent-x.jsonl]
        sid = parts[1] if len(parts) > 2 else os.path.splitext(parts[-1])[0]
        return sid, len(parts) > 2
    # [proj, agent-transcripts, id.jsonl | id/id.jsonl | id/subagents/x.jsonl]
    sid = os.path.splitext(parts[2])[0] if len(parts) > 2 else os.path.splitext(parts[-1])[0]
    return sid, "subagents" in parts[3:-1]


# ---------------------------------------------------------------- parsing

def _iso(ts) -> float | None:
    if isinstance(ts, bytes):
        try:
            ts = ts.decode()
        except UnicodeDecodeError:
            return None
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _value(raw: bytes, key: bytes, last: bool = False) -> bytes | None:
    """The string value of the first (or last) occurrence of a key, without parsing the line."""
    i = raw.rfind(key) if last else raw.find(key)
    if i < 0:
        return None
    i += len(key)
    while raw[i:i + 1] in (b" ", b":"):
        i += 1
    if raw[i:i + 1] != b'"':
        return None
    j = raw.find(b'"', i + 1)
    return raw[i + 1:j] if j > 0 else None


class FileState:
    """One transcript, read incrementally (JSONL is append-only) into 10 s bins.

    bins:   {bin: [reported output tokens, tool calls, errors, user/assistant events, $ at list prices]}
    est:    the same for Cursor lines that were already on disk when first read; they are
            dated by the file mtime of that moment and never count in NOW or as live
    models: {model: {bin: [reported output tokens, $]}}
    """

    __slots__ = ("path", "kind", "session", "sub", "mtime", "size", "offset", "old",
                 "bins", "est", "models", "msgs", "tools", "last")

    def __init__(self, path: str, kind: str, session: str, sub: bool,
                 old: tuple[float, int] | None = None):
        self.path = path
        self.kind = kind
        self.session = session
        self.sub = sub
        self.mtime = 0.0
        self.size = -1
        self.offset = 0
        # (mtime, size) of the file when the app first knew about it. Cursor records carry no
        # timestamp: those in the first `size` bytes get that mtime and go to `est`; records
        # appended later get the time they were seen. None: everything on disk at the first
        # read is old (files present at startup). (0.0, 0): a file created while running.
        self.old = old
        self._reset()

    def _reset(self) -> None:
        self.offset = 0
        self.bins: dict[int, list[int]] = {}
        self.est: dict[int, list[int]] = {}
        self.models: dict[str, dict[int, list]] = {}
        self.msgs: dict[str, tuple] = {}    # message.id -> max usage seen (see usage()), recent ids only
        self.tools: dict[str, None] = {}    # recent tool_use ids
        self.last = 0.0                     # newest user/assistant record time (not estimated)

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.session)

    # ------------------------------------------------------------ accumulation
    def _row(self, ts: float, est: bool = False) -> list[int]:
        b = int(ts // BIN)
        d = self.est if est else self.bins
        r = d.get(b)
        if r is None:
            r = d[b] = [0, 0, 0, 0, 0.0]
        return r

    def _event(self, ts: float, est: bool = False) -> list[int]:
        r = self._row(ts, est)
        r[EVENTS] += 1
        if not est and ts > self.last:
            self.last = ts
        return r

    @staticmethod
    def _remember(d: dict, k, v) -> None:
        d.pop(k, None)
        d[k] = v
        if len(d) > RECENT_IDS:
            del d[next(iter(d))]

    def _tool(self, r: list[int], tid) -> None:
        if isinstance(tid, str):
            if tid in self.tools:
                return
            self._remember(self.tools, tid, None)
        r[TOOLS] += 1

    # ------------------------------------------------------------ Claude Code
    def _claude(self, raw: bytes) -> None:
        # The role sits in the first ~200 bytes of an assistant record (measured: never past 201),
        # so only the head is searched; a big tool result is never scanned end to end.
        if b'"assistant"' in raw[:HEAD]:
            # assistant records (and the odd user record that quotes the word): full parse
            try:
                o = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                return
            if not isinstance(o, dict):
                return
            t = o.get("type")
            if t == "user":
                ts = _iso(o.get("timestamp"))
                if ts is not None:
                    self._event(ts)
            elif t == "assistant":
                self._assistant(o)
            return
        # Fast path for user records: the top-level "type" is the first one on the line and
        # the top-level "timestamp" comes after the content, so rfind gets it without a parse.
        if _value(raw[:HEAD], b'"type"') != b"user":
            return
        ts = _iso(_value(raw, b'"timestamp"', last=True))
        if ts is not None:
            self._event(ts)

    def _assistant(self, o: dict) -> None:
        ts = _iso(o.get("timestamp"))
        if ts is None:
            return
        r = self._event(ts)
        if o.get("isApiErrorMessage"):
            r[ERRORS] += 1
        m = o.get("message")
        if not isinstance(m, dict):
            return
        model = m.get("model") if isinstance(m.get("model"), str) else ""
        u = m.get("usage")
        v = usage(u)
        if any(v) and model != "<synthetic>":
            # Streaming writes one record per content block, all with the same message.id: the
            # input and cache counts repeat and output_tokens grows. Each record adds what is new
            # over the max seen for that id (per field), so a message counts once and its output
            # lands when it was produced.
            mid = m.get("id")
            prev = self.msgs.get(mid) if isinstance(mid, str) else None
            if prev is not None:
                v = tuple(map(max, v, prev))
            if isinstance(mid, str):
                self._remember(self.msgs, mid, v)
            pr = price(model)
            mult = (2.0 if u.get("speed") == "fast" else 1.0) * (1.1 if u.get("inference_geo") == "us" else 1.0)
            cost = 0.0 if pr is None else usd(pr[0], v, mult) - (usd(pr[0], prev, mult) if prev else 0.0)
            delta = v[4] - (prev[4] if prev else 0)
            if delta or cost:
                r[OUT] += delta
                r[COST] += cost
                mb = self.models.setdefault(model, {})
                c = mb.get(int(ts // BIN))
                if c is None:
                    c = mb[int(ts // BIN)] = [0, 0.0]
                c[0] += delta
                c[1] += cost
        content = m.get("content")
        # <synthetic> records (API errors, and replays written when a session resumes) repeat
        # earlier tool_use blocks with their old ids; measured over a week, none was new
        if isinstance(content, list) and model != "<synthetic>":
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    self._tool(r, c.get("id"))

    # ------------------------------------------------------------ Cursor
    def _cursor(self, raw: bytes, ts: float, est: bool) -> None:
        try:
            o = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(o, dict):
            return
        role = o.get("role") or o.get("type")
        if role in ("user", "assistant", "tool_use"):
            r = self._event(ts, est)
            if role == "tool_use":
                r[TOOLS] += 1
            m = o.get("message")
            content = m.get("content") if isinstance(m, dict) else None
            if role == "assistant" and isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        self._tool(r, c.get("id"))
        elif role == "turn_ended" and o.get("status") == "error":
            self._row(ts, est)[ERRORS] += 1

    # ------------------------------------------------------------ reading
    def refresh(self, mtime: float, size: int, now: float, skipped: list) -> None:
        if mtime == self.mtime and size == self.size:
            return
        if size < self.offset or (size == self.size and mtime != self.mtime):
            self._reset()       # truncated or rewritten: start over
        if self.kind == CURSOR and self.old is None:
            self.old = (mtime, size)
        old_mtime, old_size = self.old or (0.0, 0)
        claude = self.kind == CLAUDE
        pos = self.offset
        try:
            # line by line, so a 50 MB transcript never sits in memory at once
            with open(self.path, "rb") as f:
                f.seek(pos)
                for raw in f:
                    if raw[-1:] != b"\n":
                        # last line without newline: use it if it is complete JSON, else wait
                        try:
                            json.loads(raw)
                        except ValueError:
                            break
                    start, pos = pos, pos + len(raw)
                    if len(raw) < 3:
                        continue        # blank line
                    if claude:
                        self._claude(raw)
                    else:
                        est = start < old_size
                        self._cursor(raw, old_mtime if est else now, est)
        except OSError:
            skipped[0] += 1
        self.offset = pos
        self.mtime, self.size = mtime, size


# ---------------------------------------------------------------- processes

class Procs(NamedTuple):
    cursor_cpu: float = 0.0
    cursor_up: bool = False
    claude_pids: frozenset = frozenset()


SELF_NAMES = ("CursorScope", "DFX Agent Enhancer")


def parse_ps(text: str, own_pid: int | None = None) -> Procs:
    """Parse `ps -axo pid,pcpu,rss,comm` output."""
    ccpu = 0.0
    cup = False
    claude = set()
    for line in text.splitlines()[1:]:
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pid, cpu = int(parts[0]), float(parts[1])
        except ValueError:
            continue
        comm = parts[3]
        if pid == own_pid or any(n in comm for n in SELF_NAMES):
            continue
        base = os.path.basename(comm)
        # the Cursor app and its helpers only; macOS has its own CursorUIViewService
        if "/Cursor.app/" in comm or base == "Cursor" or base.startswith("Cursor Helper"):
            ccpu += cpu
            cup = True
        elif base == "claude":
            claude.add(pid)
    return Procs(round(ccpu, 1), cup, frozenset(claude))


def read_ps() -> Procs:
    try:
        r = subprocess.run(["ps", "-axo", "pid,pcpu,rss,comm"], capture_output=True, text=True, timeout=5)
        return parse_ps(r.stdout, os.getpid())
    except (OSError, subprocess.SubprocessError):
        return Procs()


# ---------------------------------------------------------------- Claude live state

class Agent(NamedTuple):
    pid: int
    session: str
    busy: bool
    since: float = 0.0      # statusUpdatedAt, epoch seconds (0 when absent)
    status: str = ""        # busy | idle | waiting (a permission prompt or a question; Claude Code 2.1.289)
    name: str = ""          # Claude Code's session name, e.g. brave-otter-12
    cwd: str = ""


def read_claude_sessions(root: str, pids: frozenset) -> list[Agent]:
    """Running `claude` processes from <root>/sessions/<pid>.json (internal, undocumented:
    used when present). Only files whose pid is a live `claude` process count."""
    out = []
    for e in _scan(os.path.join(root, "sessions")):
        if not e.name.endswith(".json"):
            continue
        try:
            with open(e.path, "rb") as f:
                o = json.loads(f.read(65536))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(o, dict):
            continue
        pid, sid = o.get("pid"), o.get("sessionId")
        if isinstance(pid, int) and pid in pids and isinstance(sid, str):
            since = o.get("statusUpdatedAt")
            since = since / 1000 if isinstance(since, (int, float)) and since > 0 else 0.0
            status = o.get("status") if isinstance(o.get("status"), str) else ""
            name = o.get("name") if isinstance(o.get("name"), str) else ""
            cwd = o.get("cwd") if isinstance(o.get("cwd"), str) else ""
            out.append(Agent(pid, sid, status == "busy", since, status, name, cwd))
    return out


# ---------------------------------------------------------------- model names

def pretty_model(model: str) -> str:
    """claude-opus-5-5 -> Opus 5.5, claude-sonnet-4-5-20250929 -> Sonnet 4.5;
    other ids keep their last path segment."""
    m = re.sub(r"\[.*?\]$", "", model or "").strip()
    i = m.find("claude-")
    if i < 0:
        return m.rsplit("/", 1)[-1] or "?"
    parts = [p for p in m[i + 7:].split("-") if p and not (p.isdigit() and len(p) >= 6)]
    names = [p.capitalize() for p in parts if not p.isdigit()]
    nums = [p for p in parts if p.isdigit()]
    return " ".join(names + ([".".join(nums)] if nums else [])) or m
