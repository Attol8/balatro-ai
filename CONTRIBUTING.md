# Contributing

See [the documentation index](docs/README.md) for usage, architecture and results.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,bench]'
```

## Tests

```bash
pytest -q
```

## Lint

```bash
ruff check .
```

## Benchmarks

Regenerate benchmark results after any change that could affect them:

```bash
python -m benchmarks
```

CI checks that `benchmarks/results/results.json` and
`benchmarks/results/results.md` are unchanged after this command runs, so
regenerate and commit them together with any relevant code change.

To add new real-game results, add a run directory and then aggregate it in:

```bash
python -m benchmarks --runs DIR
```

### Live runs

Never start a live game from CI or from the test suite. Tests use recorded
observations and fake transports only; a live run costs model calls and needs a
real game client, so it is always a deliberate, local, supervised act.

To play one, start the game side and check readiness before spending any calls:

```bash
BALATROBOT_ALL_UNLOCKED=1 uvx balatrobot serve --fast --headless --logs-path runs/logs
balatro doctor
balatro play --endless --output runs/<name>
```

The defaults bound the run at 450 model calls, 750 actions, 7200 seconds and 60
seconds per call. Stop the runner only while it is waiting on a model call, never
inside a game mutation, and continue with `balatro play --resume DIR --output
NEWDIR`.

Write the run up in a README next to the evidence, as
[`evidence/astra-low-TAF7DNTX/README.md`](evidence/astra-low-TAF7DNTX/README.md)
does: every restart with its reason and runner revision, the segment hashes, each
resume's `resume_adjusted`, and the rejected replies and model-call timeouts from
`result.json`. Report them even when they are unflattering.

## Rules

- No game assets (images, audio, level data, etc.) may be committed to this
  repository.
- Never include seeds or private game state in prompts sent to the model.
- Never retry an uncertain game mutation; treat ambiguous action outcomes as
  failures rather than resubmitting them.
- Every reported experimental result must trace back to a file under `evidence/`.

## License

Code contributions are licensed under AGPL-3.0-or-later ([LICENSE](LICENSE)).
Documentation, evidence and generated results are licensed under CC BY 4.0
([LICENSE-DOCS](LICENSE-DOCS)).
