"""Prepare a fixed, tiny offline teacher batch; never call a model or game."""
import argparse
import json
from pathlib import Path

from .shadow_blind import load_decision
from .teacher_packet import make_packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--traces', type=Path, nargs='+', required=True)
    parser.add_argument('--ante', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= len(args.traces) <= 3:
        parser.error('pilot accepts at most three traces per teacher call')
    packets, cases = [], []
    for path in args.traces:
        found = None
        with path.open() as stream:
            for line in stream:
                e = json.loads(line)
                if e.get('event') != 'decision':
                    continue
                public = e['observation']['public_solver']
                if public['phase'] == 'SHOP' and public['ante'] == args.ante:
                    found = e
                    break
        if found is None:
            raise ValueError(f'no requested shop in {path}')
        observation, _ = load_decision(path, found['index'])
        packet = make_packet(observation)
        packets.append(packet)
        cases.append({'case_id': packet['case_id'], 'trace': str(path.resolve()),
                      'decision': found['index'], 'recorded_action': found['action']['public_action']})
    if len({p['case_id'] for p in packets}) != len(packets):
        raise ValueError('duplicate public cases')
    # Provenance and recorded choices are deliberately separate from teacher input.
    args.output.mkdir(parents=True, exist_ok=False)
    for name, data in (('packets.json', packets), ('coordinator.json', {
            'schema_version': 1, 'selection': f'first SHOP at ante {args.ante} per supplied trace',
            'status': 'awaiting_unverified_teacher', 'cases': cases})):
        with (args.output / name).open('x') as stream:
            json.dump(data, stream, separators=(',', ':'))
            stream.write('\n')
    print(json.dumps({'cases': len(cases), 'packet_bytes': (args.output / 'packets.json').stat().st_size,
                      'output': str(args.output)}))


if __name__ == '__main__':
    main()
