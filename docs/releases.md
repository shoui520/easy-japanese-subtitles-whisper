# Windows ZIP releases

Build using Windows PowerShell 5.1 (no Python needed for packaging):

```powershell
./scripts/build-release.ps1 -Version 0.1.0-preview.1
```

Upload the ZIP and adjacent `.zip.sha256` in `dist/` as GitHub release assets.
Do not upload the development launcher alone, the checkout, or a configured runtime.
The builder refuses to overwrite an existing version's artifacts.

Archive layout:

```text
Easy Japanese Subtitles.exe
Read me.txt
_internal/
  app/
  anime_subs.py
  requirements.txt
  constraints-windows-py314.txt
  scripts/setup-private-runtime.ps1
```

The launcher is compiled for this layout explicitly; it does not search parents
for a repository. First-run setup creates `_internal/.runtime` and logs/settings
under `_internal/.app-data`. No developer/test dependencies are installed.
The allowlisted archive excludes runtimes, models, private data and test media.

This is a bootstrap portable **preview**, not an offline, preinstalled distribution.
It requires Windows 11 x64, WebView2, internet during setup/downloads and a writable
extraction directory. First-run setup offers CUDA or CPU; Intel/AMD GPU runtime
installation is not automated. The executable is unsigned.

Moving an initialized folder is detected through `pyvenv.cfg`; setup reruns to
refresh Python environment paths, retaining packages/downloads/models. Queue
settings recording the old app-owned Python are migrated to the new location.
Custom external Python/tool paths are not rewritten. Updates currently use a
fresh extraction and fresh setup rather than an in-place updater.

Before a public release, manually test actual extraction, native WebView2 startup,
drag/drop, first-run downloads, cancellation, and one transcription on a clean
Windows 11 installation. Automated layout/isolated-PATH tests are not that test.
Publish as a prerelease until this acceptance pass is complete.

No third-party runtime/model binaries are redistributed in the generated ZIP.
Choose a project source license before advertising the project as open source;
this repository currently supplies no general source license. Third-party
downloaded software/model licenses continue to apply independently.
