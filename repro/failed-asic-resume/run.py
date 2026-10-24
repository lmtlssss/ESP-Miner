#!/usr/bin/env python3
"""Require the recorded original faults and the corrected resume behavior."""
import json
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parent
output=root/'output'
receipt=[]
for snapshot,expected_faults in [('development-original',{1,2,3,5}),('release-original',{1,2,3,5}),('development-candidate',set())]:
    target=output/snapshot
    subprocess.run([sys.executable,str(root/'replay.py'),'--repo',str(root/'source'/snapshot),'--output',str(target)],check=True,stdout=subprocess.DEVNULL)
    result=json.loads((target/'results.json').read_text())
    faults={case['scenario'] for case in result['scenarios'] if not case['pass']}
    if faults!=expected_faults:
        raise SystemExit(f'{snapshot}: expected {expected_faults}; observed {faults}')
    print(f'{snapshot}: expected behavior reproduced')
    receipt.append({'snapshot':snapshot,'expected_behavior_observed':True,'results':result})
(output/'verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
