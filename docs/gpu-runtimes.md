# Windows GPU runtimes

The app supports selecting CUDA (NVIDIA), XPU (Intel), ROCm / HIP (AMD), or CPU.
These are compute runtimes, separate from the three transcription model choices.
Intel/AMD integration is best-effort and has not been exercised on their hardware.
Latest drivers do not make every GPU supported. Consult the vendor's hardware and
driver matrix before installing a runtime.

## Runtime profiles

| Runtime | Python | PyTorch | Installation |
| --- | --- | --- | --- |
| CUDA | 3.14 x64 | 2.11.0, cu128 | Existing `scripts/setup-dev.ps1` |
| XPU | 3.14 x64 | 2.11.0+xpu | Official PyTorch XPU index |
| ROCm / HIP | 3.12 x64 | 2.9.1+rocm7.2.1 | AMD's native Windows 7.2.1 wheels |

The AMD profile deliberately uses a published Windows wheel, not a Linux ROCm
index and not a CUDA compatibility shim. It is a fixed integration baseline, not
a claim that 7.2.1 is the newest ROCm release or supports all Radeon cards.
Python 3.14's dependency freeze is not applied to AMD's Python 3.12 environment;
AMD's non-model transitive dependencies are not yet locked or clean-install-tested.

Official references checked for this implementation:

- [PyTorch Intel GPU setup and supported Windows hardware](https://docs.pytorch.org/docs/2.14/notes/get_start_xpu.html)
- [AMD Windows support matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html)
- [AMD Windows 7.2.1 wheel repository](https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/)
- [PyTorch HIP semantics](https://docs.pytorch.org/docs/2.14/notes/hip.html)

## Isolated setup

Keep the UI in the existing `.venv`. Prepare an alternative worker runtime using
an explicitly chosen Python executable, without replacing the UI/CUDA environment:

```powershell
./scripts/setup-gpu-runtime.ps1 -Compute xpu -PythonExecutable 'C:\path\to\Python314\python.exe'
./scripts/setup-gpu-runtime.ps1 -Compute rocm -PythonExecutable 'C:\path\to\Python312\python.exe'
```

Run only the command matching the test machine. These install large packages into
`.runtimes/xpu` or `.runtimes/rocm`, run `pip check`, and test basic GPU FP16 math.
They never install drivers, change global Python, or overwrite an existing runtime
directory. If setup is interrupted, inspect the partial environment before retrying;
automatic repair/resume of runtime setup is not implemented.

In **Setup & diagnostics**, set Python executable to the resulting
`.runtimes/<runtime>/Scripts/python.exe`, and choose XPU or ROCm / HIP. No launcher
rebuild is needed. A previously prepared vendor environment can also be selected.

Automatic uses the first available CUDA/HIP device, then XPU, then CPU. Separate
PyTorch builds generally expose different accelerators; Automatic does not install
or switch Python environments. An explicitly unavailable runtime is an error, not
a silent CPU fallback. CPU remains manually selectable in every runtime.

## Implementation and validation limits

- AMD uses `torch.version.hip` for identification and PyTorch's `cuda` device/API
  internally, as required by PyTorch. The UI never calls AMD hardware CUDA.
- Intel uses `torch.xpu` and the `xpu` tensor device.
- Anime and Large use eager attention on XPU/HIP to avoid assuming NVIDIA fused
  attention kernels. CUDA retains its existing SDPA path.
- Official Whisper Turbo remains the official implementation. On XPU, its unused
  sparse word-alignment buffer stays on CPU. Segment timestamps are still generated
  normally; word-level alignment is not enabled.
- A small FP16 matrix calculation runs before audio extraction. Passing it does not
  prove that every Whisper operator, model, or GPU memory size works.
- No automatic model substitution or retry on another device occurs after errors.
  The user can select CPU and retry. Failed items do not abort the batch.
- Worker termination continues to release the entire process and its GPU resources.

Tests simulate runtime detection, explicit device choices, missing/broken drivers,
HIP-to-cuda mapping, and Turbo's XPU buffer handling. These are not Intel/AMD GPU
execution tests. NVIDIA regression runs are also not evidence of Intel/AMD accuracy.

Before claiming a card/model combination supported, test all three models on short
Japanese speech, both with and without subtitle timing guidance. Check actual GPU
utilization, Japanese text/timestamps, progress, cancellation, memory exhaustion,
offline reuse, and a mixed-file batch. Keep the diagnostics and job logs from each
test and record Python, PyTorch, GPU, driver, model, runtime, and results.
