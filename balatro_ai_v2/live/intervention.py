"""One public-state intervention, explicitly not a general learned policy."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from balatro_ai_v2.balatrobot.client import BalatroBotClient
from balatro_ai_v2.solver.actions import action_from_data, action_to_data, is_legal
from balatro_ai_v2.solver.shadow_blind import load_decision
from .runner import RunConfig, SEARCH_VARIANTS, _revision, run_episode
from .strategic import SearchPolicy


class InterventionPolicy(SearchPolicy):
    def __init__(self, observation, action):
        if not is_legal(observation, action):
            raise ValueError('intervention must be legal at its public target')
        super().__init__(**SEARCH_VARIANTS['search-v6'])
        self.target_digest = observation.digest()
        self.intervention = action
        self.applied = False

    def select(self, observation):
        if not self.applied and observation.digest() == self.target_digest:
            if not is_legal(observation, self.intervention):
                raise ValueError('intervention became illegal')
            self.applied = True
            return self.intervention, 'Explicit public-state development intervention.', {
                'development_intervention': True, 'target_digest': self.target_digest}
        return super().select(observation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--decision', type=int, required=True)
    parser.add_argument('--action', required=True, help='Public action JSON')
    parser.add_argument('--seed', required=True)
    parser.add_argument('--port', type=int, default=12347)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.seed.isascii() or not args.seed.isalnum() or not 1 <= len(args.seed) <= 8:
        parser.error('seed must be 1..8 ASCII alphanumeric characters')
    observation, _ = load_decision(args.trace, args.decision)
    policy = InterventionPolicy(observation, action_from_data(json.loads(args.action)))
    config = RunConfig(policy='search-v6', expected_profile='all_unlocked')
    client = BalatroBotClient(port=args.port, timeout=30)
    health = client.health()
    if health.get('profile_mode') != config.expected_profile:
        raise RuntimeError('intervention requires all_unlocked profile')
    if client.gamestate().get('state') != 'MENU':
        raise RuntimeError('intervention requires an idle MENU; never reset an existing game')
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {
        'evidence_kind': 'single_development_intervention_not_generalization',
        'seed': args.seed, 'config': asdict(config), 'server': health,
        'target_digest': policy.target_digest,
        'intervention': action_to_data(policy.intervention), **_revision(),
    }
    with (args.output / 'manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2)
    result = run_episode(client, policy, args.seed, args.output / 'trajectory.jsonl', config)
    result['intervention_applied'] = policy.applied
    result['evidence_kind'] = manifest['evidence_kind']
    with (args.output / 'result.json').open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
