The candidate firmware passed a complete ESP-IDF v6.0.2 build in the internal assistant workspace. The official Xtensa GCC 15.2.0 toolchain compiled the source. The build embedded the unchanged production AxeOS bundle, built with Node 24.19.0 from the same upstream revision. The ESP32-S3 image passed its app-partition size check: 0x2c59a0 bytes in the 0x400000-byte partition.

The component manager version was 3.1.2. This execution environment restricts process inspection. The local build dependency uses its documented os.getppid() fallback when psutil raises an error. This bookkeeping adjustment is outside the firmware repository. Its exact source adjustment is retained in the separate lifetime-counter build evidence at commit 69b0885719bc59a2c25049b633406e5dbe507e68, under repro/lifetime-counters/BUILD.md.

The native replay passed with AddressSanitizer and UndefinedBehaviorSanitizer. Leak scanning is disabled for the same process-inspection restriction. The candidate preserves the existing startup and poll delays. Physical retry behavior, permanent hardware-fault handling and accepted shares require hardware review. No device was flashed.

The full firmware commands were:

```sh
GITHUB_ACTIONS=true idf.py reconfigure
GITHUB_ACTIONS=true cmake --build build --parallel 4
```
