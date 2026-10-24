#!/usr/bin/env python3
"""Reproduce expected original failures and corrected counter behavior offline."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'output'
counter_failures = {'alternating_999_1001_ms', 'regular_900_ms', 'alternating_900_1100_ms', 'hourly_persistence'}
checks = [
    ('development-original', 'replay.py', counter_failures),
    ('release-original', 'replay.py', counter_failures),
    ('development-candidate', 'replay.py', set()),
    ('development-original', 'replay_monitor.py', {1, 10}),
    ('development-candidate', 'replay_monitor.py', set()),
]
receipt = []
for snapshot, script, failures in checks:
    target = OUTPUT / (snapshot + '-' + Path(script).stem)
    subprocess.run([sys.executable, str(ROOT / script), '--repo', str(ROOT / 'source' / snapshot), '--output', str(target)], check=True, stdout=subprocess.DEVNULL)
    file_name = 'monitor_results.json' if script == 'replay_monitor.py' else 'results.json'
    result = json.loads((target / file_name).read_text())
    observed = set()
    for case in result['scenarios']:
        if not case['pass']:
            observed.add(case['scenario'] if script == 'replay.py' else case['jitter_ms'])
    if observed != failures:
        raise SystemExit(f'{snapshot}/{script}: expected {failures}, observed {observed}')
    print(f'{snapshot}/{script}: expected behavior reproduced')
    receipt.append({'snapshot': snapshot, 'script': script, 'expected_behavior_observed': True, 'results': result})
OUTPUT.mkdir(exist_ok=True)
(OUTPUT / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('Original failures and candidate corrections reproduced.')
