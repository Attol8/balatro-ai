"""Frozen constants shared by route-terminal collection and merging."""

from __future__ import annotations


ROUTE_TEACHER_PROTOCOL_ID = "route-terminal-development-v1"
ROUTE_TEACHER_PREREGISTRATION = (
    "experiments/route-terminal-v1-preregistration.json"
)
ROUTE_TEACHER_ORIGIN_KEY = "runs/secrets/route-terminal-v1-origin.key"
ROUTE_TEACHER_BATCH_SIZE = 20
ROUTE_TEACHER_BATCH_STARTS = tuple(range(2311, 2411, ROUTE_TEACHER_BATCH_SIZE))
ROUTE_TEACHER_BATCHES = tuple(
    {
        "batch_id": f"batch-{index:02d}",
        "seed_start": seed_start,
        "seeds": ROUTE_TEACHER_BATCH_SIZE,
        "teacher_jsonl": (
            "runs/experiments/route-terminal-v1/"
            f"batch-{index:02d}/teacher.jsonl"
        ),
        "report_json": (
            "runs/experiments/route-terminal-v1/"
            f"batch-{index:02d}/report.json"
        ),
    }
    for index, seed_start in enumerate(ROUTE_TEACHER_BATCH_STARTS, start=1)
)
ROUTE_TEACHER_SEARCH = {
    "samples": 6,
    "horizon_antes": 1,
    "max_steps": 200,
    "override_z": 1.0,
    "max_decisions": 1200,
    "ante_cap": 20,
    "workers": 9,
    "nonce": "route-terminal-v1-frozen",
    "continuation": "strategic",
    "policy_seed": "baseline-v1",
    "strategy_options": True,
    "include_reorders": False,
    "dense_teacher": False,
}
ROUTE_TEACHER_TERMINAL = {
    "samples": 2,
    "prewin_start_ante": 4,
    "endless_horizon_antes": 2,
    "max_steps": 600,
    "affects_actions": False,
    "anchor_schedule": (
        "first_shop_each_ante;first_pack_each_ante_from_ante4;"
        "boss_select_ante5_plus;postwin_first_shop_and_pack_each_ante"
    ),
}
ROUTE_TEACHER_PILOT_GATE = {
    "source_runs": ROUTE_TEACHER_BATCH_SIZE,
    "minimum_record_groups": 3,
    "minimum_records": 20,
    "required_route_phases": ["PACK", "SHOP"],
    "minimum_route_diverse_groups": 3,
    "minimum_route_diverse_rows": 5,
    "minimum_matched_pairs": 10,
    "minimum_search_utility_sensitive_pairs": 1,
    "sample_count": 2,
    "maximum_stored_roots": 512,
    "maximum_subset_rows": 0,
    "rejected_or_censored": 0,
}
ROUTE_TEACHER_COVERAGE_GATE = {
    "source_runs": len(ROUTE_TEACHER_BATCH_STARTS) * ROUTE_TEACHER_BATCH_SIZE,
    "minimum_record_groups": 20,
    "minimum_records": 200,
    "required_phases": ["BLIND_SELECT", "PACK", "SHOP"],
    "required_goals": ["victory", "endless"],
    "minimum_route_diverse_groups": 15,
    "minimum_route_diverse_rows": 40,
    "minimum_matched_pairs": 100,
    "minimum_search_utility_sensitive_pairs": 10,
    "minimum_search_utility_positive_pairs": 2,
    "minimum_search_utility_negative_pairs": 2,
    "sample_count": 2,
    "maximum_stored_roots": 512,
    "maximum_subset_rows": 0,
    "rejected_or_censored": 0,
}
