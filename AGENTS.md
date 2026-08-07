# Agent Rules

## Goal

Build a fair, superhuman Balatro agent. A policy may use only information a
normal player can observe. A result counts only when the exact frozen artifact
runs through authoritative Balatro under the declared evaluation protocol.

## Workflow

- Plan non-trivial work in `plan.md` before editing.
- Use focused subagents for independent research or adversarial review.
- Prefer the smallest root-cause change; delete superseded paths.
- Never finish without tests, behavior checks, and a diff review.
- Preserve unrelated or untracked user files.

## Hard gates

- No debug mutation endpoints or injected game state.
- Never expose seed, hidden draw order, face-down identities, future RNG, raw
  object IDs, save payloads, or private clones to policy/search code.
- Unknown observation fields, action rules, phases, or engine behavior fail
  closed.
- BalatroBot is authoritative but currently exposes only observed state. Do not
  call observed-state agreement whole-engine parity or snapshot fidelity.
- Differential evidence has no waivers, tolerated mismatches, compact states,
  missing transitions, or incomplete runs.
- Every promoted trace identifies source/config/model digests, exact backend and
  game versions, compute limits, and seed provenance.
- Fast-environment wins never count as Balatro wins.

## Direction

Use a pinned, audited fast kernel for throughput and real Balatro for authority.
Prove the public-information firewall and organic differential lockstep before
training. Then use belief-state search and expert iteration with compositional
card/item/action models. Final evaluation uses a frozen artifact, evaluator-
secret seeds, all standard decks at Gold stake, and a preregistered strong-human
comparison.
