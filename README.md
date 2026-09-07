# Balatro AI

One real game, one Astra coach, public numerical tools. The model chooses strategy
and actions; Python exposes legal moves, estimates hand scores, validates replies,
and executes through local BalatroBot. Cashout is the only automatic decision.

**Default: `gpt-6-astra`, low reasoning effort, through Codex signed into ChatGPT.**
No direct model API client or API-key billing path. No training, simulator,
policy variants, batch evaluator, or fallback player.

The earlier Astra **high** system cleared Ante 8: 415,042 chips against Violet
Vessel's 300,000 requirement. [Recorded proof](docs/coached-win.md) includes the
original prompt and full compressed trace. Astra low also cleared Ante 8 on [seed 2K9H9HN](evidence/astra-low-2K9H9HN)
during a supervised development run with recovery fixes, then reached Ante 11
in endless mode with a peak hand of 1,239,454. Its unattended win rate is unmeasured.

## Install and check

Requires Python 3.11+, macOS/Linux, Codex CLI supporting `--ignore-user-config`
and `--ignore-rules` (developed against 0.153.4), and an installed real Balatro
with BalatroBot. Runtime Python dependencies: none.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
codex login
balatro --help
balatro doctor
```

Start your BalatroBot installation with `BALATROBOT_ALL_UNLOCKED=1`, listening on
localhost port 12346, and leave the game at MENU. With the installed launcher:

```sh
BALATROBOT_ALL_UNLOCKED=1 uvx balatrobot serve --fast --headless
```

`doctor` checks readiness without
model inference. The runner requires Red Deck, White Stake and the all-unlocked
profile. It does not install or launch the game. Use one game instance: separate
BalatroBot ports do not isolate the shared save/profile.

## Play when ready

This command starts a real game and makes model calls; it is never part of tests.

```sh
balatro play --output runs/game-001
# Continue past Ante 8 until loss or the configured limits:
balatro play --endless --output runs/endless-001
```

Defaults cap the run at 200 coach calls, 400 actions, 3600 seconds, and 180 seconds
per call. Override with `--max-calls`, `--max-actions`, `--seconds`, and
`--call-seconds`. These bound work, not a monetary price. Invalid action responses receive validation feedback for up to two corrections,
counted within the same coach-call limit. No rejected action reaches the game.
Transport failures and uncertain game actions are never retried. A timeout,
three consecutive invalid replies or stalled game stops the run and records a reason. Ctrl-C records an
interruption and terminates an active Codex child. The game is left for inspection.
Existing output directories and active games are never overwritten.

`--seed ABC123` optionally selects a reproducible seed. Seeds stay in the runner
manifest; the coach receives typed public observations and unordered deck counts,
not hidden identities, draw order or future shop information. Every decision uses
an isolated Codex context with a compact persistent strategy and recent outcomes.
Repeated public-state records use lossless column/row tables to reduce request
size. Coach response logs include call duration and packet byte counts; smaller
packets have not yet been benchmarked for live latency.

For an existing Codex/Claude session, run:

```sh
balatro play --coach session --output runs/session-001 --call-seconds 600
balatro next runs/session-001/public
balatro reply runs/session-001/public response.json
```

The session reads only the public packet and submits:

```json
{"request_id":"COPY_CURRENT_ID","action_json":"{\"type\":\"select_blind\"}","plan":"Compact strategy for subsequent decisions."}
```

The session model/effort is controlled by your client; the file bridge cannot
verify it. Select Astra low in Codex to match the intended configuration. Claude
is compatible with the exchange protocol but is not Astra. No session gameplay
agent is automatically spawned.

## Tools and records

`balatro_ai/game` contains the tested public adapter, legal actions and scoring
mechanics. `analysis.py` offers bounded candidates across hand families, growth
preservation options, useful held-card facts and reorder suggestions. The
[coach instructions](balatro_ai/prompts/coach.md) preserve the successful run's
lessons about Bus, Blue seals, Steel, Blackboard and changing copy targets.
Candidates are advice; the model can choose any validated legal move.

Scoring includes approximations for random/unsupported effects. Hidden cards and
hidden Jokers disable numerical play advice. Discard selection is model reasoning;
there is no Monte Carlo discard search. The original win used five V6-delegated
actions; the new product asks Astra for all meaningful choices.

Each output has `manifest.json`, `trajectory.jsonl`, and `result.json`. Requests,
responses, mutation attempts and settled outcomes are logged. The coach receives
only its packet, not the manifest or historical evidence. Inspect results offline:

```sh
balatro inspect evidence/first-win
balatro inspect runs/game-001
python -m pytest -q
```

Tests use recorded observations and fake transports only. They cover scoring,
public-state boundaries, legality, fixed model configuration, budgets, failure
handling, and migration parity against the winning trace.

In endless mode, `ante_8_cleared` and `won` preserve the Ante8 milestone even
if the later final status is `lost`. Limits still apply; configure longer runs
explicitly with the existing call/action/time options.
