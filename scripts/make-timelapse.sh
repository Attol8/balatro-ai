#!/bin/sh
# Turn a full game recording into a two-minute time-lapse and a short GIF.
#
#   scripts/make-timelapse.sh IN.mp4 OUT_DIR
#
# Writes OUT_DIR/recording-timelapse.mp4 (1280 px wide, about 120 s, ~10 MB) and
# OUT_DIR/recording-timelapse.gif (800 px wide, about 20 s at 10 fps, ~5 MB),
# sized for a repository. Requires ffmpeg as in record-display.sh.
set -eu
IN="${1:?usage: make-timelapse.sh IN.mp4 OUT_DIR}"
OUT="${2:?usage: make-timelapse.sh IN.mp4 OUT_DIR}"
mkdir -p "$OUT"
if command -v ffmpeg >/dev/null 2>&1; then
  FF=ffmpeg
else
  FF="$(python3 -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || true)"
  [ -n "$FF" ] || { echo "ffmpeg not found; install ffmpeg or pip install imageio-ffmpeg" >&2; exit 1; }
fi
DUR="$("$FF" -i "$IN" 2>&1 | sed -n 's/.*Duration: \([0-9:.]*\),.*/\1/p' | awk -F: '{print $1*3600+$2*60+$3}')"
SPEED="$(python3 -c "print(max(1.0, $DUR/120.0))")"
GSPEED="$(python3 -c "print(max(1.0, $DUR/20.0))")"
"$FF" -hide_banner -loglevel error -y -i "$IN" \
  -vf "setpts=PTS/$SPEED,fps=30,scale=1280:-2" -an \
  -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p -movflags +faststart "$OUT/recording-timelapse.mp4"
"$FF" -hide_banner -loglevel error -y -i "$IN" \
  -vf "setpts=PTS/$GSPEED,fps=10,scale=800:-2:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5" \
  -loop 0 "$OUT/recording-timelapse.gif"
ls -la "$OUT"
