#!/bin/sh
# Record one display to an MP4 until interrupted (macOS, ffmpeg with avfoundation).
#
#   scripts/record-display.sh OUT.mp4 [DISPLAY_INDEX]
#
# DISPLAY_INDEX is the avfoundation "Capture screen N" index (default 1, the
# first screen; list them with `ffmpeg -f avfoundation -list_devices true -i ""`).
# Uses `ffmpeg` from PATH, or the binary bundled with the imageio-ffmpeg Python
# package when that is importable. Output is 1080p H.264 at 30 fps, roughly
# 400 MB per hour. Stop with Ctrl-C or SIGINT so the file is finalised; a SIGKILL
# leaves the container unusable.
set -eu
OUT="${1:?usage: record-display.sh OUT.mp4 [DISPLAY_INDEX]}"
SCREEN="${2:-1}"
if command -v ffmpeg >/dev/null 2>&1; then
  FF=ffmpeg
else
  FF="$(python3 -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || true)"
  [ -n "$FF" ] || { echo "ffmpeg not found; install ffmpeg or pip install imageio-ffmpeg" >&2; exit 1; }
fi
exec "$FF" -hide_banner -loglevel warning -y \
  -f avfoundation -framerate 30 -capture_cursor 0 -i "${SCREEN}:none" \
  -vf "scale=1920:-2,format=yuv420p" -c:v libx264 -preset veryfast -crf 24 -g 60 \
  -movflags +faststart "$OUT"
