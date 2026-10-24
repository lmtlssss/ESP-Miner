# Cumulative work counter: skipped poll intervals

The lifetime counter estimates hashes from the reported hashrate and elapsed time. In the inspected source, a short poll advances the timestamp before the one-second guard returns. The next update therefore omits that interval. The repair advances the timestamp after the guard.

The complete production function reproduces the error on development commit `bb4fd0c7e589858bbeef00ec89342216c1510671` and v2.15.4 commit `d212a0f948cb3ffd90c7ca9572e9b2cf2d865d80`. Both versions contain the same function. The candidate is [`6dc1e9a`](https://github.com/lmtlssss/ESP-Miner/commit/6dc1e9afd8cda9a60da06235cd025dac7aba6aa6). Its production diff moves one assignment in `main/system.c`.

| Controlled trace at 1000 GH/s | Elapsed time | Original estimate | Candidate estimate |
| --- | ---: | ---: | ---: |
| One-second polls | 20 seconds | 20 trillion hashes | 20 trillion hashes |
| Alternating 999 ms and 1001 ms polls | 20 seconds | 10.01 trillion hashes | 20 trillion hashes |
| Repeated 500 ms polls | 20 seconds | 0 hashes | 20 trillion hashes |
| Alternating 999 ms and 1001 ms polls | 1 hour | 1.8018 quadrillion hashes | 3.6 quadrillion hashes |

The alternating trace loses 49.95% of the expected estimate in the original source. This percentage describes the controlled trace. Device scheduling and fleet prevalence remain unmeasured. The production monitor requests a nominal one-second poll interval. The 500 ms trace checks accumulation behavior outside that nominal cadence.

The replay also covers a delayed poll, a zero-rate period followed by normal operation, low-word carry, first-call baseline preservation, and hourly persistence. Original source passes four cases and fails three. The candidate passes all seven. The saved hourly snapshot contains the corrected total.

The runner extracts the complete function from the selected source file. It supplies controlled clock and NVS functions, plus the three accessed SystemModule fields. The field types match the source header. This is a native source-function replay. Full firmware compilation, RTOS scheduling, and physical devices require separate validation.

The counter still estimates work from sampled hashrate. A grouped interval uses the latest sampled rate. This repair preserves elapsed time. It supplies no measured increase in physical hashing, pool credit, or per-hash success probability.

The failure modes and replay preceded the production edit. The normal native build uses C11 with optimization and compiler warnings as errors. AddressSanitizer and UndefinedBehaviorSanitizer also pass. LeakSanitizer requires process access that this execution host restricts, so the successful sanitizer run uses `ASAN_OPTIONS=detect_leaks=0`.

From a repository checkout containing this directory, run `python3 repro/cumulative_hash_intervals/run.py --source main/system.c --out /tmp/counter-candidate.json`. To replay the retained original function, replace the source path with `repro/cumulative_hash_intervals/original_counter.c`. The original replay exits with status 1 because three cases expose the fault. A C11 compiler and Python 3 are sufficient. Network access, a mining pool, and ASIC hardware are unnecessary for this replay.

The targeted repository search found no matching interval-counter repair. [PR #1555](https://github.com/bitaxeorg/ESP-Miner/pull/1555) introduced lifetime totals. [PR #1988](https://github.com/bitaxeorg/ESP-Miner/pull/1988) concerns omitted zero-rate periods in rolling averages. This patch concerns elapsed time in the cumulative counter. Timing-slot aliasing already appears in the discussion of [PR #2013](https://github.com/bitaxeorg/ESP-Miner/pull/2013), so this investigation preserves that attribution.

The existing drafts [#2044](https://github.com/bitaxeorg/ESP-Miner/pull/2044) and [#2045](https://github.com/bitaxeorg/ESP-Miner/pull/2045) remain separate contributions.

