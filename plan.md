# Restore the README's visual introduction

Outcome: visitors immediately see an AI beating real Balatro, watch it play, and
explore the results before getting to installation.

Design: bold opening, three headline results, quick navigation, the existing game
GIF, then results with the native victory screenshot and both benchmark graphs.
Keep capabilities, quick start, evidence links and limitations accessible.

Smallest example: opening README shows the Black/Gold wins and a game time-lapse;
scrolling reveals graphs with their settings and comparison caveats.
Reuse archived media and generated figures; no new assets or configuration.

1. Check README history, existing media and evidence for headline claims.
2. Restore the visual introduction and place results before installation.
3. Verify local links, image files, figure captions and the final diff.

Acceptance: GIF and both graphs embedded, claims backed by run evidence, no
unsupported first-ever or reliability claim, and no code or benchmark changes.
Preserve the unrelated untracked uv.lock.

Completed locally: restored the GIF, victory screenshot and both graphs; added
headline results and navigation. Verified all 33 link targets (local paths and
anchors), parsed both SVGs, decoded every GIF frame and the PNG, and passed
`git diff --check`. The GIF duration is 20.01 seconds. No code or evidence changed.
