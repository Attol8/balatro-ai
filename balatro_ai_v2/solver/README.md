# Frozen public strategic policy

Imported from `balatro-ai-v2` git revision `1c19cccce240222204b1edd0dc8b071875248842` using `git show`, not the mutable source checkout.

The initial import preserved the source policy logic. Its mechanical transformations were namespace changes from `balatro_ai_v2` to `balatro_ai_v2.solver`, flattening `balatrobot.adapter` to `solver.adapter`, namespaced test fixture imports, adjusting a test's source-file lookup, and importing `PublicHistoryStep` directly from its defining `policy` module instead of its runner re-export. The package initializer is local. Subsequent additions include local search layers and an optional public-root candidate wrapper; see [candidate provenance](CANDIDATE_PROVENANCE.md). No trained model or original strategy-search framework is included. Optional lazy search constructors in `build_public_baseline` require modules outside the import; the supported strategic integration is `PublicStrategicPolicy`.

Use `adapter.to_public_observation(raw)` to cross the privileged/public boundary, `actions.iter_legal_actions(observation)` for public actions, and `PublicStrategicPolicy.choose_action(observation, action_source, history)` for decisions. `adapter.action_to_rpc(action, observation)` validates and converts the selected action. `public_codec.public_observation_to_data` and `public_observation_from_data` serialize only the typed public contract. Raw snapshots must never be sent to the policy.

Historical candidate panels in the source repository are not measurements of this imported artifact. Verify new real-game results independently.

Local changes after import: `public_scoring.py` excludes debuffed Twos from Wee
Joker growth, correcting a 104-point overprediction found in the live development
panel. `shop_search.py` and `tactical_search.py` are new local search layers; their
estimates are not claims of full-game simulation or exact stochastic outcomes.

`misprint_distribution.py` models one uncopied Misprint's 24 outcomes on a final
hand. `SearchPolicy(model_misprint_probability=True)` enables the experimental
comparison; every registered live policy leaves it off. Existing discard guards
still apply. The same-input eight-state V5 audit changed no actions, so this is
not a demonstrated improvement. Its 1/24 action margin is a heuristic, not a
confidence bound; other scorer limitations remain.

Original source SHA-256 digests (before namespace transformations):

| Imported destination | Frozen source | SHA-256 |
| --- | --- | --- |
| `tests/solver/test_solver_baselines.py` | `tests/test_baselines.py` | `c78bc15fbe9d26266528e7d4779db549ece14e2c3b0bcdebe3d5d9a41b9a227c` |
| `balatro_ai_v2/solver/baselines.py` | `balatro_ai_v2/baselines.py` | `dd94941d4db713253616d5eafd9b55dba2dd2e3976b53f4b795da1f7722eb16d` |
| `balatro_ai_v2/solver/actions.py` | `balatro_ai_v2/actions.py` | `096e0a6fb638c2a65e7c09999ec5a4141f63afe6574bfc06e6b2b89f26b7005d` |
| `balatro_ai_v2/solver/consumable_rules.py` | `balatro_ai_v2/consumable_rules.py` | `c7cb3d11612b36888fddcf298094ab82ea999d8d7e4eae3a71f9c00e0e42ef75` |
| `balatro_ai_v2/solver/public_state.py` | `balatro_ai_v2/public_state.py` | `0262b82fdc6e2965aabab198846c19b2b4b565cc2a9c8f2b33b5aebc4fc599b8` |
| `balatro_ai_v2/solver/belief.py` | `balatro_ai_v2/belief.py` | `9eb016b498814cf08b1bc43e4a1a11eb27113353994214e880824bb8a8ba6e14` |
| `balatro_ai_v2/solver/boss_rules.py` | `balatro_ai_v2/boss_rules.py` | `d5cd0860e2224a28b2452b2741e13c74063881e0a02b5b08f13aa5580cb2221d` |
| `balatro_ai_v2/solver/build_strategy.py` | `balatro_ai_v2/build_strategy.py` | `5ace5d25db53494870172340293eef9444ee4ab39bb8e9235cd6ea6566d7da34` |
| `balatro_ai_v2/solver/joker_catalog.py` | `balatro_ai_v2/joker_catalog.py` | `a9e181bbd01eebc0ad705955aee0127cdee8824239250c0a7ef0ce0f1a8708cf` |
| `balatro_ai_v2/solver/policy.py` | `balatro_ai_v2/policy.py` | `33e6a51b436ceca2f427f1f97082c33afb960428251b88f5db4a88210154a9bc` |
| `balatro_ai_v2/solver/public_scoring.py` | `balatro_ai_v2/public_scoring.py` | `ef62980beca137b50beacae03a54fc841380df53f66310382f11c593c6f0621c` |
| `balatro_ai_v2/solver/strategy_tuning.py` | `balatro_ai_v2/strategy_tuning.py` | `8b8ef91578b43f9e35af7017511d8773d97bc351280e5e7aa9cb8fd78a085dde` |
| `balatro_ai_v2/solver/strategy_engine.py` | `balatro_ai_v2/strategy_engine.py` | `7427c7adf6e0188af9e3661620dd25447fa8af4fb4732689900996be2ad21d26` |
| `balatro_ai_v2/solver/strategy_options.py` | `balatro_ai_v2/strategy_options.py` | `97f8e9d1b1c8b1f5c00814c2bc8431fdc1f1d029c877ac236b64166949a65530` |
| `balatro_ai_v2/solver/canonical.py` | `balatro_ai_v2/canonical.py` | `83f2b60aac00a95a750ca5b8d6b4b168283166cdbdfc3f65355978cda54187b9` |
| `balatro_ai_v2/solver/public_codec.py` | `balatro_ai_v2/public_codec.py` | `88d4351a1bec6e5897a95c642893a53f76965bbf11fc1e53c2b0e06ba0f3fa62` |
| `balatro_ai_v2/solver/adapter.py` | `balatro_ai_v2/balatrobot/adapter.py` | `2c44cf608345fd384affc7300bbbdb885b83bc409bddb5783de6bf080cea6236` |
| `tests/solver/test_solver_actions.py` | `tests/test_actions.py` | `896c4dd66c39387f12c57bbde1f3a50f092c4f474be10b69f7349b1aef649e22` |
| `tests/solver/test_solver_public_codec.py` | `tests/test_public_codec.py` | `aadbf066a6760eb038742bffbfd1d9fe6049f8916c0353d0e6919bb8e938b374` |
| `tests/solver/test_solver_public_scoring.py` | `tests/test_public_scoring.py` | `3e9bb8c8f3c234b1850277ea0cc20c1b1d5249780655759177d3dfb1050b1afd` |
| `tests/solver/test_solver_build_strategy.py` | `tests/test_build_strategy.py` | `54caaf91cc5a5d3e94a2f079cd8b17f2a2f383cc4efa721f3166bb0171700779` |
| `tests/solver/test_solver_strategy_engine.py` | `tests/test_strategy_engine.py` | `48b94bc79f07a443a63c15edae30abb720d3636061a7c11c4a667436f8b766e1` |
| `tests/solver/test_solver_strategy_options.py` | `tests/test_strategy_options.py` | `07f7a5ce18cdae996dd7dd864f36f2094e7a170147b385415485a96a2256c5f4` |
| `tests/solver/test_solver_canonical.py` | `tests/test_canonical.py` | `3e668e6c449f33b67a6131f74c3a440b8bfbdd3640bf93cebf2e0ae370c6e7e9` |
| `tests/solver/solver_state_factory.py` | `tests/state_factory.py` | `8f4a4ad7f08331aece1b330f0913349f53c6b83c81c76a91064c5b964e7dde26` |
