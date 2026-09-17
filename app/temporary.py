"""Only clean app-created job directories with an unlocked ownership marker."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile

SIGNATURE = b"EASY_SUBS_JOB_V1"


def lock(handle):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)


def unlock(handle):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def job_directory(root):
    with tempfile.TemporaryDirectory(prefix="job-", dir=root) as directory:
        path=Path(directory)
        with (path/'.easy-subs-job').open('w+b') as handle:
            handle.write(SIGNATURE);handle.flush();lock(handle)
            try:
                yield path
            finally:
                unlock(handle)


def clean_stale(root):
    if os.name != 'nt':
        return 0
    root=Path(root).resolve()
    cleaned=0
    for child in root.glob('job-*'):
        if not child.is_dir() or child.is_symlink() or child.is_junction() or child.resolve().parent != root:
            continue
        marker=child/'.easy-subs-job'
        if not marker.is_file() or marker.is_symlink():
            continue
        try:
            with marker.open('r+b') as handle:
                if handle.read()!=SIGNATURE:
                    continue
                lock(handle)  # A live supervisor owns this byte until its job finishes.
                unlock(handle)
            shutil.rmtree(child)
            cleaned+=1
        except OSError:
            continue
    return cleaned
