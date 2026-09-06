Mapped from advanced checkout revision `1c19cccce240222204b1edd0dc8b071875248842`.

Scope: backend.py, jackdaw.py, public_root.py, six candidate_data/jackdaw JSON
assets, and their two test modules. Internal imports are mapped to solver;
public_root uses the isolated candidate_errors exception. No private-clone
determinization or search framework is imported with this scope.

Jackdaw is optional and requires Python 3.12 or newer. Its pinned upstream
revision is dbedc66255fe594cce7b7cccc188c8a11649d9ec. The compatibility wrapper
and bundled assets are part of the candidate, not interchangeable with bare upstream.

The candidate is never authoritative Balatro. Public-root round trips and
synthetic rollout results do not establish authoritative transition parity.
No live integration or dependency installation is included.

Omitted imported tests (outside scoped dependency closure):

- test_public_root.py: test_shop_roots_round_trip_and_accept_every_decision_root
- test_public_root.py: test_all_vanilla_pack_roots_round_trip_accept_actions_and_return_to_shop
- test_public_root.py: test_same_public_particle_is_deterministic_and_other_particles_are_hidden_twins
- test_public_root.py: test_frozen_branch_restores_card_counter_before_shop_creation
- test_public_root.py: test_existing_search_consumes_fresh_public_roots_and_falls_back_elsewhere
- test_jackdaw.py: test_schema_six_authority_trace_is_retired_after_public_blind_change

These require private snapshot helpers, the unimported search framework, or
retired authority trace readers/fixtures. All other retained assertions are unchanged.
