# Running the bot

See the [quick start](../README.md#quick-start) for installation and the headless
game server. The `balatro` runner connects to that server; `play` does not launch it.
Use `balatro doctor` to check readiness without making model calls.

## Choose a run

```sh
balatro play --output runs/game-001
balatro play --deck BLACK --stake GOLD --output runs/black-gold-001
balatro play --endless --output runs/endless-001
```

These are alternatives: run one game at a time and use a new output directory
for each attempt. The defaults are Red Deck, White Stake and `gpt-6-astra` at low
effort. `--model` selects another available Codex model. `--seed` fixes a seed for
reproduction; it is recorded in the manifest and withheld from the coach.

## Bound the work

`play` defaults to 450 model calls, 750 actions, 7,200 seconds and a 60-second
per-call timeout. Set `--max-calls`, `--max-actions`, `--seconds` and `--call-seconds`
to change those limits. They bound work, not monetary cost. Model-call timeouts
and retries are recorded; uncertain game mutations are never blindly replayed.
Use `balatro play --help` for the complete command surface.

## Inspect progress

```sh
balatro watch runs/game-001
balatro inspect runs/game-001
```

`watch` serves a local dashboard at `http://127.0.0.1:8765`; it follows the action
history, status and recorded plan. `inspect` reads a saved result. Each run writes
`manifest.json`, append-only `trajectory.jsonl` and `result.json`.

## Resume a stopped run

Stop the runner while it is waiting for the model, rather than during a game
action. Keep the same game state open, then continue into a new output directory:

```sh
balatro play --resume runs/game-001 --output runs/game-001b
```

The runner compares the live state with the recorded final observation before
continuing. Any difference is recorded as `resume_adjusted` in the manifest.
Deck and stake settings are inherited on resume.

For recovery across runner exits, use the supervisor with an already running server:

```sh
balatro supervise --output runs/supervised-001
```

It keeps segments under one game root, resumes recoverable exits and stops on a
finished game or configured limits. `--server-command` optionally supplies a
server launch command; `--save-file` identifies an autosave for game-process
recovery. See `balatro supervise --help` before configuring those options.

## Supply decisions yourself

Session mode exposes requests for another client or a human to answer:

```sh
balatro play --coach session --output runs/session-001
balatro next runs/session-001/public
balatro reply runs/session-001/public response.json
```

See [the architecture](architecture.md) for the public observation and decision
boundary, and [decision probes](decision-probes.md) for focused offline checks.
