# Contributing

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

## Rules

- No game assets (images, audio, level data, etc.) may be committed to this
  repository.
- Never include seeds or private game state in prompts sent to the model.
- Never retry an uncertain game mutation; treat ambiguous action outcomes as
  failures rather than resubmitting them.
- Every number that appears in the documentation must trace back to a file
  under `evidence/`.

## License

By contributing, you agree that your contributions are licensed under
AGPL-3.0-or-later, the same license that covers the rest of the codebase.
