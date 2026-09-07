"""Live dashboard over a run directory written by ``balatro play``.

The reader tails ``trajectory.jsonl`` incrementally: a run keeps appending for
hours and the file reaches tens of megabytes, so each poll parses only the bytes
that arrived since the last one. Standard library only, like the rest of the
package; the page is one self-contained HTML file served from here.
"""

from __future__ import annotations

import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML_PATH = Path(__file__).with_name("watch.html")

_MAX_FEED = 400
_MAX_LATENCY = 600
_FEED_COLUMNS = ("index", "ante", "phase", "action", "source", "chips", "money")

# First non-null wins: one joker exposes at most one interesting live number.
_RUNTIME_FIELDS = (
    ("current_x_mult", "x{}"),
    ("current_mult", "+{} mult"),
    ("current_chips", "+{} chips"),
    ("current_dollars", "${}"),
    ("current_hand_size_bonus", "+{} cards"),
    ("remaining_hands", "{} hands"),
    ("remaining_discards", "{} discards"),
    ("invisible_rounds", "{} rounds"),
    ("loyalty_remaining", "{} to go"),
    ("driver_tally", "{} tallied"),
    ("target_hand", "{}"),
    ("target_rank", "rank {}"),
    ("target_suit", "suit {}"),
    ("mail_rank", "rank {}"),
    ("castle_suit", "suit {}"),
)


def _number(value, default=0):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _runtime_value(joker):
    runtime = joker.get("runtime") or {}
    for key, template in _RUNTIME_FIELDS:
        value = runtime.get(key)
        if value not in (None, "", False):
            return template.format(value)
    return None


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


class RunWatch:
    """Incremental view of one run directory; state survives between polls."""

    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self._lock = threading.Lock()
        self._reset()

    # -- reading ---------------------------------------------------------
    def _reset(self):
        self._offset = 0
        self._observation = {}
        self._plan = ""
        self._blinds = []
        self._blind_by_key = {}
        self._active_key = None
        self._feed = []
        self._latency = []
        self._sequence = 0
        self._peak_hand = 0
        self._counts = dict(
            decisions=0,
            coach_calls=0,
            responses=0,
            followups=0,
            forced=0,
            rejections=0,
            timeouts=0,
            hedges_won=0,
        )

    def refresh(self):
        """Consume whatever the run appended since the previous call."""
        path = self.run_dir / "trajectory.jsonl"
        if not path.exists():
            archive = self.run_dir / "trajectory.jsonl.gz"
            if archive.exists():
                if self._offset == 0:  # a finished artifact: read it once
                    with gzip.open(archive, "rt", encoding="utf-8") as handle:
                        for line in handle:
                            self._consume(line)
                    self._offset = 1
                return
            self._reset()
            return
        size = path.stat().st_size
        if size < self._offset:  # the run directory was replaced under us
            self._reset()
        if size == self._offset:
            return
        with path.open("rb") as handle:
            handle.seek(self._offset)
            chunk = handle.read(size - self._offset)
        end = chunk.rfind(b"\n")
        if end < 0:  # a half-written line; wait for its newline
            return
        for line in chunk[: end + 1].splitlines():
            self._consume(line.decode("utf-8", "replace"))
        self._offset += end + 1

    def _consume(self, line):
        line = line.strip()
        if not line:
            return
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        kind = event.get("event")
        if kind == "coach_request":
            self._counts["coach_calls"] += 1
            self._observe(event.get("observation"))
            self._plan = event.get("plan") or self._plan
        elif kind == "coach_response":
            self._counts["responses"] += 1
            seconds = _number(event.get("seconds"), None)
            if seconds is not None:
                self._latency.append(round(seconds, 3))
                del self._latency[:-_MAX_LATENCY]
            timings = event.get("transport_timings") or {}
            if timings.get("hedged") and timings.get("winner"):
                self._counts["hedges_won"] += 1
            self._plan = (event.get("response") or {}).get("plan") or self._plan
        elif kind == "coach_rejected":
            self._counts["rejections"] += 1
        elif kind == "coach_timeout":
            self._counts["timeouts"] += 1
        elif kind == "rpc_attempt":
            self._observe(event.get("observation"))
        elif kind == "continued":
            self._observe(event.get("observation"))
        elif kind == "transition":
            self._transition(event)

    def _transition(self, event):
        before, after = event.get("before") or {}, event.get("after") or {}
        source = event.get("source") or "automatic"
        self._counts["decisions"] += 1
        if source == "coach_followup":
            self._counts["followups"] += 1
        elif source == "forced":
            self._counts["forced"] += 1
        self._observe(after)
        gained = _number((after.get("round") or {}).get("chips")) - _number(
            (before.get("round") or {}).get("chips")
        )
        if gained > 0:
            self._peak_hand = max(self._peak_hand, gained)
            blind = self._blind_by_key.get(self._active_key)
            if blind is not None:
                blind["best_hand"] = max(blind["best_hand"], gained)
        self._sequence += 1
        self._feed.append(
            dict(
                index=self._sequence,
                ante=after.get("ante"),
                phase=after.get("phase"),
                action=(event.get("action") or {}).get("type") or "unknown",
                source=source,
                chips=gained if gained > 0 else 0,
                money=_number(after.get("money")),
            )
        )
        del self._feed[:-_MAX_FEED]

    def _observe(self, observation):
        if not isinstance(observation, dict) or not observation:
            return
        self._observation = observation
        ante = observation.get("ante")
        blinds = observation.get("blinds") or []
        current = next((b for b in blinds if b.get("status") == "CURRENT"), None)
        if current is not None:
            key = (ante, current.get("kind"))
            if key != self._active_key:
                self._active_key = key
                entry = dict(
                    index=len(self._blinds),
                    ante=ante,
                    kind=current.get("kind"),
                    name=current.get("name"),
                    requirement=_number(current.get("score")),
                    best_hand=0,
                    chips=0,
                    cleared=False,
                )
                self._blinds.append(entry)
                self._blind_by_key[key] = entry
        active = self._blind_by_key.get(self._active_key)
        if active is not None:
            chips = _number((observation.get("round") or {}).get("chips"))
            active["chips"] = max(active["chips"], chips)
        for blind in blinds:
            entry = self._blind_by_key.get((ante, blind.get("kind")))
            if entry is not None and blind.get("status") == "DEFEATED":
                entry["cleared"] = True

    # -- reporting -------------------------------------------------------
    def _result(self):
        path = self.run_dir / "result.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _started_at(self):
        for name in ("manifest.json", "trajectory.jsonl"):
            path = self.run_dir / name
            if path.exists():
                return path.stat().st_mtime
        return None

    def _current_blind(self, observation):
        blinds = observation.get("blinds") or []
        blind = next((b for b in blinds if b.get("status") == "CURRENT"), None)
        blind = blind or next((b for b in blinds if b.get("status") == "SELECT"), None)
        blind = blind or next((b for b in blinds if b.get("status") == "UPCOMING"), None)
        round_state = observation.get("round") or {}
        if blind is None:
            return None
        return dict(
            kind=blind.get("kind"),
            name=blind.get("name"),
            status=blind.get("status"),
            effect=blind.get("effect") or "",
            requirement=_number(blind.get("score")),
            chips=_number(round_state.get("chips")),
            hands_left=_number(round_state.get("hands_left")),
            discards_left=_number(round_state.get("discards_left")),
        )

    def summary(self):
        """A whole-dashboard snapshot; cheap enough to build on every poll."""
        with self._lock:
            self.refresh()
            observation = self._observation
            result = self._result()
            counts = dict(self._counts)
            counts["calls_per_decision"] = (
                round(counts["coach_calls"] / counts["decisions"], 2) if counts["decisions"] else 0
            )
            hand_levels = sorted(
                (observation.get("hand_stats") or []),
                key=lambda h: (_number(h.get("level")), _number(h.get("played"))),
                reverse=True,
            )[:5]
            started = self._started_at()
            if result is not None:
                elapsed = _number(result.get("seconds"))
            elif started is not None:
                elapsed = max(0.0, time.time() - started)
            else:
                elapsed = 0.0
            if not observation and result is None:
                status = "waiting"
            else:
                status = "finished" if result is not None else "live"
            return dict(
                run=self.run_dir.name,
                status=status,
                result=result,
                elapsed_seconds=round(elapsed, 1),
                ante=observation.get("ante"),
                phase=observation.get("phase"),
                money=_number(observation.get("money")),
                blind=self._current_blind(observation),
                jokers=[
                    dict(
                        label=joker.get("label"),
                        edition=joker.get("edition"),
                        effect=joker.get("effect_text") or "",
                        value=_runtime_value(joker),
                    )
                    for joker in (observation.get("jokers") or [])
                ],
                consumables=[
                    dict(label=item.get("label"), kind=item.get("kind"))
                    for item in (observation.get("consumables") or [])
                ],
                hand_levels=[
                    dict(
                        name=hand.get("name"),
                        level=_number(hand.get("level")),
                        chips=_number(hand.get("chips")),
                        mult=_number(hand.get("mult")),
                        played=_number(hand.get("played")),
                    )
                    for hand in hand_levels
                ],
                counters=counts,
                latency=dict(
                    median=_percentile(self._latency, 0.5),
                    p90=_percentile(self._latency, 0.9),
                    last=self._latency[-1] if self._latency else None,
                    recent=self._latency[-60:],
                ),
                plan=self._plan,
                peak_hand=self._peak_hand,
                feed=list(reversed(self._feed[-12:])),
                blinds=list(self._blinds),
                last_event=self._sequence,
            )

    def events_since(self, since):
        """Compact rows for whatever landed after ``since``; newest last."""
        with self._lock:
            self.refresh()
            rows = [
                [row[column] for column in _FEED_COLUMNS]
                for row in self._feed
                if row["index"] > since
            ]
            return dict(columns=list(_FEED_COLUMNS), rows=rows, last_event=self._sequence)


_WATCHES = {}
_WATCHES_LOCK = threading.Lock()


def watcher(run_dir):
    """One reader per directory, so repeated calls keep tailing."""
    key = str(Path(run_dir).resolve())
    with _WATCHES_LOCK:
        watch = _WATCHES.get(key)
        if watch is None:
            watch = _WATCHES[key] = RunWatch(run_dir)
        return watch


def summarize(run_dir):
    """Snapshot of the run: state, counters, chart series and the action feed."""
    return watcher(run_dir).summary()


class _Handler(BaseHTTPRequestHandler):
    server_version = "balatro-watch"

    def do_GET(self):  # noqa: N802 - http.server's spelling
        path, _, query = self.path.partition("?")
        if path == "/":
            self._send(HTML_PATH.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/state":
            self._send_json(self.server.watch.summary())
        elif path == "/api/events":
            since = 0
            for part in query.split("&"):
                if part.startswith("since="):
                    since = int(part[6:]) if part[6:].isdigit() else 0
            self._send_json(self.server.watch.events_since(since))
        else:
            self.send_error(404, "no such view")

    def _send_json(self, payload):
        self._send(json.dumps(payload).encode("utf-8"), "application/json")

    def _send(self, body, content_type):
        headers = [("Content-Type", content_type), ("Cache-Control", "no-store")]
        if len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, 6)
            headers.append(("Content-Encoding", "gzip"))
        self.send_response(200)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return  # the dashboard polls twice a second-ish; keep the console clean


def make_server(run_dir, host="127.0.0.1", port=8765):
    """Bound, not yet serving: tests take port 0 and read the real port."""
    server = ThreadingHTTPServer((host, port), _Handler)
    server.watch = watcher(run_dir)
    return server


def serve(run_dir, host="127.0.0.1", port=8765):
    """Serve the dashboard for ``run_dir`` until interrupted."""
    server = make_server(run_dir, host, port)
    print(f"balatro watch: http://{host}:{server.server_address[1]}/  ({Path(run_dir)})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
