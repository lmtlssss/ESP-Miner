# Lifetime work counter replay

The original `SYSTEM_noinit_update()` advances its timestamp before it rejects an interval shorter than one second. Thus the next call cannot include that interval. At 1000 GH/s, sixty alternating 999 ms and 1001 ms intervals span one minute. The original records 30.03 trillion hashes. The corrected updater records 60 trillion hashes. The same original fault exists in v2.15.4 and development commit `bb4fd0c7e589858bbeef00ec89342216c1510671`.

The production correction moves one assignment after the one-second condition. It retains short intervals until an update commits them. This changes the local lifetime work estimate and the saved counters. Physical hashrate, pool credit and exact attempted-hash exposure have separate meanings. The existing last-sample rate approximation remains in place. The correction cannot reconstruct past lost intervals.

`replay.py` extracts the complete production updater and its getters. `replay_monitor.py` also compiles the complete monitor task. The controlled boundaries supply a monotonic clock, RTOS wake times, ASIC rates and NVS writes. The monitor fixture reports any pending interval shorter than one second. Its expected committed work excludes that interval. This preserves the existing update threshold.

Python 3 and a C compiler with AddressSanitizer and UndefinedBehaviorSanitizer are required. The replay needs no network or Python packages. Run it from any directory:

```sh
python3 run.py
```

The runner requires the expected faults in both original versions and the corrected behavior in the candidate. It also preserves the regular-cadence, zero-rate, low-counter carry and hourly-persistence controls. Results and generated C files go under `output/`. Leak detection is disabled because the research execution environment restricts process inspection. The monitor fixture frees its buffers and destroys its mutex.

The source snapshots retain the upstream GPL license. Their provenance is in `SOURCE.json`. They are source for the replay, rather than complete firmware checkouts. See `BUILD.md` for the separate production-build disposition and the local dependency-manager accommodation. Physical ASIC timing and fleet prevalence remain unmeasured.
