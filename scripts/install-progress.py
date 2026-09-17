"""Translate pip's line-based progress into the native setup event protocol."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import threading


def report(stage, detail, progress=None):
    sys.stdout.write('SETUP ' + json.dumps(dict(stage=stage, detail=detail, progress=progress)) + '\n')
    sys.stdout.flush()


class PipProgress:
    def __init__(self, label, clock=time.monotonic):
        self.label = label
        self.clock = clock
        self.filename = ''
        self.started = None
        self.initial = 0
        self.previous = 0
        self.number = 0

    def feed(self, line):
        text = line.strip()
        if text.startswith(('Downloading ', 'Resuming download ')):
            self.filename = text.split(' (', 1)[0].removeprefix('Downloading ').removeprefix('Resuming download ')
            self.filename = self.filename.rsplit('/', 1)[-1].split('?', 1)[0]
            self.started = None
            self.number += 1
            report(f'Downloading {self.label}', f'File {self.number}: {self.filename}')
        match = re.fullmatch(r'Progress (\d+) of (\d+)', text)
        if match:
            current, total = map(int, match.groups())
            now = self.clock()
            if self.started is None or current < self.previous:
                self.started, self.initial = now, current
            self.previous = current
            elapsed = now - self.started
            speed = (current - self.initial) / elapsed if elapsed > 0 else 0
            detail = f'{current / 1048576:.1f} MB'
            if total:
                detail += f' / {total / 1048576:.1f} MB ({min(100, current / total * 100):.0f}%)'
            else:
                detail += ' downloaded (total size unavailable)'
            if speed > 0:
                detail += f' | {speed / 1048576:.1f} MB/s'
                if total and current < total:
                    remaining = max(1, round((total - current) / speed))
                    detail += f' | about {remaining // 60}m {remaining % 60:02d}s left'
            report(f'Downloading {self.label} - file {self.number}',
                   detail + '\n' + self.filename, min(1, current / total) if total else None)
        elif text.startswith('Installing collected packages:'):
            total = len(text.split(':', 1)[1].split(','))
            report(f'Installing {self.label}', f'0 of {total} packages installed', 0)
        elif text.startswith(('Building wheel for ', 'Preparing metadata ', 'Installing build dependencies')):
            report(f'Preparing {self.label}', text)
        elif text.startswith(('Collecting ', 'Using cached ')):
            report(f'Preparing {self.label}', text)
        elif text.startswith('Successfully installed '):
            report(f'Installed {self.label}', 'Installation finished', 1)


def install_with_progress(original, requirements, label, *args, **kwargs):
    """Count successful installs, not starts; failed installs never advance."""
    requirements = list(requirements)
    total = len(requirements)
    completed = 0
    originals = []
    for requirement in requirements:
        install = requirement.install
        originals.append((requirement, install))

        def tracked(*install_args, _install=install, _name=requirement.name, **install_kwargs):
            nonlocal completed
            started = time.monotonic()
            stop = threading.Event()

            def update():
                elapsed = int(time.monotonic() - started)
                report(f'Installing {label}',
                       f'{completed} of {total} packages installed ({completed / total:.0%})\n'
                       f'Installing {_name} - {elapsed // 60}m {elapsed % 60:02d}s elapsed', completed / total)

            def heartbeat():
                while not stop.wait(1):
                    update()

            update()
            thread = threading.Thread(target=heartbeat, daemon=True)
            thread.start()
            try:
                result = _install(*install_args, **install_kwargs)
            finally:
                stop.set()
                thread.join()
            completed += 1
            report(f'Installing {label}',
                   f'{completed} of {total} packages installed ({completed / total:.0%})\n'
                   + (f'Installed {_name}' if completed < total else 'Finalizing installation'), completed / total)
            return result

        requirement.install = tracked
    try:
        return original(requirements, *args, **kwargs)
    finally:
        for requirement, install in originals:
            requirement.install = install


def pip_child(label, arguments):
    # The pinned Python runtime supplies pip. Hook its actual install calls in
    # this disposable child process only; no pip files are edited on disk.
    import pip._internal.req as req
    original = req.install_given_reqs
    req.install_given_reqs = lambda requirements, *args, **kwargs: install_with_progress(
        original, requirements, label, *args, **kwargs)
    from pip._internal.cli.main import main as pip_main
    return pip_main(['--isolated', *arguments, '--progress-bar', 'raw', '--disable-pip-version-check'])


def main():
    if sys.argv[1] == '--pip-child':
        return pip_child(sys.argv[2], sys.argv[3:])
    label, *arguments = sys.argv[1:]
    progress = PipProgress(label)
    # raw emits actual byte counters even with redirected stdout; never parse a
    # terminal animation or estimate download progress from package counts.
    process = subprocess.Popen([sys.executable, '-u', __file__, '--pip-child', label, *arguments],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace', bufsize=1)
    try:
        for line in process.stdout:
            print(line, end='', flush=True)
            progress.feed(line)
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()


if __name__ == '__main__':
    sys.exit(main())
