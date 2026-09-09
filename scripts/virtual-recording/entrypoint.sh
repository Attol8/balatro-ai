#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ! ${RECORD_SECONDS:-3600} =~ ^[1-9][0-9]*$ ]]; then
  echo 'RECORD_SECONDS must be a positive integer.' >&2
  exit 2
fi
if [[ ! -r /game/Balatro.love || ! -d /mods/BalatroBot || ! -d /mods/smods ]]; then
  echo 'Mount /game/Balatro.love, /mods/BalatroBot, and /mods/smods before starting.' >&2
  exit 2
fi
mkdir -p /recording "$HOME" /mods/lovely
/usr/local/bin/bootstrap-recording-settings
if [[ -e /recording/gameplay.mp4 ]]; then
  echo '/recording/gameplay.mp4 already exists; use a fresh recording directory.' >&2
  exit 2
fi

xvfb_pid=''
game_pid=''
ffmpeg_pid=''
watchdog_pid=''

cleanup() {
  local status=$?
  trap - EXIT
  trap '' TERM INT
  set +e
  if [[ -n $watchdog_pid ]]; then
    kill -TERM "$watchdog_pid" 2>/dev/null
  fi
  # Keep the display alive until FFmpeg flushes its trailer and MP4 index.
  if [[ -n $ffmpeg_pid ]] && kill -0 "$ffmpeg_pid" 2>/dev/null; then
    kill -INT "$ffmpeg_pid" 2>/dev/null
    for ((attempt = 0; attempt < 200; attempt++)); do
      kill -0 "$ffmpeg_pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$ffmpeg_pid" 2>/dev/null; then
      echo 'FFmpeg did not finalize within 20 seconds.' >&2
      kill -KILL "$ffmpeg_pid" 2>/dev/null
      status=1
    fi
    wait "$ffmpeg_pid" 2>/dev/null
  fi
  for pid in "$game_pid" "$xvfb_pid"; do
    [[ -z $pid ]] || kill -TERM "$pid" 2>/dev/null
  done
  # Bound shutdown so Docker's 30-second grace period is sufficient.
  sleep 0.5
  for pid in "$game_pid" "$xvfb_pid" "$watchdog_pid"; do
    if [[ -n $pid ]]; then
      kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
    fi
  done
  exit "$status"
}
trap cleanup EXIT
trap 'exit 0' TERM INT

Xvfb :99 -screen 0 1280x720x24 -nolisten tcp -nocursor -ac > /recording/xvfb.log 2>&1 &
xvfb_pid=$!
display_ready=0
for ((attempt = 0; attempt < 100; attempt++)); do
  if xdpyinfo -display :99 >/dev/null 2>&1; then
    display_ready=1
    break
  fi
  if ! kill -0 "$xvfb_pid" 2>/dev/null; then
    echo 'Xvfb exited during startup; see xvfb.log.' >&2
    exit 1
  fi
  sleep 0.1
done
if (( ! display_ready )); then
  echo 'Xvfb did not become ready; see xvfb.log.' >&2
  exit 1
fi

# Wallclock anchor just before capture starts; first-frame startup may add a small offset.
printf '{"capture_started_at":%s,"anchor":"before_ffmpeg_start"}\n' "$(date +%s.%N)" > /recording/video-clock.json
ffmpeg -nostdin -hide_banner -loglevel warning -n \
  -f x11grab -draw_mouse 0 -video_size 1280x720 -framerate 15 -i :99.0 \
  -an -c:v libx264 -preset ultrafast -crf 23 -pix_fmt yuv420p \
  -movflags +faststart /recording/gameplay.mp4 > /recording/ffmpeg.log 2>&1 &
ffmpeg_pid=$!

env LD_PRELOAD=/usr/local/lib/liblovely.so \
  love /game/Balatro.love > /recording/game.log 2>&1 &
game_pid=$!
sleep "${RECORD_SECONDS:-3600}" &
watchdog_pid=$!

finished_pid=''
child_status=0
wait -n -p finished_pid "$xvfb_pid" "$ffmpeg_pid" "$game_pid" "$watchdog_pid" || child_status=$?
if [[ $finished_pid == "$watchdog_pid" ]]; then
  echo "Recording reached its ${RECORD_SECONDS:-3600}-second limit."
  exit 0
fi
echo "Recording child $finished_pid exited unexpectedly (status $child_status); see recording logs." >&2
exit 1
