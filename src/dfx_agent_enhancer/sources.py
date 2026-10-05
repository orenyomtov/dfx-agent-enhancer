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

OUT, TOOLS, ERRORS, EVENTS = range(4)


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

    bins:   {bin: [reported output tokens, tool calls, errors, user/assistant events]}
    est:    the same for Cursor lines that were already on disk when first read; they are
            dated by the file mtime of that moment and never count in NOW or as live
    models: {model: {bin: reported output tokens}}
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
        self.models: dict[str, dict[int, int]] = {}
        self.msgs: dict[str, int] = {}      # message.id -> max output_tokens, recent ids only
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
            r = d[b] = [0, 0, 0, 0]
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
        out = u.get("output_tokens") if isinstance(u, dict) else None
        if isinstance(out, int) and out > 0 and model != "<synthetic>":
            # Streaming writes one record per content block, all with the same message.id and
            # a growing output_tokens. Each record adds what is new since the max seen so far,
            # so a message counts once and lands when it was produced.
            mid = m.get("id")
            if isinstance(mid, str):
                prev = self.msgs.get(mid, 0)
                delta = max(0, out - prev)
                self._remember(self.msgs, mid, max(out, prev))
            else:
                delta = out
            if delta:
                r[OUT] += delta
                mb = self.models.setdefault(model, {})
                b = int(ts // BIN)
                mb[b] = mb.get(b, 0) + delta
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
