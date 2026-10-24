The production firmware compiled with ESP-IDF v6.0.2 and the official Xtensa GCC 15.2.0 toolchain. Node 24.19.0 built the production AxeOS bundle. The build embedded that bundle into the firmware through the project's CI configuration. The ESP32-S3 image passed the app-partition size check. The resulting binary uses 0x2c59a0 bytes of the 0x400000-byte app partition.

The component manager version was 3.1.2. Its process lookup stopped configuration with `psutil.NoSuchProcess` in this execution environment. The local build dependency used `os.getppid()` when `psutil` could not inspect the process tree. That function already documents this parent-PID fallback. This build-environment adjustment affects bookkeeping outside the firmware repository. The proposed firmware patch contains only the timestamp assignment move.

The native counter replay used UndefinedBehaviorSanitizer and the floating-point conversion sanitizer. The complete monitor replay also used AddressSanitizer. Both completed with the expected source behavior. Leak detection remains disabled because of the process-inspection restriction. Hardware timing, physical ASIC behavior and fleet prevalence remain separate, unmeasured quantities. No device was flashed.

The full firmware build used these commands after the production frontend build:

```sh
GITHUB_ACTIONS=true idf.py reconfigure
GITHUB_ACTIONS=true cmake --build build --parallel 8
```

The original component-manager fallback adjustment was:

```python
try:
    current = psutil.Process()
    parent = current.parent()
    while parent is not None:
        if 'cmake' in parent.name().lower():
            return parent.pid
        parent = parent.parent()
except psutil.Error:
    return os.getppid()
```
