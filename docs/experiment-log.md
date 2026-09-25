# Experiment log

What has been tried, what happened, and where the code lives. Recorded
2026-09-25 when the experiment worktrees were cleaned up. Individual game
results are development evidence, not win rates; seeds JBG00000–JBG00002 have
been inspected and are excluded from future holdout evaluation.

## Lines of work

| Line | Setting | Outcome | Code and evidence |
|---|---|---|---|
| Heuristic search baselines v4–v6 | Red/White, seeds D0000000–19 | 3/20 Ante-8 clears each | `main`: `benchmarks/`, `docs/results.md` |
| Simulator era (`balatro_ai_v2`, Jackdaw) | Red/White, 200-seed panels | `control-v0` 13/400 wins, 3.6–3.9 mean antes cleared. Losses: 88% had no xMult Joker, 92% still played Pair/Two Pair, 64% died to a boss | tag `archive/2026-09-14/route-merger-wip` (`plan.md`, `docs/plan-lab-notes.md`) |
| Oracle rollout planner on Jackdaw | Red/White | 55–75% wins, but read hidden state; deleted as unfair | same tag, lab notes |
| Fair determinized search v2 | Red/White, seeds 1–30 / 31–60 | +1.40 [0.50, 2.30] and +0.60 [0.13, 1.10] mean antes vs control; wins 2 vs 1 and 2 vs 2. About 10–16 min per simulated run | same tag |
| Parity, legality and sale-guard work | Simulator era | Legality speedups, destructive-sale guard, parity records | tags `archive/2026-09-14/codex/*` |
| **Astra low + numerical tools** | Red/White | 5 Ante-8 clears across versions; Ante 13 endless; 134,231,931,235-chip peak hand | `main`: `docs/results.md` |
| **Astra low + numerical tools** | Black/Gold | 2 fresh-seed wins (MSVP7ABY, PI4T2AH8), 9 Sep 2026 | `main`: `docs/black-gold-results.md` |
| Terra low | Red/White | 2 losses at Ante 2 on QD3F4XVW | `main`: `evidence/terra-low-*` |
| Jev only | Black/Gold JBG00000 | Infrastructure failure at Ante 1 after 62 s | tag `archive/2026-09-25/jev-balatro` |
| Hybrid v1–v5 (Jev tactics, Astra strategy) | Black/Gold JBG00000 | v1 lost Ante 1 (292/300); v2 lost Ante 5 (24,470/25,000); v3 lost Ante 1 (560/600); v4 and v5 lost Ante 2 Big Blind | same tag, `docs/hybrid.md` |
| Hybrid v6 matched pilot | Black/Gold JBG00001–2 | Astra lost Ante 5 twice; hybrid lost Ante 4 and hit the 2,400 s budget alive at Ante 7 | same tag, `evidence/hybrid-v6-matched-pilot/` |
| Search coach (blind expectimax + Jev + Astra) | Black/Gold JBG00000 | Stopped by the user alive at Ante 2; Astra median 20.4 s | same tag, `docs/blind-search.md` |
| Fast coach (Jev decides, Astra advises) | Black/Gold JBG00000 | Lost Ante 1 (378/600) twice at 0.77 s median decisions | same tag, `docs/fast.md` |
| Fast selective v2 (Jev + selective Astra reviews) | Black/Gold JBG00000 | Lost Ante 4 (6,836/13,500) in 518 s | same tag, `evidence/fast-selective-*` |
| GPT-6 Luna xhigh, pure Codex coach | Black/Gold, headless | Lost Ante 2 after 1,332 s; 30 s median latency, 4 timeouts | tag `archive/2026-09-25/luna-xhigh-headless` |
| Blind-search replay (kernel ported, no routing) | Recorded in-blind decisions from both wins, XV2MP8L5 and the pilot Astra arms | 85 of 406 covered; 14 (3.4%) routable after excluding scaling/money Jokers, held Tarots and inexact results, all "play a covered clearing hand", 14/14 agreeing with Astra; never proves Astra worse. Dropped per `plan.md` A2 | port and report left unmerged in an agent worktree |
| **Astra low + pace, money, Tarot and skip values; visible `--fast`** | Black/Gold, random fresh seed, 25 Sep 2026 | Lost the Ante 8 boss (Crimson Heart, 295,956/400,000) after clearing Antes 1–7; 28.2 min, 148 calls, 6 skips | `runs/astra-fast-bg-001` (not committed); `balatro_ai/pace.py`, `balatro_ai/economy.py` |
| Same bot + next-ante horizon, forecast-gated rerolls; visible `--fast`, endless | Red/White, seed 2W7A4ADG, 25 Sep 2026 | **Won Ante 8**; endless lost the Ante 11 Big Blind (2,671,670/10,800,000). 55.3 min and 278 calls in three segments: an Ante 8 Cerulean Bell crash and a transient Codex exit, both fixed and resumed | `runs/red-white-2W7A4ADG-endless*` (not committed) |
| Offline strategy knowledge base | Offline | In progress, uncommitted, on branch `strategy-knowledge-base` in the primary checkout | not archived by this cleanup |

## Lessons

- **Strength has come only from Astra making decisions.** Every attempt to move
  decision authority to something faster lost strength: Jev, hybrid routing,
  heuristic rules and fair simulator search.
- **Fair search helps survival, not wins.** Determinized rollouts added
  0.6–1.4 antes but barely changed wins. The rollout policy bounds their quality,
  and the only strong search result used hidden state.
- **The fast chooser's losses were calculable.** For example, it left Saturn
  unused (the same Straight scored 256 without it, 658 with it, against a 600
  target) and played a 24-point pair with 344 chips still needed.
- **Hand-written strategy rules moved wins by at most one per 50-seed screen**
  in the simulator era.
- **Single development games do not measure strength.** Compare frozen versions
  on untouched matched seeds.

## Where the time goes (measured 2026-09-25 from recorded traces)

| Run | Wall | Astra | Game client | Astra calls, median |
|---|---|---|---|---|
| PI4T2AH8 (win) | 95.5 min | 36.0 min | 59.4 min | 227, 9.2 s |
| MSVP7ABY (win) | 97.7 min | 48.8 min | 48.9 min | 216, 10.2 s |
| Pilot Astra runs | 22–27 min | 70–72% | 28–30% | 98–122, 8.6–9.5 s |
| astra-fast-bg-001 (visible `--fast`, lost Ante 8) | 28.2 min | 24.3 min | 2.2 min | 148, 9.3 s |

- Local analysis is negligible: about 0.01 s per decision. The pace forecast adds a
  median 0.4 s (p90 2.4 s) to shop decisions.
- Visible `--fast` mode cut a `play` from 8.7 s to 0.72 s median; Astra is now 86%
  of wall time, so the number of calls is the remaining lever.
- The 2W7A4ADG run chained 47 follow-up actions (20 rerolls inside loops) against
  19 in the previous game; median call time stayed at 9.5 s.
- The live run found three bugs, all fixed: Four Fingers flushes scored an off-suit
  card (38,808 estimated, 24,716 real), held-Tarot scoring and targets ignored
  Cerulean Bell's forced card, and a failed Codex process was not retried.
- The pace forecast freezes growing Jokers (Obelisk, Supernova) at their current
  value, so it is conservative for builds that grow inside a round: it gave the
  Ante 10 boss under 50% and the bot cleared it with 1.43M of 1.12M.
- Until 25 Sep 2026 the runner settled Arcana and Spectral packs before their hand
  was dealt, so targeted Tarots were illegal on the first pick of nearly every pack
  (PI4T2AH8: 12 of 64 pack observations had a hand).
- The wins were recorded in visible, slowed-down mode. With visible 2×
  animations, a `play` takes 8.7 s median in the client. A clean
  `--fast --headless` measurement does not exist yet.
- Astra's calls in the two wins:
  - about one third were in-blind plays, discards and reorders (71/227, 73/216);
  - 42–46% were shop clicks, including 30 and 23 single rerolls;
  - 11–12% were pack choices;
  - 7–10% were blind selection.

## Worktree cleanup, 2026-09-25

- `jev-balatro` and `luna-xhigh-headless` were committed as-is and tagged
  `archive/2026-09-25/<name>`. Restore with, for example,
  `git worktree add ../restore archive/2026-09-25/jev-balatro`.
- `balatro-ai-v2.route-merger-wip` was already preserved as
  `archive/2026-09-14/route-merger-wip`.
- Active work continues in the `astra-speed` worktree; see its `plan.md`.
