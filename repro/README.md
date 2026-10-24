# SV2 mixed acknowledgement replay

This evidence branch adds only a local source-level replay to the five-line accounting correction. The upstream pull request contains the production correction alone.

Requires Python 3, a C11 compiler and, for `--sanitize`, GCC/Clang AddressSanitizer and UndefinedBehaviorSanitizer. From a full checkout of this branch:

```sh
python3 repro/sv2_share_accounting.py --repo . --sanitize --report candidate.json
git worktree add ../esp-miner-accounting-original bb4fd0c7e589858bbeef00ec89342216c1510671
python3 repro/sv2_share_accounting.py --repo ../esp-miner-accounting-original --sanitize --expect-failure --report original.json
```

The script extracts the actual share parsers, acknowledgement cases, and system share-counter functions from the selected checkout, compiles them locally, and feeds binary message payloads through them. Minimal boundary types, a clock, log suppression and latency storage are supplied by the harness. It does not exercise sockets, Noise, the RTOS, an ASIC or a running dashboard.

The 1,546 synthetic traces include all success/error patterns of lengths 1–8 at batch sizes 1, 3 and 10 (1,530), plus 16 concrete cases. Counters are checked after every input event. The extended cases include delayed errors, reversed success batches, foreign channels, truncated payloads, oversized counts, empty batches and a fresh-session reset.

| Trace | Original accepted / rejected / pending | Corrected |
|---|---|---|
| Nine successes held, one immediate error, one success, batch ack of ten | 1 / 1 / 9 | 10 / 1 / 0 |
| Six successes interleaved with six immediate errors, then batch ack | 0 / 6 / 6 | 6 / 6 / 0 |

Recorded native run: original 900 traces with at least one counter mismatch (898 incorrect final states); correction 0. Both sanitizer runs completed without runtime diagnostics. These are source-level component results, not production incident rates or a measurement of pool payments, hash power, energy or mining uptime.

The fix counts acknowledged outcomes; it does not implement duplicate-reply detection or change existing 32-bit sequence rollover handling. The reply ordering is legal under SV2 sections 5.3.13–5.3.14: success may be batched and an error resolves its own submission. Known frame/wire bounds are preserved. Full ESP-IDF build and physical pool/client validation remain pending.

Sources: https://stratumprotocol.org/specification/05-mining-protocol/ ; original source commit bb4fd0c7e589858bbeef00ec89342216c1510671. No pool was contacted during reproduction.
