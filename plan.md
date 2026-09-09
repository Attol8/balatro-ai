# Simplify the project overview and documentation

Outcome: readers quickly understand what the bot does, how to run it and what
results the evidence supports. Keep a brief Black/Gold win mention near the top.
Reuse existing commands, result archives and technical docs; retain working
utilities and evidence while removing recording/development clutter from README.
Smallest example: a reader can find a headless start command and the two Black/Gold
wins without navigating recording tools or historical implementation notes.

1. Rewrite README around capabilities, quick start, results and limitations.
2. Move advanced usage into a guide and add a documentation index; reconcile stale
   result summaries and contributor navigation without changing benchmark data.
3. Verify links, CLI examples and diff; publish the documentation cleanup via PR.

Acceptance: no unsupported reliability claims, every result linked to evidence,
no gameplay or code behavior changes, and unrelated uv.lock preserved.

Completed locally: README reduced to capabilities, headless quick start, compact
results and limitations. Added usage guide and documentation index; corrected
stale result counts and contributor license scopes. Local links, all documented
CLI command help and diff checks pass. No code behavior or evidence changed.
