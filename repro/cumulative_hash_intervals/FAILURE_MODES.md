# Counter interval repair: failure modes before implementation

The counter estimates work from the reported rate and elapsed time. This review concerns the estimate.

1. A poll earlier than 1000 ms can discard elapsed time if it advances the accounting timestamp.
2. Repeated short polls can prevent every counter update.
3. A repair can count one interval twice if it retains an already consumed timestamp.
4. The first call must establish a baseline and preserve retained work.
5. An exact one-second cadence and a longer scheduling delay must retain their existing totals.
6. Zero-rate periods must contribute zero work. A subsequent positive rate must resume accumulation.
7. Addition must preserve the carry between the two existing 64-bit counter words.
8. Hourly persistence must preserve its existing interval and all three saved values.
9. A grouped interval uses the current sampled rate. This remains an estimate of physical work.
10. The native replay controls the clock and NVS boundary. Physical scheduling frequency remains unmeasured.

The replay will use the complete production function from each selected source. The source edit will follow the original replay.
