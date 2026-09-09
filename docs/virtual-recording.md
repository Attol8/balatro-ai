# Record without a visible game window

`scripts/record-virtual.py` runs the real game inside Docker and records a private
Xvfb display. It never launches the macOS game application or records your desktop.
The game renders normally **inside the container**; BalatroBot's `--headless`
setting disables drawing and cannot produce footage.

Requirements: a running Docker daemon, Python 3, a legally installed
`Balatro.love`, and installed `smods` and `BalatroBot` mod directories. The default
paths match a macOS Steam installation; override `--game` and `--mods` elsewhere.
The image contains the Linux runtime and mod loader, not the game or its assets.
The first build downloads dependencies and compiles pinned Lovely 0.9 and LÖVE 11.5
sources for the Docker host architecture.

```sh
python3 scripts/record-virtual.py build
python3 scripts/record-virtual.py start runs/private-video --seconds 3600
```

`start` creates a fresh output directory and waits for the game API. It begins
recording the menu but does not start a bot run. To play when ready:

```sh
python3 -m balatro_ai play --port 12347 --deck BLACK --stake GOLD \
  --rpc-seconds 180 --seconds 3300 --output runs/private-video/bot
```

Stop the bot before stopping the recording, then finalize the MP4:

```sh
python3 scripts/record-virtual.py stop runs/private-video
python3 scripts/review-recording.py runs/private-video \
  --trace runs/private-video/bot/trajectory.jsonl
```

The default recording limit is one hour from container startup. Choose a limit
that covers the intended bot budget, or stop early; the limit stops the container
even if a bot is still active. A stopped bot can resume while the same recording
container is still running. This launcher does not restore stopped containers.
Rendered scoring animations can exceed the usual 60-second game API timeout;
`play --rpc-seconds 180` allows them to settle before sending the next action.
The total run deadline still bounds each request.

Output includes `gameplay.mp4` (1280×720, 15 FPS, silent), game/FFmpeg/display logs,
`health.json`, `recording.json`, and isolated saves. The game and mod directories
are mounted read-only. Only the fresh recording directory is writable on the
host; host saves and display devices are not mounted. The API is published only
at `127.0.0.1:12347` by default (`--port` overrides it). The container has a two-CPU,
2 GB memory limit, and uses software graphics with a 30 FPS game cap.
The virtual display cursor is hidden and FFmpeg excludes mouse pointers, removing
the default X cursor from the middle of the footage.

Normal stop and timer expiry send FFmpeg SIGINT before shutting down the virtual
display, allowing the MP4 index to be finalized. Avoid forcibly killing Docker
during recording. Stopped containers are retained for inspection; their names
appear in `recording.json` and they can be removed after inspecting the output.

The previous Black/Gold winning run has action/state evidence, not video. This
workflow records future gameplay; it does not reconstruct footage of that win.

Open the resulting `review.html` when convenient to watch the video with the trace
beside it. Clicking an event pauses and seeks to its time. The panel shows the
recorded action explanation and strategy, while expandable details retain public
observations, numerical advice and actual transitions. The MP4 itself contains only
gameplay; keep it beside `review.html` when sharing the interactive review.

New trajectory events carry Unix wallclock timestamps and elapsed segment time.
`video-clock.json` anchors capture immediately before FFmpeg starts, so alignment
may have a small startup offset; the viewer provides an offset adjustment. Supply
`--trace` multiple times for resumed segments. Historical traces without timestamps
are rejected rather than assigned invented timing. Missing explanations stay
labelled as missing. Forced/queued actions do not receive a fresh model explanation;
rejected proposals remain explicitly visible in the event stream.

Generate the review after stopping the bot and finalizing the video. It is a static
snapshot, not a live dashboard. The existing `balatro watch` command remains
available for monitoring a running bot.

For an uploadable video with explanations embedded beside the game, install
Pillow in the invoking Python environment and use the same local Docker image:

```sh
python3 scripts/export-recording.py runs/private-video \
  --trace runs/private-video/bot/trajectory.jsonl \
  --output runs/private-video/reddit.mp4 --max-seconds 840
```

This creates a silent 1920×720 H.264 MP4 with a 640-pixel explanation panel.
The export keeps the action chronology, removes recording time outside the game,
and uniformly accelerates footage when needed to fit the requested duration.
The actual playback multiplier appears on screen and in the adjacent JSON
metadata. Omit `--max-seconds` for normal speed. Repeat `--trace` for resumed
segments. The original capture remains intact; no upload is performed.

Verified on Apple Silicon with a Linux ARM Docker runtime on 9 September 2026:
four legal BLACK/GOLD actions and four real coach explanations, including a
108-chip prediction matching the game exactly. The 1280×720 H.264 capture plays
at 15 FPS; the review page passed seek, rewind and explanation-association checks
in a headless browser. Manual shutdown and a separate 12-second menu-only timer
test both finalized playable MP4 files. All six host save fingerprints remained
unchanged and owned containers were stopped. This was a short integration test,
not a full recorded win. Focused regression suite: 103 tests passed.

Local evidence: `runs/virtual-recording-20260909/verification.json`; demo:
`runs/virtual-recording-20260909/capture-04/review.html`.

A subsequent full private recording on the same date won BLACK/GOLD on fresh
random seed `PI4T2AH8`: 420,305 against 400,000, with one hand remaining,
270 completed legal actions and a peak hand of 227,383. The complete capture
and both trace segments are in `runs/black-gold-reddit-20260909/`. One opening
transport timeout required resuming the same game with `--rpc-seconds 180`;
the decision policy was unchanged. The native score audit retains three
one-chip discrepancies consistent with Ramen floating-point decay. Cursor
removal, unchanged host saves and the seekable review were verified.
The final local `black-deck-gold-reddit-final.mp4` is 14:05, 1920×720 H.264:
all gameplay actions at labelled 6.787× playback, followed by a five-second
outcome card. It passed full decoding and sampled visual checks. The original
95-minute capture remains available at `capture/gameplay.mp4`.
