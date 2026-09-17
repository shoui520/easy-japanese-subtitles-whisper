"""Observe pinned backends' download bars inside an isolated worker process."""
from contextlib import contextmanager
import importlib
import os
import time


@contextmanager
def report_downloads(callback):
    hf_progress = importlib.import_module("huggingface_hub.utils.tqdm")
    import whisper
    originals = [(hf_progress, "tqdm", hf_progress.tqdm), (whisper, "tqdm", whisper.tqdm)]
    with open(os.devnull, "w") as sink:
        def wrapped(base):
            class DownloadBar(base):
                def __init__(self, *args, **kwargs):
                    self.last_report = 0
                    self.report_closed = False
                    kwargs.update(disable=False, file=sink)
                    super().__init__(*args, **kwargs)
                    self.report()

                def report(self):
                    if getattr(self, "unit", None) not in {"B", "iB"}:
                        return
                    now = time.monotonic()
                    if now - self.last_report < .3 and (not self.total or self.n < self.total):
                        return
                    self.last_report = now
                    callback("Downloading model", min(1, self.n/self.total) if self.total else None,
                             detail=self.desc or "Model weights", downloaded_bytes=self.n, download_bytes=self.total)

                def update(self, amount=1):
                    result = super().update(amount)
                    self.report()
                    return result

                def close(self):
                    if self.report_closed:
                        return
                    self.report_closed = True
                    super().close()
                    self.last_report = 0
                    self.report()
                    if getattr(self, "total", None) and getattr(self, "n", 0) >= self.total:
                        callback("Loading model", None, detail="Preparing downloaded model files")
            return DownloadBar
        try:
            for module, name, base in originals:
                setattr(module, name, wrapped(base))
            yield
        finally:
            for module, name, base in originals:
                setattr(module, name, base)
