"""Aggregate transcript bins, live state and processes into the snapshot the page renders.

One merged view: nothing here is split by Cursor vs Claude Code except where a source cannot
supply a number (Cursor reports no tokens and no model). The design is summarized in NOTES.md.
"""
from __future__ import annotations

import math
import os
import re
import time
from datetime import datetime, timedelta

from . import sources
from .sources import BIN, CLAUDE, CURSOR, ERRORS, EVENTS, OUT, TOOLS, FileState, Procs

WINDOWS = ("now", "1h", "today", "week")
METRICS = ("tokens", "sessions")
NB = 10                      # spectrum buckets
WEEK = 7 * 86400
SPAN = {"now": 300, "1h": 3600, "week": WEEK}
LIVE_SECS = 90
# Claude Code keeps status "busy" for hours while a session waits (e.g. on paused workflow
# agents). Busy only counts as working with a transcript record or a status change this recent;
# 30 min covers the longest tool call (the Bash maximum).
BUSY_SILENCE = 1800
ERROR_RECENT = 900           # ERRORS turns red for an error in the last 15 min
RESCAN_SECS = 30             # full directory walk interval
HOT_SECS = 900               # files touched this recently are stat'ed on every poll
# Cursor's helper processes idle at ~5% combined, so "using CPU" means clearly busy,
# and only for a transcript touched in the last 10 minutes (a long think writes nothing).
CURSOR_BUSY_CPU = 15.0
CURSOR_BUSY_MAX_AGE = 600

STUB = round(2 / 76, 3)      # 2 px of the 76 px track: the least a value above 0 shows
# Full scale steps, linear axis: 4, 8, 12, 20, 40, 80 x 10^k. All divisible by 4, so the quarter
# labels are integers, and with a x10^k multiplier on the tab they never need more than 2 digits.
FS_STEPS = tuple(sorted({s * 10 ** k for s in (4, 8, 12, 20, 40, 80) for k in range(10)}))
TOKENS_FLOOR = 4000          # tokens/min: a trickle does not fill the screen
SESSIONS_FLOOR = 4
SCALE_STALE = 10             # a full scale not used for this long (window not shown) starts over
RATE_SECS = 60               # the "now" token rate: reported output tokens in the last minute
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")   # fixed: not the system locale
# the chime: a session counts as having stopped only after it worked this long
STOP_MIN = {CLAUDE: 15, CURSOR: 60}
# slider full scale per window (NOW, 1H, TODAY, WEEK)
ROW_FS = {
    "sessions": (10, 15, 30, 100),
    "subagents": (20, 100, 2000, 5000),
    "tokens": (5e5, 5e6, 5e7, 2e8),
    "tools": (500, 5000, 1e5, 5e5),
    "errors": (10, 20, 100, 300),
}
WHEN = {"now": "in the last 5 min", "1h": "in the last hour", "today": "today", "week": "in the last 7 days"}
SHOWN = {"now": "last 5 minutes", "1h": "last hour", "today": "today", "week": "last 7 days"}


# ---------------------------------------------------------------- scanner

class Scanner:
    """Parsed transcripts of both sources, refreshed incrementally, newest first."""

    def __init__(self, cursor_root: str | None = None, claude_root: str | None = None):
        self.roots = {CURSOR: cursor_root or sources.cursor_root(),
                      CLAUDE: claude_root or sources.claude_root()}
        self.files: dict[str, FileState] = {}
        self.hot: dict[str, str] = {}        # path -> kind, stat'ed on every poll
        self.hot_dirs: set[str] = set()      # subagents/ dirs of hot Claude sessions, re-walked every poll
        self.backlog: list = []              # listing rows not parsed yet (time budget), newest first
        self.found = {CURSOR: False, CLAUDE: False}
        # (mtime, size) of every transcript at the last full walk. A Cursor file that shows up
        # later keeps its bytes up to that size out of NOW (they were written before we saw them).
        self.seen: dict[str, tuple[float, int]] = {}
        self.last_scan = 0.0
        self.started = False     # the first listing has been applied
        self.skipped = [0]       # files we could not read

    def listing(self, now: float) -> tuple[bool, list]:
        """Stat the transcripts. Touches no parsed state, so it can run outside the UI lock.
        A full walk every RESCAN_SECS; in between only the hot files, plus the subagent folders
        of hot Claude sessions so new Task/workflow agents show up within one poll."""
        if not self.started or now - self.last_scan >= RESCAN_SECS:
            rows = []
            for kind, root in self.roots.items():
                rows += sources.list_transcripts(kind, root)
            rows.sort(reverse=True)
            return True, rows
        rows = []
        for p, kind in list(self.hot.items()):
            try:
                st = os.stat(p, follow_symlinks=False)
                rows.append((st.st_mtime, st.st_size, p, kind))
            except OSError:
                pass
        extra: list = []
        for d in list(self.hot_dirs):
            sources.walk_subagents(d, extra)
        rows += [r for r in extra if r[2] not in self.hot]
        rows.sort(reverse=True)
        return False, rows

    def apply(self, full: bool, rows: list, now: float, budget: float | None = None) -> None:
        """Parse what changed, newest first. With a budget (seconds), stop when it runs out and
        keep the rest for the next call, so NOW and 1H fill before the week is done."""
        oldest = now - WEEK - 2 * RESCAN_SECS
        if full:
            self.last_scan = now
            for r in rows:
                self.found[r[3]] = True
            keep = {r[2] for r in rows if r[0] >= oldest}
            for p in list(self.files):
                if p not in keep:
                    del self.files[p]
            self.hot = {r[2]: r[3] for r in rows if r[0] >= now - HOT_SECS}
            self.hot_dirs = set()
            for p, kind in self.hot.items():
                if kind == CLAUDE:
                    i = p.find(os.sep + "subagents" + os.sep)
                    self.hot_dirs.add(p[:i + 10] if i >= 0 else sources.claude_session_dir(p))
            todo = rows
        else:
            for r in rows:
                if r[0] >= now - HOT_SECS:      # a new subagent file joins the hot set
                    self.hot.setdefault(r[2], r[3])
            listed = {r[2] for r in rows}
            todo = rows + [r for r in self.backlog if r[2] not in listed]
        deadline = None if budget is None else time.monotonic() + budget
        self.backlog = []
        for i, (mtime, size, path, kind) in enumerate(todo):
            if deadline is not None and time.monotonic() > deadline:
                self.backlog = todo[i:]
                break
            if mtime < oldest:
                continue    # cannot fall in any window, do not parse it
            fs = self.files.get(path)
            if fs is None:
                old = None if not self.started else self.seen.get(path, (0.0, 0))
                session, sub = sources.identify(kind, self.roots[kind], path)
                fs = self.files[path] = FileState(path, kind, session, sub, old)
            fs.refresh(mtime, size, now, self.skipped)
        if full:
            self.seen = {r[2]: (r[0], r[1]) for r in rows}
        self.started = True

    def refresh(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.apply(*self.listing(now), now)


# ---------------------------------------------------------------- aggregation

class Agg:
    """Totals over [start, end), and per-bucket series when a bucket length is given."""

    def __init__(self, start: int, end: int, length: int | None, lookback: int):
        self.start, self.end, self.length, self.lookback = start, end, length, lookback
        self.out = [0] * NB
        self.src = [0] * NB          # per bucket, events from: 1 Claude Code, 2 Cursor (no lookback)
        self.active = [set() for _ in range(NB)]
        self.sessions: set = set()
        self.subagents: set = set()
        self.tokens = self.sub_tokens = self.tools = self.errors = self.events = 0
        self.claude = False          # a Claude Code record in the window: tokens are known
        self.cursor = False          # a Cursor record in the window
        self.last_error = 0.0
        self.models: dict[str, list] = {}    # pretty name -> [tokens, newest bin]
        self.nominal = start                 # where the axis says the window starts


def aggregate(files, start: int, end: int, length: int | None = None, lookback: int = 0,
              est: bool = True, models: bool = False, since: int | None = None) -> Agg:
    """Sum bins in [since or start, end). With `length`, also split [start, end) into NB buckets
    of that length, and count a session as active in a bucket when it has an event in
    [bucket_end - lookback, bucket_end). `since` keeps TODAY's totals after midnight when its
    spectrum starts earlier."""
    a = Agg(start, end, length, lookback)
    lb = max(lookback, length or 0)
    lo, b0, b1 = (start - (lb - (length or 0))) // BIN, start // BIN, end // BIN
    bt = max(b0, (since or start) // BIN)
    for fs in files:
        if fs.mtime < lo * BIN - 60:
            continue    # records are written before their file's mtime
        key = fs.key
        for d, is_est in ((fs.bins, False), (fs.est, True)):
            if is_est and not est:
                continue
            for b, r in d.items():
                if b < lo or b >= b1:
                    continue
                t = b * BIN
                if length and r[EVENTS]:
                    i0 = max(0, (t - start) // length)
                    i1 = min(NB - 1, (t - start + lb) // length - 1)
                    for i in range(i0, i1 + 1):
                        a.active[i].add(key)
                if b < b0:
                    continue
                if length:
                    i = (t - start) // length
                    a.out[i] += r[OUT]
                    if r[EVENTS]:
                        a.src[i] |= 1 if fs.kind == CLAUDE else 2
                if b < bt:
                    continue
                if r[EVENTS]:
                    a.events += r[EVENTS]
                    a.sessions.add(key)
                    if fs.sub:
                        a.subagents.add(fs.path)
                    if fs.kind == CLAUDE:
                        a.claude = True
                    else:
                        a.cursor = True
                a.tokens += r[OUT]
                if fs.sub:
                    a.sub_tokens += r[OUT]
                a.tools += r[TOOLS]
                if r[ERRORS]:
                    a.errors += r[ERRORS]
                    a.last_error = max(a.last_error, t)
        if models:
            for model, mb in fs.models.items():
                for b, n in mb.items():
                    if bt <= b < b1:
                        m = a.models.setdefault(sources.pretty_model(model), [0, 0])
                        m[0] += n
                        m[1] = max(m[1], b)
    return a


def live_state(scanner: Scanner, procs: Procs, agents, now: float) -> tuple[set, set]:
    """(working session keys, open session keys).

    Claude: working = a timestamped user/assistant record in the last 90 s in any of the
    session's transcripts (main or subagent), or an alive sessions/<pid>.json with status busy
    and a record or status change in the last BUSY_SILENCE seconds. File mtime is never used:
    idle sessions get untimestamped bookkeeping lines.
    Cursor: new bytes in the last 90 s, or Cursor busy on CPU with a transcript touched
    in the last 10 min. Open: an alive Claude session file, or Cursor running."""
    working, opened = set(), set()
    last: dict = {}             # Claude session key -> newest record in any of its transcripts
    newest_cursor = None
    for fs in scanner.files.values():
        if fs.kind == CLAUDE:
            if fs.last > last.get(fs.key, 0.0):
                last[fs.key] = fs.last
            if now - fs.last < LIVE_SECS:
                working.add(fs.key)
        else:
            if newest_cursor is None or fs.mtime > newest_cursor.mtime:
                newest_cursor = fs
            if now - fs.mtime < LIVE_SECS:
                working.add(fs.key)
    for a in agents or ():
        key = (CLAUDE, a.session)
        opened.add(key)
        if a.busy and now - max(last.get(key, 0.0), a.since) < BUSY_SILENCE:
            working.add(key)
    if (newest_cursor is not None and procs.cursor_cpu >= CURSOR_BUSY_CPU
            and now - newest_cursor.mtime < CURSOR_BUSY_MAX_AGE):
        working.add(newest_cursor.key)
    opened |= working
    if procs.cursor_up and not any(k[0] == CURSOR for k in opened):
        opened.add((CURSOR, "app"))
    return working, opened



# ---------------------------------------------------------------- scales

def fs_up(x: float, floor: float) -> int:
    """The first full-scale step (4, 8, 12, 20, 40, 80 x 10^k) at or above both x and the floor."""
    x = max(x, floor)
    return next((s for s in FS_STEPS if s >= x * (1 - 1e-12)), FS_STEPS[-1])


def fs_down(fs: float) -> int:
    smaller = [s for s in FS_STEPS if s < fs]
    return smaller[-1] if smaller else FS_STEPS[0]


def stable(scales: dict | None, key, target, down, now: float):
    """Full scale that rises to a new step at once but falls by at most one step a minute,
    so the bars do not all jump when one peak leaves the window. A scale that was not used in
    the last SCALE_STALE seconds (its window was not shown) starts over at the target."""
    if scales is None:
        return target
    prev = scales.get(key)
    if prev is None or target > prev[0] or now - prev[2] > SCALE_STALE:
        scales[key] = (target, now, now)
        return target
    fs, t, _ = prev
    if target < fs and now - t >= 60:
        fs = max(target, down(fs))
        t = now
    scales[key] = (fs, t, now)
    return fs


def height(v: float, fs: float) -> float:
    """Linear: a bar twice as tall is twice the value. Anything above 0 shows a 2 px stub at least."""
    if v <= 0:
        return 0.0
    return round(max(STUB, min(1.0, v / fs)), 3)


def scale_labels(fs: float, unit: int) -> tuple[int, list[str]]:
    """(multiplier, labels at FS, 3/4, 1/2, 1/4). The multiplier is unit x 10^k, the smallest
    that brings FS to 80 or below, so a label never needs more than 2 digits (the label column
    is 15 px wide). FS 40k -> x1k, 40 30 20 10; FS 120k -> x10k, 12 9 6 3."""
    mult = unit
    while fs / mult > 80:
        mult *= 10
    top = round(fs / mult)
    return mult, [str(top * q // 4) for q in (4, 3, 2, 1)]


def row_fill(v, fs: float, lo: float) -> float:
    """Slider fill: log scale from lo to the row's full scale, never below a visible 4%."""
    if not v:
        return 0.0
    return round(min(1.0, max(0.04, math.log(v / lo) / math.log(fs / lo))), 3)


# ---------------------------------------------------------------- formatting

def short(n: float, decimals: bool = True) -> str:
    """15020 -> 15.0k, 20000 -> 20k (decimals=False), 1.2M."""
    for div, unit in ((1e6, "M"), (1e3, "k")):
        if n >= div:
            v = n / div
            if v >= 100 or (not decimals and v == int(v)):
                return "%d%s" % (round(v), unit)
            return "%.1f%s" % (v, unit)
    return "%d" % n


def compact(n: float) -> str:
    """Rates and scales: 640, 4.2k, 12k, 312k, 1.2M (one decimal only below 10)."""
    n = round(n)
    for div, unit in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if n >= div * 0.9995:
            v = n / div
            return ("%d" % round(v) if v >= 9.95 else ("%.1f" % v).rstrip("0").rstrip(".")) + unit
    return "%d" % n


def dur(s: int) -> str:
    if s < 60:
        return "%d s" % s
    if s < 3600:
        return "%g min" % round(s / 60, 1)
    return "%g h" % round(s / 3600, 1)


def hm(t: float) -> str:
    """24 h clock without a leading zero: 8:05, 20:30."""
    d = datetime.fromtimestamp(t)
    return "%d:%02d" % (d.hour, d.minute)


def hms(t: float) -> str:
    d = datetime.fromtimestamp(t)
    return "%d:%02d:%02d" % (d.hour, d.minute, d.second)


def clock(t: float, week: bool = False) -> str:
    return (DAYS[datetime.fromtimestamp(t).weekday()] + " " + hm(t)) if week else hm(t)


def ago(s: float) -> str:
    s = max(0, int(s))
    if s < 60:
        return "%ds ago" % s
    if s < 3600:
        return "%dm ago" % (s // 60)
    return "%dh ago" % (s // 3600)


def plural(n: int, word: str) -> str:
    return "%s %s%s" % (format(n, ","), word, "" if n == 1 else "s")


# ---------------------------------------------------------------- time axis

TODAY_STEPS = (900, 1800, 3600, 7200, 10800, 14400, 21600)


def midnight(now: float) -> int:
    return int(datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def axis(window: str, start: int, end: int, nominal: int) -> list[dict]:
    """Time labels for the axis row: [{x: 0..1 across the bars, text}]. The two ends are always
    shown; the page drops interior labels that would collide."""
    span = end - start

    def x(t):
        return round((t - start) / span, 4)

    if window == "now":
        return [{"x": i / 5, "text": "-%dm" % (5 - i)} for i in range(5)] + [{"x": 1, "text": "now"}]
    if window == "1h":
        return ([{"x": 0, "text": "-1h"}] + [{"x": q / 4, "text": "-%dm" % (60 - 15 * q)} for q in (1, 2, 3)]
                + [{"x": 1, "text": "now"}])
    inner = []
    if window == "today":
        first = hm(nominal)
        mid = midnight(start)
        for step in TODAY_STEPS:      # whole clock times, at most 4 of them
            t0 = mid + -(-(start - mid) // step) * step
            ticks = [t for t in range(t0, end, step) if t > start]
            if len(ticks) <= 4:
                break
        inner = [{"x": x(t), "text": hm(t)} for t in ticks]
    else:                             # week: each weekday at its local noon
        first = "-7d"
        d = datetime.fromtimestamp(start).date()
        while True:
            noon = datetime(d.year, d.month, d.day, 12).timestamp()
            if noon >= end:
                break
            if noon > start:
                inner.append({"x": x(noon), "text": DAYS[d.weekday()]})
            d += timedelta(days=1)
    return [{"x": 0, "text": first}] + inner + [{"x": 1, "text": "now"}]


def bucket_range(window: str, t0: float, t1: float, last: bool) -> str:
    """NOW 20:39:30–20:40:00, 1H and TODAY 20:30–20:36, WEEK Tue 14:24 – Wed 07:12; the last bar ends at now."""
    if window == "week":
        return "%s – %s" % (clock(t0, True), "now" if last else clock(t1, True))
    f = hms if window == "now" else hm
    return "%s–%s" % (f(t0), "now" if last else f(t1))


# ---------------------------------------------------------------- snapshot

def geometry(scanner: Scanner, window: str, now: float) -> tuple[int, int, int, int]:
    """(start, bucket length, end, nominal start) in epoch seconds, on the 10 s bin grid; end is
    the end of the current bin. TODAY starts at the first event today (floored to 10 min), or
    at midnight, and spans at least 1 h; rounding to 10 buckets can start it up to 100 s early.
    The spectrum may so reach into yesterday; TODAY's totals never do (see _series)."""
    end = (int(now // BIN) + 1) * BIN
    if window != "today":
        length = SPAN[window] // NB
        return end - NB * length, length, end, end - NB * length
    mid = midnight(now)
    first = None
    for fs in scanner.files.values():
        if fs.mtime < mid:
            continue
        for d in (fs.bins, fs.est):
            for b in d:
                t = b * BIN
                if mid <= t < end and (first is None or t < first):
                    first = t
    s0 = first // 600 * 600 if first is not None else mid
    span = max(end - s0, 3600)
    length = -(-span // (NB * BIN)) * BIN
    start = end - NB * length
    return start, length, end, (s0 if end - s0 >= 3600 else start)


def spectrum(a: Agg, metric: str, window: str, scales: dict | None, now: float) -> dict:
    """The bars of one metric: linear heights against a stable full scale, the four Y labels,
    the tab text (name, unit and multiplier) and one tooltip per bar."""
    length = a.length
    ranges = [bucket_range(window, a.start + i * length, a.start + (i + 1) * length, i == NB - 1)
              for i in range(NB)]
    if metric == "tokens":
        # a rate, so a label means the same thing in every window and matches the deck
        rates = [v * 60 / length for v in a.out]
        fs = stable(scales, (window, metric), fs_up(max(rates), TOKENS_FLOOR), fs_down, now)
        mult, labels = scale_labels(fs, 1000)
        tips = []
        for i in range(NB):
            if a.out[i]:
                line = "%s tokens · %s/min" % (format(a.out[i], ","), compact(rates[i]))
            elif a.src[i] & 1:
                line = "no tokens"
            elif a.src[i] & 2:
                line = "Cursor activity, no usage data"
            else:
                line = "no activity"
            tips.append(ranges[i] + "\n" + line)
        return {"tab": "Tokens/min ×" + compact(mult),
                "tip": ("Output tokens per minute in each bar (incl. thinking), Claude Code sessions and subagents. "
                        "Cursor reports no usage. Top of scale: %s/min." % compact(fs)),
                "values": [round(r) for r in rates], "heights": [height(r, fs) for r in rates],
                "fullScale": fs, "labels": labels, "known": a.claude or not a.events, "tips": tips}
    vals = [len(s) for s in a.active]
    fs = stable(scales, (window, metric), fs_up(max(vals), SESSIONS_FLOOR), fs_down, now)
    mult, labels = scale_labels(fs, 1)
    return {"tab": "Active sessions" + (" ×%d" % mult if mult > 1 else ""),
            "tip": "Sessions with activity in each bar. Top of scale: %d." % fs,
            "values": vals, "heights": [height(v, fs) for v in vals], "fullScale": fs, "labels": labels,
            "tips": [r + "\n" + ("%s active" % plural(v, "session") if v else "no activity")
                     for r, v in zip(ranges, vals)]}


def _series(scanner, window, now, est):
    start, length, end, nominal = geometry(scanner, window, now)
    since = midnight(now) if window == "today" else None
    a = aggregate(scanner.files.values(), start, end, length, max(length, LIVE_SECS), est=est, models=True,
                  since=since)
    a.nominal = nominal
    return a


def _loading(scanner: Scanner, since: float) -> bool:
    """Files are parsed newest first: data from `since` on is ready once no file left could hold it."""
    return not scanner.started or any(r[0] >= since for r in scanner.backlog)


def token_rate(scanner: Scanner, now: float) -> int | None:
    """Reported output tokens in the 60 s up to now; None when no source reports usage. Bins are
    10 s, so the current (partial) bin and the 5 before it count in full and the bin before those
    counts for the part of it still inside the minute. The value then covers exactly 60 s and
    slides smoothly instead of jumping each time a bin leaves the window."""
    if not scanner.found[CLAUDE]:
        return None
    files, c = scanner.files.values(), int(now // BIN) * BIN
    recent = aggregate(files, c + BIN - RATE_SECS, c + BIN, est=False).tokens
    oldest = aggregate(files, c - RATE_SECS, c + BIN - RATE_SECS, est=False).tokens
    return round(recent + oldest * (c + BIN - now) / BIN)


def build(scanner: Scanner, window: str = "now", metric: str | None = None, procs: Procs | None = None,
          agents=None, now: float | None = None, scales: dict | None = None, live=None) -> dict:
    """`live`: (working, open) session keys from live_state, when the caller already has them."""
    now = time.time() if now is None else now
    procs = procs or Procs()
    window = window if window in WINDOWS else "now"
    if metric not in METRICS:
        # sessions is the only spectrum a Cursor-only user can fill
        metric = "tokens" if scanner.found[CLAUDE] or not scanner.found[CURSOR] else "sessions"
    wi = WINDOWS.index(window)
    files = scanner.files.values()

    # Cursor lines already on disk at launch are dated by file mtime: never in NOW, never live
    a = _series(scanner, window, now, est=window != "now")
    end = a.end
    recent = aggregate(files, end - LIVE_SECS, end, est=False)
    err_recent = aggregate(files, end - ERROR_RECENT, end, est=False).errors
    working, opened = live if live is not None else live_state(scanner, procs, agents, now)
    active, nopen = len(working), len(opened)
    # The last bar counts every session working now, also one Claude Code reports busy that wrote
    # nothing in the lookback (a long tool call), so it agrees with the deck, the tab and the title.
    a.active[-1] |= working
    rate = token_rate(scanner, now)
    live_loading = _loading(scanner, now - LIVE_SECS - 60)

    spec = {m: spectrum(a, m, window, scales, now) for m in METRICS}
    when = WHEN[window]

    def led(v, recent_v):
        return "off" if not v else ("green" if recent_v else "amber")

    sessions_v = active if window == "now" else len(a.sessions)
    if window == "now":
        stip = ("%s working now, %d open" % (plural(active, "session"), nopen)) if nopen else "No sessions open"
    else:
        stip = "%s with activity %s. %d working now, %d open" % (plural(sessions_v, "session"), when, active, nopen)
    tokens_v = a.tokens if (a.claude or not a.events) else None
    if tokens_v is None:
        ttip = "No usage data %s: Cursor does not report usage." % when
    else:
        ttip = ("%s output tokens %s (incl. thinking)" % (format(tokens_v, ","), when) if tokens_v
                else "No output tokens %s" % when)
        if tokens_v and a.sub_tokens:
            ttip += ", %d%% from subagents" % round(100 * a.sub_tokens / tokens_v)
        ttip += "."
        if a.models:
            ranked = sorted(a.models.items(), key=lambda kv: (kv[1][0], kv[1][1]), reverse=True)
            total = sum(v[0] for _, v in ranked) or 1
            ttip += " Models: %s." % ", ".join(
                "%s %s" % (n, ("%d%%" % round(100 * v[0] / total)) if v[0] * 200 >= total else "<1%") for n, v in ranked)
        if a.cursor:
            ttip += " Cursor does not report usage."
    if a.errors:
        etip = "%s %s (Claude Code API errors and failed Cursor turns), last at %s" % (
            plural(a.errors, "error"), when, clock(a.last_error, window == "week"))
        eled = "red" if err_recent else "amber"
    else:
        etip, eled = "No API errors %s" % when, "green"
    rows = [
        {"id": "sessions", "label": "SESSIONS", "value": sessions_v,
         "fill": row_fill(sessions_v, ROW_FS["sessions"][wi], 0.5),
         "led": "green" if active else ("amber" if nopen else "off"), "tip": stip},
        {"id": "subagents", "label": "SUBAGENTS", "value": len(a.subagents),
         "fill": row_fill(len(a.subagents), ROW_FS["subagents"][wi], 0.5),
         "led": led(len(a.subagents), recent.subagents),
         "tip": "%s active %s (Claude Code Task and workflow agents, Cursor subagents)" % (
             plural(len(a.subagents), "subagent"), when)},
        {"id": "tokens", "label": "TOKENS", "value": tokens_v,
         "fill": row_fill(tokens_v, ROW_FS["tokens"][wi], ROW_FS["tokens"][wi] / 1000),
         "led": "off" if tokens_v is None else led(tokens_v, recent.tokens), "tip": ttip},
        {"id": "tools", "label": "TOOL CALLS", "value": a.tools,
         "fill": row_fill(a.tools, ROW_FS["tools"][wi], 0.5), "led": led(a.tools, recent.tools),
         "tip": "%s %s" % (plural(a.tools, "tool call"), when)},
        {"id": "errors", "label": "ERRORS", "value": a.errors,
         "fill": row_fill(a.errors, ROW_FS["errors"][wi], 0.5), "led": eled, "tip": etip},
    ]

    # session state, the same in every window: the silver tab, the menu-bar title
    if live_loading:
        readout = {"text": "Loading…", "led": "off", "tip": None}
    else:
        if active:
            text, rled = "%d active · %d open" % (active, nopen), "green"
            rtip = "%s working now (a message in the last 90 s, or Claude Code reports %s busy), %d open." % (
                plural(active, "session"), "it" if active == 1 else "them", nopen)
        elif nopen:
            text, rled, rtip = "Idle · %d open" % nopen, "amber", "No session working now, %d open." % nopen
        else:
            text, rled, rtip = "No sessions", "off", "No sessions open."
        if rate is not None:
            rtip += " %s output tokens in the last minute." % format(rate, ",")
        readout = {"text": text, "led": rled, "tip": rtip}

    # the deck's big text: the current value of the graph it shows
    idle = {"big": "IDLE", "small": ""}
    if live_loading:
        deck = {"big": "…", "small": ""}
    elif metric == "tokens":
        deck = ({"big": "NO DATA", "small": ""} if rate is None else
                idle if not active and not rate else {"big": compact(rate), "small": "/min"})
    else:
        deck = {"big": str(active), "small": "ACTIVE"} if active else idle

    return {
        "window": window,
        "metric": metric,
        "loading": _loading(scanner, a.start - LIVE_SECS - 60),
        "updatedAt": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
        "bucketSecs": a.length,
        "axis": axis(window, a.start, a.end, a.nominal),
        "spectrum": spec,
        "rows": rows,
        "now": {"active": active, "open": nopen, "rate": rate},
        "readout": readout,
        "deckText": deck,
        "deckTip": "%s, %s. Click to expand." % ("Tokens/min" if metric == "tokens" else "Active sessions",
                                                 SHOWN[window]),
        "menuTitle": "%d active" % active if active and not live_loading else "",
    }


# ---------------------------------------------------------------- stops (chime) and the menu

class Stops:
    """Sessions that stop working, for the chime and the menu's "Last stopped".

    Claude Code: its sessions/<pid>.json status goes from busy to anything else (idle, or
    waiting on a permission prompt or a question) after at least 15 s busy, while the pid is
    alive; a process that exits does not count. Cursor (no status file): a session leaves the
    working set after at least 60 s in it, so up to 90 s late."""

    def __init__(self):
        self.busy: dict = {}      # Claude pid -> busy since
        self.cursor: dict = {}    # Cursor session key -> working since

    def update(self, agents, working, now: float) -> list:
        out = []
        busy = {}
        for a in agents or ():
            since = self.busy.get(a.pid)
            if a.busy:
                busy[a.pid] = since if since is not None else (a.since or now)
            elif since is not None and now - since >= STOP_MIN[CLAUDE]:
                out.append((CLAUDE, a.session))
        self.busy = busy
        cur = {k: self.cursor.get(k, now) for k in working if k[0] == CURSOR}
        out += [k for k, t in self.cursor.items() if k not in cur and now - t >= STOP_MIN[CURSOR]]
        self.cursor = cur
        return out


def _folder(scanner: Scanner, fs: FileState) -> str:
    """A transcript's project folder name without the home-directory part: both tools name the
    folder after the path with / turned into -, so -Users-you-code-my-app gives code-my-app."""
    rel = os.path.relpath(fs.path, os.path.join(scanner.roots[fs.kind], "projects"))
    name = rel.split(os.sep)[0]
    return re.sub(r"^-?(Users|home)-[^-]+-(?=.)", "", name).lstrip("-") or name


def session_names(scanner: Scanner, agents, keys) -> list[str]:
    """Names of the given sessions, most recently active first: Claude Code's own session name
    (sessions/<pid>.json), else the folder it runs in, else the transcript's project folder."""
    by_sid = {a.session: a for a in agents or ()}
    rec: dict = {}
    rep: dict = {}
    for fs in scanner.files.values():
        k = fs.key
        if k not in keys:
            continue
        rec[k] = max(rec.get(k, 0.0), fs.last if fs.kind == CLAUDE else fs.mtime)
        if k not in rep or (rep[k].sub and not fs.sub):
            rep[k] = fs

    def name(k):
        a = by_sid.get(k[1]) if k[0] == CLAUDE else None
        if a is not None:
            rec[k] = max(rec.get(k, 0.0), a.since)
            if a.name:
                return a.name
            if a.cwd:
                return os.path.basename(a.cwd.rstrip("/")) or a.cwd
        if k in rep:
            return _folder(scanner, rep[k])
        return "Cursor" if k[0] == CURSOR else k[1][:8]

    names = {k: name(k) for k in keys}
    return [names[k] for k in sorted(keys, key=lambda k: rec.get(k, 0.0), reverse=True)]


def menu_lines(scanner: Scanner, agents, working, opened, now: float) -> list[tuple[str, int]]:
    """The menu's status lines as (text, indent): the state, today's totals, the active sessions."""
    active, nopen = len(working), len(opened)
    head = ("%d active · %d open" % (active, nopen) if active
            else "Idle · %d open" % nopen if nopen else "No sessions")
    rate = token_rate(scanner, now)
    if rate is not None and (active or rate):
        head += " · %s tokens/min" % compact(rate)     # the same format as the deck
    t = aggregate(scanner.files.values(), midnight(now), (int(now // BIN) + 1) * BIN)
    parts = ["%s tokens" % short(t.tokens)] if scanner.found[CLAUDE] else []
    parts += [plural(t.tools, "tool call"), plural(t.errors, "error")]
    lines = [(head, 0), ("Today: " + " · ".join(parts), 0)]
    names: dict = {}        # several sessions in one project folder: one line, "code-demo ×2"
    for n in session_names(scanner, agents, working):
        names[n] = names.get(n, 0) + 1
    shown = [n if c == 1 else "%s ×%d" % (n, c) for n, c in names.items()]
    lines += [(n, 1) for n in shown[:6]]
    if len(shown) > 6:
        lines.append(("+%d more" % (len(shown) - 6), 1))
    return lines
