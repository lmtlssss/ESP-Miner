#!/usr/bin/env python3
"""Replay the complete production counter function with a controlled clock."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


def extract_function(source, name):
    match = re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
    if match is None:
        raise ValueError(f"Function {name} is absent")
    level = 1
    cursor = match.end()
    while level:
        if source[cursor] == '{':
            level += 1
        elif source[cursor] == '}':
            level -= 1
        cursor += 1
    return source[match.start():cursor] + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sanitize', action='store_true')
    args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    function = extract_function(source_bytes.decode(), 'SYSTEM_noinit_update')
    harness = Path(__file__).with_name('counter_replay.c')
    with tempfile.TemporaryDirectory(prefix='sc-counter-') as build:
        build = Path(build)
        (build / 'production_counter.inc').write_text(function)
        compiler = shlex.split(os.environ.get('CC', 'cc'))
        flags = ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic']
        if args.sanitize:
            flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
        command = compiler + flags + ['-I', str(build), str(harness), '-o', str(build / 'replay')]
        subprocess.run(command, check=True)
        result = subprocess.run([str(build / 'replay')], text=True, capture_output=True)
        if result.stderr:
            print(result.stderr, end='')
        cases = [json.loads(line) for line in result.stdout.splitlines()]
        receipt = {
            'source': str(args.source),
            'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
            'function_sha256': hashlib.sha256(function.encode()).hexdigest(),
            'compiler': subprocess.check_output(compiler + ['--version'], text=True).splitlines()[0],
            'flags': flags,
            'cases': cases,
            'passed': sum(c['passed'] for c in cases),
            'failed': sum(not c['passed'] for c in cases),
            'returncode': result.returncode,
            'stderr': result.stderr,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
