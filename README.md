# Balatro AI

An AI agent that plays real Balatro using GPT-6 Astra and public-information
numerical tools. It chooses hands, discards, purchases and Joker arrangements,
then executes legal actions through [BalatroBot](https://github.com/coder/balatrobot).

The bot has beaten **Black Deck on Gold Stake on two fresh random seeds** and
reached **Ante 13** in an earlier Red Deck / White Stake run.
[Results and limitations](#results) are documented below.

## What it does

- Plays a complete game, with optional continuation into endless mode.
- Evaluates legal hands, discard options, scoring combinations and upcoming blinds.
- Uses public game information: the model receives no seed, future shop contents
  or hidden draw order.
- Supports headless play, bounded runs, checked resumes and a live status dashboard.
- Saves decisions and outcomes so each run can be inspected afterwards.

The model makes strategic decisions; Python supplies calculations, validates
responses and sends actions to the game. Scoring is exact for supported deterministic
situations; random or hidden effects can limit the advice available.
[How it works](docs/architecture.md).

## Quick start

Requires Python 3.11+, macOS or Linux, your own copy of Balatro with BalatroBot
installed, and access to the configured model through a signed-in Codex CLI.
This repository includes no game assets. Run these commands from a local checkout:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
codex login
```

Start the game server headlessly in one terminal:

```sh
BALATROBOT_ALL_UNLOCKED=1 uvx balatrobot serve --fast --headless --logs-path runs/logs
```

In another terminal with the same virtual environment activated:

```sh
balatro doctor
balatro play --output runs/game-001
```

The default is Red Deck / White Stake, stopping after the Ante 8 win. To play
Black Deck / Gold Stake instead:

```sh
balatro play --deck BLACK --stake GOLD --output runs/black-gold-001
```

Use `--endless` to continue after Ante 8. Each run uses model calls and records
its result and action history. Run one game instance at a time.
[Run limits, resumes, supervision and inspection](docs/usage.md).

## Results

A win means clearing the Ante 8 boss. These are documented runs from several bot
versions, **not a measured win rate or a guarantee of reliable wins**.

| Setting | Demonstrated result | Evidence |
|---|---|---|
| Red Deck / White Stake | Five published Astra Ante 8 clears across earlier versions; highest ante reached: 13 | [Results and run disclosures](docs/results.md) |
| Red Deck / White Stake, highest score | **134,231,931,235 chips in one hand** | [Ante 13 run](evidence/astra-low-TAF7DNTX/README.md) |
| Black Deck / Gold Stake | Two fresh-seed wins: **435,408 / 400,000** and **420,305 / 400,000**, both with one hand unused | [Full traces and rules audit](docs/black-gold-results.md) |
| Non-model baselines | Best policies won 3 of 20 games on a fixed Red/White seed panel | [Benchmark tables](benchmarks/results/results.md) |

The coached runs are not a matched comparison with the baseline panel. Development
included losses, some earlier games used fixes between segments, and the two
Black/Gold wins do not establish a success rate. The reports retain failures,
restarts, policy versions and scoring discrepancies.

## Scope and limitations

The published runs use the native game with BalatroBot automation and an
all-unlocked profile. This bypasses content unlock progression; it is a modded
setup, not a fresh-account achievement run. The Black/Gold report checks every
cumulative stake rule against the recorded game state.

The bot uses numerical assistance rather than vision alone. Its decisions can be
suboptimal, scoring advice has coverage limits, and model-service timeouts can
interrupt runs. Reliability across a representative seed set remains unmeasured.
[Evaluation methodology](docs/methodology.md).

## Development

Tests use recorded observations and fake transports; they do not start the game
or spend model calls.

```sh
pip install -e '.[dev,bench]'
pytest -q
ruff check .
python -m benchmarks
```

For small checks before a full run, see [decision probes](docs/decision-probes.md).
See [CONTRIBUTING.md](CONTRIBUTING.md) for validation and evidence requirements,
and the [documentation index](docs/README.md) for technical details.

## License

Code is licensed under the GNU Affero General Public License v3.0 or later
([LICENSE](LICENSE)). Documentation, evidence and generated results are CC BY 4.0
([LICENSE-DOCS](LICENSE-DOCS)). Balatro is a game by LocalThunk, published by
Playstack; this project is unaffiliated and includes no game assets. BalatroBot is
MIT licensed by Coder. See [NOTICE](NOTICE). To cite, use [CITATION.cff](CITATION.cff).
