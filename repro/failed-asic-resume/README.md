# Failed ASIC resume replay

The production power task clears `is_paused` after a call to `mining_start()`, including a call that returns zero. After an unsuccessful resume, the ASIC stays unavailable. Later cycles skip the resume branch because the task already cleared its paused state. This affects the shared user-pause and pool-outage recovery path.

The correction retains the paused state until `mining_start()` returns a nonzero chip count. The complete production task then reaches a second attempt after a transient first failure. Normal recovery still uses one attempt. An active hardware-fault flag prevents resume. A renewed pause request prevents retry until that request clears. Persistent failure retains the stopped branch and the existing startup and poll delays.

The replay compiles the complete production power task and its startup/shutdown helpers. Controlled boundaries replace sensors, NVS, ASIC initialization, voltage commands and RTOS delays. The six scenarios cover normal recovery, one failed resume, persistent failure, pool-outage recovery, a retained hardware fault and a renewed pause. Both original versions reproduce the expected failures. The development candidate passes all six scenarios.

Python 3 and a C compiler with AddressSanitizer and UndefinedBehaviorSanitizer are required. The runner uses no network or external Python packages:

```sh
python3 run.py
```

This proves source control flow at the stated boundaries. Physical ASIC behavior, accepted pool shares, electrical behavior during repeated initialization failures and fleet incidence remain unmeasured. The candidate retains the existing startup delays. Retry backoff and attempt limits require maintainer and hardware review. The separate thermal-recovery branch remains outside this patch.

This differs from PR #2044, which restores retained Standard work after successful chip initialization. Issue #1953 reports a return from a pool outage with no initialization attempt in its logs. This replay supplies an attempted initialization that fails. PR #2006 detects a silent hash domain; this correction adds no new failure detector. The inspected public searches found no matching correction for this exact failed-resume state transition.

`SOURCE.json` identifies the source versions. The snapshots retain the upstream GPL license. `recorded-results.json` contains the original observations. New results and generated C files go under `output/`. Leak scanning is disabled for the execution environment's process-inspection restriction. No device was flashed.
