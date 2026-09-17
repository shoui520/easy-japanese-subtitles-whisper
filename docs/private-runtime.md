# App-owned runtime and clean-PATH verification

`scripts/setup-private-runtime.ps1` requires only Windows PowerShell 5.1 or later,
network access, disk space, and Windows system components. It does not call system
Python, Python Install Manager, WinGet, Git, curl, 7-Zip, or an installed FFmpeg.
The script sets its process PATH to Windows + System32 before doing any work.
No global PATH, registry registration, Python installation, or driver is changed.

Run with Windows PowerShell 5.1:

```powershell
& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-private-runtime.ps1
```

The execution-policy flag applies only to this invocation. Direct setup refuses to
replace an existing `.runtime/venv` unless `-Resume` is supplied and the directory
is identified as app-owned. Interrupted installs are retained for diagnosis. Retry
reuses verified archives; incomplete downloads restart. The helper refuses to
repair the runtime while its Python processes are running.

The native launcher opens a setup window when the private runtime/media tools are
missing. After choosing the CUDA or CPU runtime and pressing Set up, it displays
download progress and installation stages. It closes automatically on successful
setup and opens the main app. Errors stay visible with Retry and a setup-log link.
Cancel/closing setup kills the gated installer process tree using a Windows Job
Object. Intel/AMD worker-runtime selection remains covered by the separate GPU guide.

Model downloads happen in a dialog inside the web UI. This appears only for actual
downloads, not every cached model load, and closes when model loading completes.
Failure stays visible; cancelling stops the queue. A retry is available after the
queue has stopped. Unknown-length downloads/package installations are indeterminate,
not assigned fabricated percentages.

## Local layout (all Git ignored)

```text
.runtime/
  downloads/       verified vendor archives
  python/          official CPython runtime, python.exe, pythonw.exe, license
  venv/            new isolated environment, independent of root .venv
  ffmpeg/          unmodified Gyan archive contents, including license/readme
  models/          app model cache; not the user's Hugging Face/Whisper cache
  tmp/             setup and verification temporary files
  ready.json       written only after installation and pip check succeed
```

The launcher uses `.runtime/venv` when ready. Explicit custom Python/tool choices
remain supported. Existing settings pointing at the old app-managed `.venv` migrate
to the new app-managed runtime. Default media discovery prefers the private Gyan
executables, then falls back to PATH. Diagnostics uses exactly the same resolver.

This is not a claim that an already-created Windows venv is relocatable. If the
extracted application is moved after setup, venv absolute paths may need rebuilding.
A release bootstrapper must manage that; do not ship this prepared venv as a tested
portable distribution.

## Provenance and licensing

- CPython 3.14.3 x64: official full runtime ZIP used by Python Install Manager,
  `https://www.python.org/ftp/python/3.14.3/python-3.14.3-amd64.zip`.
  SHA-256: `ec781bb03f9638d136b24da7c83b4db1652ce767848aa856a30bb87cfdb1abe4`.
  The full archive and `LICENSE.txt` are retained. This is not an embeddable-Python
  pip workaround. Python documents direct extraction of its offline ZIPs in
  [Using Python on Windows](https://docs.python.org/3.14/using/windows.html#offline-installs).
- FFmpeg 9.0.1 essentials: Gyan's own versioned GitHub mirror,
  `https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip`.
  SHA-256 from gyan.dev:
  `fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9`.
  Gyan labels these binaries GPLv3; the archive is retained intact, including
  `LICENSE` and `README.txt`. See [Gyan builds](https://www.gyan.dev/ffmpeg/builds/)
  and [FFmpeg licensing](https://www.ffmpeg.org/legal.html).

These are local third-party downloads, not committed or published release assets.
Before redistributing a ZIP containing binaries, review the exact license terms
and arrange GPL-compliant Corresponding Source access for FFmpeg and its included
GPL components/build materials. A generic upstream link is not a substitute for
that work. Preserve the Python and Python-package notices as well. This document
records provenance and release obligations; it is not legal advice or certification.

## Verification

`scripts/test-private-runtime.ps1` (5.1-compatible) strips PATH, Python/Conda/CUDA
overrides, and model-cache/token overrides in its own process. It launches the
private venv's interpreter with user-site disabled. The test checks:

- Base Python and every relevant imported package belong to `.runtime`.
- Python, py, Git, FFmpeg and FFprobe cannot be found through PATH.
- A fresh model cache downloads the anime model; no user model cache is reused.
- Private `pythonw.exe` starts the real HTTP server and serves the UI.
- A full disposable episode copy transcribes through the HTTP API, with its SRT
  beside the copy, followed by a short offline inference run using the new cache.
- Media hashes are unchanged and app-owned job temporary files are cleaned.

Run this test only with an initially empty app model cache. Detailed results and
logs are retained under `.test-artifacts/private-runtime-*`. Original seeding
videos are never the output target. Testing on this machine does not simulate an
uninstalled NVIDIA driver, missing Windows components, or absent WebView2 Runtime.
The HTTP UI is exercised; native WebView2 rendering/drag-drop is a separate check.

### Recorded result — 2026-09-17

Setup completed using Windows PowerShell 5.1.26100.9482 and the Windows-only PATH.
The private Python 3.14.3 base and newly created venv passed `pip check`. All 37
automated tests passed under that same isolated PATH using private FFmpeg.
The pythonw/HTTP integration test passed full-episode Japanese Anime transcription
with a newly downloaded model, followed by offline inference on a 35-second clip.
Both outputs were beside their disposable input copies; hashes and cleanup checks
passed. Detailed local evidence is in
`.test-artifacts/private-runtime-8pt66ib4/verification.json` and its job logs.

The media test currently expects the disposable reference episode created by
`tests.verify_progress_run` under `.test-artifacts/progress-v2`; it is not included
in the repository or a release ZIP. This evidence is for the current Windows/NVIDIA
machine, not Intel/AMD hardware or a pristine Windows installation.
