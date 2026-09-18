"""App-owned runtime setup, launched directly by the native progress window."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import urllib.error
import zipfile
from contextlib import contextmanager


def report(stage, detail, progress=None, **extra):
    print('SETUP ' + json.dumps(dict(stage=stage, detail=detail, progress=progress, **extra)), flush=True)


def extended_path(path):
    value = os.path.abspath(path)
    if os.name != 'nt' or value.startswith('\\\\?\\'):
        return value
    if value.startswith('\\\\'):
        return '\\\\?\\UNC\\' + value[2:]
    return '\\\\?\\' + value


def profile(kind):
    if kind not in {'cpu', 'cu128', 'xpu', 'rocm'}:
        raise ValueError('Choose CUDA, Intel XPU, AMD ROCm, or CPU.')
    amd = kind == 'rocm'
    repo = 'https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1'
    return dict(python='3.12.10' if amd else '3.14.3',
                torch='2.9.1+rocm7.2.1' if amd else '2.11.0+' + kind,
                requirement=repo + '/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl' if amd else 'torch==2.11.0+' + kind,
                index='https://pypi.org/simple' if amd else 'https://download.pytorch.org/whl/' + kind,
                constraints='constraints-windows-py312.txt' if amd else 'constraints-windows-py314.txt',
                device='cuda' if kind == 'cu128' else kind,
                sdk=[repo + '/' + name for name in ('rocm_sdk_core-7.2.1-py3-none-win_amd64.whl',
                     'rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl',
                     'rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl', 'rocm-7.2.1.tar.gz')] if amd else [])


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, target, sha, label):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if digest(target) == sha:
            report('Verified ' + label, 'Using the previously downloaded file', 1)
            return
        target.unlink()
    partial = target.with_suffix(target.suffix + '.partial')
    if partial.exists() and digest(partial) == sha:
        partial.replace(target)
        report('Verified ' + label, 'Using the previously downloaded file', 1)
        return
    report('Downloading ' + label, url)
    start = last = time.monotonic()
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code != 416 or not offset:
            raise
        response = urllib.request.urlopen(url, timeout=60)
        offset = 0
    with response:
        if getattr(response, 'status', 200) != 206:
            offset = 0  # Server ignored Range: replace, never append a full response.
        elif not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
            raise RuntimeError('The download server returned an invalid resume range. Retry setup.')
        received = offset
        total = int(response.headers.get('Content-Length', 0))
        total = total + offset if total else 0
        if offset:
            report('Resuming ' + label, f'Continuing from {offset / 1048576:.1f} MB', offset / total if total else None)
        with partial.open('ab' if offset else 'wb') as output:
            while chunk := response.read(256 * 1024):
                output.write(chunk)
                received += len(chunk)
                now = time.monotonic()
                if now - last >= .25 or received == total:
                    speed = (received - offset) / max(now - start, .001)
                    detail = f'{received / 1048576:.1f} MB downloaded | {speed / 1048576:.1f} MB/s'
                    if total:
                        seconds = max(0, round((total - received) / speed))
                        detail = f'{received / 1048576:.1f} / {total / 1048576:.1f} MB ({received / total:.0%}) | {speed / 1048576:.1f} MB/s | about {seconds // 60}m {seconds % 60:02d}s left'
                    report('Downloading ' + label, detail, min(1, received / total) if total else None)
                    last = now
        if total and received < total:
            raise RuntimeError('Download interrupted. Retry setup to continue from the saved progress.')
    report('Verifying ' + label, target.name)
    if digest(partial) != sha:
        partial.unlink()
        raise RuntimeError('Download verification failed. Retry setup: ' + target.name)
    partial.replace(target)


def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        for index, entry in enumerate(entries):
            target = (root / entry.filename).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError('Unsafe archive path')
            source.extract(entry, extended_path(root))
            if index % 50 == 0:
                report('Unpacking media tools', f'{index + 1} of {len(entries)} files', (index + 1) / len(entries))


@contextmanager
def setup_temporary(root):
    # pip/tarfile mix slash styles, so extended-length TEMP paths are not safe.
    # Keep only disposable build scratch in a short, app-owned Windows temp dir.
    sys.path.insert(0, str(root))
    from app.temporary import job_directory, clean_stale
    scratch = Path(os.environ['LOCALAPPDATA']) / 'Temp/ejs'
    scratch.mkdir(parents=True, exist_ok=True)
    clean_stale(scratch)
    with job_directory(scratch) as directory:
        report('Preparing temporary workspace', 'Package-build scratch: ' + str(directory))
        yield directory


def install(root, kind, temporary):
    settings = profile(kind)
    owned = root / '.runtime'
    runtime = owned / 'profiles' / kind
    base = runtime / 'python/python.exe'
    venv = runtime / 'venv'
    ready = owned / 'ready.json'
    if ready.exists() and json.loads(ready.read_text(encoding='utf-8-sig')).get('profile') == kind:
        ready.unlink()
    (owned / 'setup-owned.txt').write_text('easy-japanese-subtitles-private-runtime-v1', encoding='ascii')
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONUTF8='1', TEMP=str(temporary), TMP=str(temporary),
               PATH=os.pathsep.join([str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']]))
    for key in ('PYTHONHOME', 'PYTHONPATH'):
        env.pop(key, None)

    def run(*args):
        print('Running: ' + subprocess.list2cmdline([str(a) for a in args]), flush=True)
        subprocess.run([str(a) for a in args], cwd=root, env=env, check=True)

    archive = owned / 'downloads/ffmpeg-9.0.1-essentials.zip'
    download('https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip',
             archive, 'fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9', 'media tools')
    tools = owned / 'ffmpeg/ffmpeg-9.0.1-essentials_build/bin'
    if not all((tools / name).is_file() for name in ('ffmpeg.exe', 'ffprobe.exe')):
        extract(archive, owned / 'ffmpeg')
    python = venv / 'Scripts/python.exe'
    if not python.is_file() or not (venv / 'pyvenv.cfg').is_file():
        report('Preparing environment', 'Creating the private Python environment')
        run(base, '-m', 'venv', venv)
    else:
        report('Resuming setup', 'Keeping your existing private Python environment')
    pip_wheel = owned / 'downloads/pip-25.3-py3-none-any.whl'
    download('https://files.pythonhosted.org/packages/44/3c/d717024885424591d5376220b5e836c2d5293ce2011523c9de23ff7bf068/pip-25.3-py3-none-any.whl',
             pip_wheel, '9655943313a94722b7774661c21049070f6bbb0a1516bf02f7c8d5d9201514cd', 'package installer')
    report('Preparing installer', 'Installing the verified package installer')
    run(python, '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps', pip_wheel)

    def packages(label, *args):
        # A successful phase is reusable only for the same inputs and environment.
        # pip's private cache also retains completed downloads from a failed phase.
        fingerprint = hashlib.sha256(json.dumps([str(a) for a in args]).encode())
        fingerprint.update((root / 'requirements.txt').read_bytes())
        fingerprint.update((root / settings['constraints']).read_bytes())
        fingerprint.update(str(python.stat().st_mtime_ns).encode())
        checkpoint = venv / ('.setup-' + label.replace(' ', '-') + '.json')
        key = fingerprint.hexdigest()
        if checkpoint.exists() and checkpoint.read_text() == key:
            report('Already installed: ' + label, 'Keeping the completed setup step', 1)
            return
        run(python, '-u', root / 'scripts/install-progress.py', label, 'install',
            '--cache-dir', owned / 'downloads/pip-cache', *args)
        pending_checkpoint = checkpoint.with_suffix('.tmp')
        pending_checkpoint.write_text(key)
        pending_checkpoint.replace(checkpoint)

    if settings['sdk']:
        packages('AMD runtime libraries', *settings['sdk'], '--index-url', 'https://pypi.org/simple')
    packages('transcription engine', settings['requirement'], '--index-url', settings['index'])
    packages('application components', '-r', root / 'requirements.txt', '-c', root / settings['constraints'],
             'torch==' + settings['torch'], '--index-url', 'https://pypi.org/simple')
    report('Checking installation', 'Checking packages and processing device')
    try:
        run(python, '-m', 'pip', 'check')
        run(python, '-c', 'import torch,transformers,whisper,fastapi,uvicorn,webview; from transformers import AutoModelForSpeechSeq2Seq,AutoProcessor')
    except subprocess.CalledProcessError:
        # A damaged/inconsistent environment must not be hidden by checkpoints.
        for marker in venv.glob('.setup-*.json'):
            marker.unlink()
        raise
    run(python, '-m', 'app.setup_check', settings['device'])
    pending = ready.with_suffix('.tmp')
    pending.write_text(json.dumps(dict(python=settings['python'], torch=settings['torch'],
                                     profile=kind, compute=kind, ffmpeg='9.0.1')), encoding='utf-8')
    pending.replace(ready)
    report('Complete', 'Setup finished', 1)


if __name__ == '__main__':
    if '--wait-for-start' in sys.argv and input() != 'GO':
        sys.exit(1)
    try:
        root = Path(__file__).resolve().parent.parent
        with setup_temporary(root) as temporary:
            install(root, sys.argv[1], temporary)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        message = 'Setup could not finish. The live log below shows the failed step. Retry after checking your connection, disk space, and selected GPU.'
        if not isinstance(exc, subprocess.CalledProcessError) or 'setup_check' not in str(exc):
            report('Setup needs attention', message, error=message)
        sys.exit(1)
