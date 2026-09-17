"""Translate pip's line-based progress into the native setup event protocol."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time


def report(stage, detail, progress=None):
    print('SETUP ' + json.dumps(dict(stage=stage, detail=detail, progress=progress)), flush=True)


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
            report(f'Installing {self.label}', 'Downloads finished. Installing files on your PC.\n' + text.split(':', 1)[1].strip())
        elif text.startswith(('Building wheel for ', 'Preparing metadata ', 'Installing build dependencies')):
            report(f'Preparing {self.label}', text)
        elif text.startswith(('Collecting ', 'Using cached ')):
            report(f'Preparing {self.label}', text)
        elif text.startswith('Successfully installed '):
            report(f'Installed {self.label}', 'Installation finished', 1)


def main():
    label, *arguments = sys.argv[1:]
    progress = PipProgress(label)
    # raw emits actual byte counters even with redirected stdout; never parse a
    # terminal animation or estimate download progress from package counts.
    process = subprocess.Popen([sys.executable, '-u', '-m', 'pip', '--isolated',
                                *arguments, '--progress-bar', 'raw', '--disable-pip-version-check'],
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
