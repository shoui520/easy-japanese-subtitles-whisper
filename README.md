# Easy Japanese Subtitles — milestone 1

A Windows WebView2 app for a local video → Japanese SRT workflow. Drop files or
folders, review the automatically selected Japanese audio and full subtitle track,
choose a model, and start the queue. Models run on your PC.

## Run this development build

The project uses an isolated `.venv`; it does not borrow packages from another
environment. The verified development runtime is Python 3.14.3 on Windows, with
PyTorch 2.11.0 CUDA 12.8 and Transformers 4.57.6.

1. Install Python using Python Install Manager if needed.
2. Install FFmpeg/FFprobe if needed (`winget install --id Gyan.FFmpeg -e`).
3. In this project directory, run `./scripts/setup-dev.ps1` from PowerShell. For a CPU-only
   environment use `./scripts/setup-dev.ps1 -Compute cpu`.
4. Open **build/launcher/Easy Japanese Subtitles.exe**, or run `.\.venv\Scripts\python.exe -m app.main`.

Python and FFmpeg are not bundled. WebView2 Runtime must be present. Setup does not
change system Python packages. This is a development milestone, not the final
automatic first-run bootstrapper or public portable release.

## Repository layout

- `app/`: backend and web UI source.
- `launcher/`: C# launcher source.
- `scripts/setup-dev.ps1`: prepares the isolated developer environment.
- `scripts/build-launcher.ps1`: rebuilds the developer launcher without installing packages.
- `tests/`: automated checks and opt-in media integration tests.
- `build/launcher/`: generated developer launcher (Git ignored).
- `dist/`: reserved for future release packages (Git ignored).
- `.venv/`, `.app-data/`, `.test-artifacts/`: local environment, settings/logs,
  and test media/results (Git ignored).

The launcher in `build/launcher/` runs this checkout's source and root `.venv`.
It is not a standalone portable release. Keep it in that location; moving the
whole checkout together is supported. Rebuilding does not change your queue or logs.

## Files and output

- Add individual videos, several files, or folders; recursive folders are optional.
  Discovery and the file picker share one extension list: MKV, MP4, AVI, MOV, M4V,
  WebM, WMV, ASF, MPG, MPEG, TS, M2TS, MTS, VOB, FLV, and OGV. Actual decoding
  depends on the installed FFmpeg build and the codecs inside each file.
- Duplicate paths are ignored. You can remove individual items, folder entries,
  or inactive queue items. Removing an entry never deletes the video or its SRT.
- Every output goes beside **its own video**, including mixed source directories.
  With no matching loose SRT, `Episode 01.mkv` produces `Episode 01.srt`.
  If a matching loose SRT already exists (such as `.srt` or `.en.srt`), it produces
  `Episode 01.ja.srt`. The model name is not added. Embedded subtitles and SRTs for
  unrelated episodes do not affect naming.
- The exact destination is shown before processing. Each completed item has its
  own **Open folder** button.
- If the selected destination already exists, it is skipped, never overwritten.
  Retrying a completed queue entry reuses its saved destination and skips it.
- One file runs at a time. A failed file does not abort the remaining queue.
- Closing the app cancels running work. Cancelled/failed jobs can be retried.

## Audio and timing

Track selection uses FFprobe metadata and absolute stream indexes. Exactly one
Japanese-tagged track is selected automatically, with a Japanese title heuristic
for missing tags. Ambiguity requires a choice.

For subtitle guidance, prefer a full English text track and exclude signs/songs
or forced-only tracks. Multiple equally plausible tracks require a choice. Users
can override both selections, including choosing **Model timestamps**.

Existing subtitle cues define dialogue regions, grouped up to 25 seconds with
small context padding. The model transcribes Japanese audio inside those regions
and supplies timestamps within them. This does not translate the English text or
force Japanese text into a one-to-one English cue layout. Without usable text
subtitles, the full audio uses the model's timestamps. Image-based subtitle tracks
are not supported as timing guides in this milestone; no OCR is performed.

FFmpeg reads the video without rewriting it. Audio and subtitle extraction share
the container timestamp origin; resampling handles initial audio padding/delay.

## Progress and runtime

The current episode has a stage list, extraction percentage, transcription
percentage, processed audio duration, elapsed time, and an approximate remaining
transcription time. The queue bar counts finished files. Unknown work such as
loading weights uses an indeterminate indicator. Download bytes appear when the
backend reports them. The log refreshes while open and preserves scroll position.

All three adapters use the original prototype's decoding logic. Anime/Large use
Transformers with their own tokenizer; Turbo uses official OpenAI Whisper.
FP16 runs on CUDA; CPU uses FP32. AMD/Intel acceleration has not been implemented.
First use downloads model files into the standard local caches; existing cached
weights are reused. Source audio/video is never uploaded.

The API binds to `127.0.0.1` and requires a per-launch token. Inference runs in a
separate process managed by a Windows Job Object so cancellation also ends child
FFmpeg processes. Only completed SRTs are published. App-owned temporary job
directories are removed after processing; stale directories with an unlocked
ownership marker are removed on next launch.

Settings, queue state, and logs are under `.app-data` by default. The development
app folder therefore needs to be writable. Setup & diagnostics can select explicit
Python/FFmpeg/FFprobe paths. There is no runtime auto-install inside the UI yet.

## Verification

Run `.\.venv\Scripts\python.exe -m pytest -q` for isolated tests. Tests cover
track selection, ambiguity, subtitle regions (including the final region), SRT
validation/no-overwrite, mixed destination paths, API authorization, missing PATH
dependencies, recovery, and guarded stale-job cleanup.

The integration scripts in `tests/` are opt-in. `verify_source.py` reads original
media, records SHA-256 inventories before/after, and redirects all generated files
under the specified artifacts directory. `verify_progress_run.py` copies one
episode into a disposable directory, transcribes it fully, and verifies actual
beside-video SRT publication and progress. `verify_batch.py` uses that copy to
create short fixtures in different folders for guided/unguided transcription,
failure continuation, skipping, cancellation, and cleanup.

The `--output-dir` and `--protect-root` flags are for read-only integration tests.
They are **not used by Easy Japanese Subtitles.exe**. A test destination override displays a prominent
banner. Never use the seeding originals as output targets during automated tests.

Native drag/drop and dialogs still need hands-on Windows acceptance testing when
desktop automation is unavailable. Isolation tests do not prove a clean Windows
installation has all required system components or a compatible GPU driver.
