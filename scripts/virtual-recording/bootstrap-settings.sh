#!/usr/bin/env bash
set -Eeuo pipefail

# BalatroBot skips the tutorial before a fresh profile initializes its progress.
# Balatro accepts uncompressed settings beginning with "return" and merges these
# fields into its defaults. Keep existing recording settings untouched.
settings_dir="${XDG_DATA_HOME:?XDG_DATA_HOME must identify the isolated save directory}/love/Balatro"
mkdir -p "$settings_dir"
if [[ ! -e "$settings_dir/settings.jkr" ]]; then
  (
    set -o noclobber
    # Explicit fullscreen dimensions avoid SDL's initial desktop-size window
    # and Balatro's automatic 80% reduction when selecting Windowed mode.
    cat > "$settings_dir/settings.jkr" <<'LUA'
return {
  tutorial_complete = true,
  screen_res = {w = 1280, h = 720},
  WINDOW = {
    screenmode = 'Fullscreen',
    vsync = 0,
    selected_display = 1,
    display_names = {'Virtual recording'},
    DISPLAYS = {
      {name = 'Virtual recording', screen_res = {w = 1280, h = 720}}
    }
  }
}
LUA
  )
fi
