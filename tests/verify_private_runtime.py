"""Real anime inference via pythonw + HTTP, with only Windows on PATH.

Run using .runtime/venv/Scripts/python.exe. Uses only disposable media copies.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from app.runtime import ROOT, PRIVATE, ProcessTree, executable


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def serve_and_transcribe(video, directory, offline=False):
    env = dict(os.environ, HF_HUB_OFFLINE='1' if offline else '0',
               TRANSFORMERS_OFFLINE='1' if offline else '0')
    log_path = directory/'server.log'
    directory.mkdir()
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),
                                    '-s', '-m', 'app.main', '--headless', '--data-dir', str(directory/'state')],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        tree = ProcessTree(process)
        try:
            deadline = time.monotonic()+90
            while time.monotonic() < deadline:
                match = re.search(r'http://127\.0\.0\.1:\d+/#\S+', log_path.read_text(encoding='utf-8'))
                if match: break
                assert process.poll() is None, log_path.read_text(encoding='utf-8')
                time.sleep(.2)
            assert match, 'Server startup timed out'
            url, token = match.group().split('#')
            def api(route, body=None):
                request = urllib.request.Request(url+'api/'+route,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-App-Token': token, 'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=90) as response:
                    return json.load(response)
            with urllib.request.urlopen(url, timeout=10) as response:
                assert 'Easy Japanese Subtitles' in response.read().decode()
            diagnostics = api('diagnostics', {})
            for tool in ('ffmpeg', 'ffprobe'):
                assert Path(diagnostics[tool]).is_relative_to(PRIVATE)
            assert Path(diagnostics['runtimes'][0]['python']).is_relative_to(PRIVATE/'venv')
            assert not diagnostics['runtimes'][0].get('error'), diagnostics
            api('add', {'paths': [str(video)]})
            item = api('state')['items'][0]
            assert item['status'] == 'ready', item
            api('start', {})
            previous = None
            stages = set()
            deadline = time.monotonic()+1800
            while time.monotonic() < deadline:
                item = api('state')['items'][0]
                stages.add(item['stage'])
                status = (item['status'], item['stage'], round(item.get('progress') or 0, 2))
                if status != previous:
                    print('Offline' if offline else 'Fresh download', status, flush=True)
                    previous = status
                if item['status'] in {'complete', 'failed', 'cancelled', 'skipped'}: break
                time.sleep(2)
            assert item['status'] == 'complete', item
            output = Path(item['output'])
            assert output == video.with_suffix('.srt')
            content = output.read_text(encoding='utf-8-sig')
            assert '-->' in content and re.search('[\u3040-\u30ff\u4e00-\u9fff]', content)
            assert not list((directory/'state/jobs').iterdir())
            return {'offline': offline, 'result': item, 'diagnostics': diagnostics, 'stages': sorted(stages)}
        finally:
            tree.close()
            process.wait(timeout=30)


def main():
    allowed = {str(Path(os.environ['SystemRoot'])/'System32').casefold(),
               str(Path(os.environ['SystemRoot'])).casefold()}
    assert {p.casefold() for p in os.environ['PATH'].split(';') if p} <= allowed
    assert all(shutil.which(name) is None for name in ('python', 'py', 'ffmpeg', 'ffprobe', 'git'))
    assert Path(sys.prefix).resolve() == (PRIVATE/'venv').resolve()
    assert Path(sys.base_prefix).resolve() == (PRIVATE/'python').resolve()
    assert 'include-system-site-packages = false' in (PRIVATE/'venv/pyvenv.cfg').read_text()
    import site
    assert not site.ENABLE_USER_SITE
    assert not any(str(ROOT/'.venv').casefold() in p.casefold() for p in sys.path)
    modules = {}
    for name in ('torch', 'transformers', 'accelerate', 'whisper', 'numpy', 'fastapi', 'webview'):
        module = importlib.import_module(name)
        modules[name] = str(Path(module.__file__).resolve())
        assert Path(modules[name]).is_relative_to(PRIVATE/'venv')
    cache = PRIVATE/'models/huggingface/hub'
    assert not list(cache.rglob('*.safetensors')), 'This verification requires an initially empty model cache'
    source = next((ROOT/'.test-artifacts/progress-v2').rglob('*.mkv')).resolve()
    assert '.test-artifacts' in source.parts
    before = digest(source)
    root = Path(tempfile.mkdtemp(prefix='private-runtime-', dir=ROOT/'.test-artifacts'))
    video = root/source.name
    shutil.copyfile(source, video)
    print('Artifacts:', root, flush=True)
    result = serve_and_transcribe(video, root/'online')
    clip = root/'Offline Japanese clip.mkv'
    subprocess.run([executable('ffmpeg'), '-nostdin', '-v', 'error', '-n', '-ss', '140', '-i', str(video),
                    '-t', '35', '-map', '0:v:0', '-map', '0:2', '-c', 'copy', str(clip)], check=True)
    offline = serve_and_transcribe(clip, root/'offline', offline=True)
    assert digest(source) == digest(video) == before
    report = dict(path=os.environ['PATH'], python=sys.executable, base_prefix=sys.base_prefix,
                  modules=modules, source_unchanged=True, online=result, offline=offline)
    (root/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: private Python + fresh venv, Windows-only PATH, pythonw HTTP UI, fresh anime download, full transcription, offline reuse, beside-video SRT, cleanup.', flush=True)


if __name__ == '__main__':
    main()
