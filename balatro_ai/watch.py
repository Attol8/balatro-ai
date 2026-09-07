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
# A supervisor summary reporting any other status means the game is over for good.
_RUNNING_STATUSES = frozenset({"running", "resuming", "restarting", "starting", "live"})
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
    """Incremental view of one game; state survives between polls.

    The directory is either a single run (a ``trajectory.jsonl`` beside a
    manifest) or a game root holding one sub-directory per segment, as the
    supervisor writes when it restarts the game. Either way the reader keeps one
    running view: finished segments are read once, the newest one is tailed, and
    a segment that appears later becomes the new tail without losing the past.
    """

    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self._lock = threading.Lock()
        self._reset()

    # -- reading ---------------------------------------------------------
    def _reset(self):
        self._offset = 0
        self._tail_dir = None
        self._loaded = set()
        self._chain = None
        self._segments = [self.run_dir]
        self._root = False
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
            rpc_timeouts=0,
            hedges_won=0,
        )

    def refresh(self):
        """Consume whatever the game appended since the previous call."""
        segments = self._segment_dirs()
        newest = segments[-1]
        plain = newest / "trajectory.jsonl"
        if newest == self._tail_dir and plain.exists() and plain.stat().st_size < self._offset:
            self._reset()  # the directory was replaced under us; rebuild from scratch
            segments = self._segment_dirs()
            newest = segments[-1]
        self._segments = segments
        for directory in segments[:-1]:
            self._load_finished(directory)
        if self._tail_dir != newest:
            self._tail_dir = newest
            self._offset = 0
        self._tail(newest)

    def _children(self):
        """Sub-directories holding a manifest: the segments a supervisor writes."""
        try:
            entries = sorted(self.run_dir.iterdir())
        except OSError:
            return []
        return [d for d in entries if d.is_dir() and (d / "manifest.json").exists()]

    def _segment_dirs(self):
        """Every directory of this game, oldest first; the last one is tailed."""
        own = ("trajectory.jsonl", "trajectory.jsonl.gz", "manifest.json")
        if not any((self.run_dir / name).exists() for name in own):
            children = self._children()
            if children:  # a game root: re-scanned every poll, so a new segment is picked up
                self._root = True
                return children
        self._root = False
        if self._chain is None and (self.run_dir / "manifest.json").exists():
            self._chain = self._ancestors()
        return [*(self._chain or []), self.run_dir]

    def _trajectory_bytes(self, directory, start=0):
        """Everything past ``start`` in a segment's trajectory, plain or archived."""
        plain = directory / "trajectory.jsonl"
        if plain.exists():
            with plain.open("rb") as handle:
                handle.seek(start)
                return handle.read()
        archive = directory / "trajectory.jsonl.gz"
        if archive.exists():
            with gzip.open(archive, "rb") as handle:
                return handle.read()[start:]
        return None

    def _load_finished(self, directory):
        """Read a segment that will not grow again, once, from wherever we stopped."""
        key = directory.resolve()
        if key in self._loaded:
            return
        # Only the directory we were tailing has already given us part of its lines.
        data = self._trajectory_bytes(directory, self._offset if directory == self._tail_dir else 0)
        if data is None:  # the segment exists but has written nothing yet
            return
        for line in data.splitlines():
            self._consume(line.decode("utf-8", "replace"))
        self._loaded.add(key)

    def _tail(self, directory):
        """Consume the bytes the newest segment appended since the previous poll."""
        plain = directory / "trajectory.jsonl"
        if not plain.exists():
            if self._offset == 0:  # a finished artifact: read it once
                data = self._trajectory_bytes(directory)
                if data is not None:
                    for line in data.splitlines():
                        self._consume(line.decode("utf-8", "replace"))
                    self._offset = len(data)
            return
        size = plain.stat().st_size
        if size == self._offset:
            return
        with plain.open("rb") as handle:
            handle.seek(self._offset)
            chunk = handle.read(size - self._offset)
        end = chunk.rfind(b"\n")
        if end < 0:  # a half-written line; wait for its newline
            return
        for line in chunk[: end + 1].splitlines():
            self._consume(line.decode("utf-8", "replace"))
        self._offset += end + 1

    def _ancestors(self):
        """Run directories this run continued, oldest first, following manifests."""
        chain = []
        seen = {self.run_dir.resolve()}
        current = self.run_dir
        for _ in range(32):
            manifest = current / "manifest.json"
            if not manifest.exists():
                break
            try:
                source = json.loads(manifest.read_text(encoding="utf-8")).get("continuation_of")
            except (OSError, ValueError):
                break
            if not source:
                break
            candidates = [Path(source), current.parent / Path(source).name]
            previous = next((c for c in candidates if (c / "manifest.json").exists()), None)
            if previous is None or previous.resolve() in seen:
                break
            seen.add(previous.resolve())
            chain.append(previous)
            current = previous
        return list(reversed(chain))

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
        elif kind == "rpc_timeout":
            self._counts["rpc_timeouts"] += 1  # the runner only records recovered ones
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
    def _json(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _result(self):
        """The result of the segment being tailed: the game's own once it ends."""
        return self._json((self._tail_dir or self.run_dir) / "result.json")

    def _started_at(self):
        for name in ("manifest.json", "trajectory.jsonl"):
            path = self._segments[0] / name
            if path.exists():
                return path.stat().st_mtime
        return None

    def _game(self, result):
        """Header facts about the whole game: how many segments, and how it resumed."""
        supervisor = self._json(self.run_dir / "summary.json") or {}
        manifests = [self._json(d / "manifest.json") or {} for d in self._segments]
        counted = supervisor.get("segments")
        if isinstance(counted, list):
            segments = len(counted)
        elif isinstance(counted, int) and not isinstance(counted, bool):
            segments = counted
        else:
            segments = len(self._segments)
        restarts = supervisor.get("restarts")
        return dict(
            segments=segments,
            restarts=restarts
            if isinstance(restarts, int) and not isinstance(restarts, bool)
            else None,
            supervisor=supervisor.get("status")
            if isinstance(supervisor.get("status"), str)
            else None,
            segment=self._tail_dir.name if self._root and self._tail_dir else None,
            resumed=any(m.get("continuation_of") for m in manifests),
            restored=any(m.get("resume_adjusted") for m in manifests),
            over=self._over(result, supervisor),
        )

    def _over(self, result, supervisor):
        """Whether the game itself ended, as opposed to one of its segments."""
        state = supervisor.get("status")
        if isinstance(state, str) and state.strip().lower() not in _RUNNING_STATUSES:
            return True
        if self._root:  # a segment stopping is a restart unless the game was decided
            return bool(result) and result.get("status") in ("won", "lost")
        return result is not None

    def _status(self, game):
        if game["over"]:
            return "finished"
        if not self._observation and not self._sequence:
            return "waiting"  # nothing has been played anywhere yet
        newest = self._tail_dir or self.run_dir
        writing = any(
            (newest / name).exists() for name in ("trajectory.jsonl", "trajectory.jsonl.gz")
        )
        if self._root:
            # Either the next segment has not started writing, or this one just ended.
            if not writing or (newest / "result.json").exists():
                return "resuming"
        elif not writing and game["resumed"]:
            return "resuming"  # a continuation directory the runner has not filled in yet
        return "live"

    def _elapsed(self, result):
        """Seconds of play: a segmented game adds its parts up."""
        if self._root:
            total = 0.0
            for directory in self._segments:
                done = self._json(directory / "result.json")
                if done is not None:
                    total += _number(done.get("seconds"))
                elif (directory / "manifest.json").exists():
                    total += max(0.0, time.time() - (directory / "manifest.json").stat().st_mtime)
            return total
        if result is not None:
            return _number(result.get("seconds"))
        started = self._started_at()
        return max(0.0, time.time() - started) if started is not None else 0.0

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
            game = self._game(result)
            status = self._status(game)
            return dict(
                run=self.run_dir.name,
                status=status,
                game=game,
                result=result if status == "finished" else None,
                elapsed_seconds=round(self._elapsed(result), 1),
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
                feed=list(reversed(self._feed[-24:])),
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
