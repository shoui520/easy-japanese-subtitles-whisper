from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from anime_subs import save_srt
from app.backends import MODELS
from app.media import enumerate_videos, inspect
from app.runtime import DATA, ROOT, ProcessTree, executable, friendly_error, default_python
from app.progress import apply_event
from app.temporary import clean_stale, job_directory

ACTIVE = {"processing", "inspecting"}


class Queue:
    def __init__(self, data_dir=DATA, output_dir=None, protected_roots=()):
        self.data = Path(data_dir)
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "jobs").mkdir(exist_ok=True)
        (self.data / "logs").mkdir(exist_ok=True)
        self.cleaned_jobs = clean_stale(self.data / "jobs")
        self.output_dir = Path(output_dir).resolve() if output_dir else None
        self.protected = [Path(p).resolve() for p in protected_roots]
        self.lock = threading.RLock()
        self.items = []
        self.running = False
        self.closed = False
        self.tree = None
        self.active_id = None
        self.thread = None
        self.settings = {"python": default_python(), "ffmpeg": "", "ffprobe": "", "device": "auto", "model": "anime", "recursive": True}
        self.restore()

    def restore(self):
        state = self.data / "queue.json"
        if state.exists():
            try:
                saved = json.loads(state.read_text(encoding="utf-8"))
                self.settings.update(saved.get("settings", {}))
                if Path(self.settings["python"]).resolve() in {
                    ROOT / ".venv" / "Scripts" / "python.exe",
                    ROOT / ".venv" / "Scripts" / "pythonw.exe",
                }:
                    self.settings["python"] = default_python()
                self.items = saved.get("items", [])
                for item in self.items:
                    if item["status"] in ACTIVE:
                        item.update(status="interrupted", stage="Interrupted last time; retry when ready", progress=0)
            except (ValueError, KeyError, TypeError):
                self.items = []

    def persist(self):
        with self.lock:
            target = self.data / "queue.json"
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps({"settings": self.settings, "items": self.items}, ensure_ascii=False), encoding="utf-8")
            temp.replace(target)

    def snapshot(self):
        with self.lock:
            items = copy.deepcopy(self.items)
            for item in items:
                if item["status"] not in {"complete", "skipped"} and not (item["status"] == "processing" and item.get("output")):
                    try:
                        item["output"] = str(self.output_path(item, self.settings["model"]))
                    except ValueError as exc:
                        item["output_error"] = str(exc)
            return copy.deepcopy({"items": items, "running": self.running,
                                  "settings": self.settings, "models": MODELS,
                                  "output_override": str(self.output_dir) if self.output_dir else None})

    def add(self, paths):
        ffprobe = executable("ffprobe", self.settings["ffprobe"])
        added = []
        for path, group in enumerate_videos(paths, self.settings["recursive"]):
            with self.lock:
                if any(i["source"].casefold() == str(path).casefold() for i in self.items):
                    continue
                item = dict(id=uuid.uuid4().hex, source=str(path), name=path.name, group=group,
                            status="inspecting", stage="Inspecting tracks", progress=0, error=None)
                self.items.append(item)
                added.append(item["id"])
            try:
                metadata = inspect(path, ffprobe)
                with self.lock:
                    item.update(metadata)
                    item["status"] = "ready" if metadata["audio_index"] is not None and not metadata["needs_subtitle_choice"] else "needs_choice"
                    item["stage"] = "Ready" if item["status"] == "ready" else "Choose tracks below"
            except Exception as exc:
                with self.lock:
                    item.update(status="failed", stage="Could not inspect file", error=friendly_error(exc))
            self.persist()
        return added

    def find(self, item_id):
        for item in self.items:
            if item["id"] == item_id:
                return item
        raise ValueError("This queue item no longer exists.")

    def edit(self, item_id, changes):
        with self.lock:
            item = self.find(item_id)
            if item["status"] in ACTIVE:
                raise ValueError("Stop this file before changing its tracks.")
            for key, tracks in (("audio_index", item.get("audio", [])), ("subtitle_index", item.get("subtitles", []))):
                if key in changes:
                    value = changes[key]
                    if value is not None and value not in [t["index"] for t in tracks]:
                        raise ValueError("That stream does not belong to this file.")
                    item[key] = value
            if "subtitle_index" in changes:
                item["needs_subtitle_choice"] = False
            item.update(status="ready" if item.get("audio_index") is not None and not item.get("needs_subtitle_choice") else "needs_choice", error=None, progress=0)
            item["stage"] = "Ready" if item["status"] == "ready" else "Choose tracks below"
            self.persist()

    def remove(self, ids):
        with self.lock:
            if any(i["id"] in ids and i["status"] in ACTIVE for i in self.items):
                raise ValueError("Cancel the active file before removing it.")
            self.items = [i for i in self.items if i["id"] not in ids]
            self.persist()

    def cancel(self, item_id=None):
        with self.lock:
            if item_id is None:
                self.running = False
            for item in self.items:
                if (item_id is None or item["id"] == item_id) and item["status"] in {"ready", "processing"}:
                    item.update(status="cancelled", stage="Cancelled", error=None)
                    if self.active_id == item["id"] and self.tree:
                        self.tree.close()
            self.persist()

    def start(self):
        with self.lock:
            if self.running:
                return
            if self.thread and self.thread.is_alive():
                raise ValueError("Cancellation is finishing. Try again in a moment.")
            executable("ffmpeg", self.settings["ffmpeg"])
            if not Path(self.settings["python"]).is_file():
                raise ValueError("Choose a Python interpreter in Setup first.")
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def output_path(self, item, model):
        source = Path(item["source"]).resolve()
        # Default writes next to EACH source, independent of which folder was dropped.
        directory = self.output_dir or source.parent
        if self.output_dir:
            # Preserve uniqueness when different input folders contain Episode 01.mkv.
            import hashlib
            directory = directory / hashlib.sha256(str(source.parent).encode()).hexdigest()[:10]
        plain = directory / f"{source.stem}.srt"
        japanese = directory / f"{source.stem}.ja.srt"
        published = item.get("published_output")
        # Keep a successful job's destination on retry so it is skipped rather
        # than creating a second copy with .ja. Legacy model suffixes aren't reused.
        if published in {str(plain), str(japanese)} and Path(published).is_file():
            target = Path(published)
        else:
            stem = source.stem.casefold()
            loose = directory.is_dir() and any(
                p.is_file() and p.suffix.casefold() == ".srt" and
                (p.stem.casefold() == stem or p.stem.casefold().startswith(stem + "."))
                for p in directory.iterdir()
            )
            target = japanese if loose else plain
        resolved = target.resolve()
        if any(resolved.is_relative_to(p) for p in self.protected):
            raise ValueError("Test protection: writing inside the protected source folder is forbidden. Select a test output directory.")
        if resolved == source or resolved.suffix.lower() != ".srt":
            raise ValueError("Output must be a separate SRT file.")
        return resolved

    def _run(self):
        try:
            while True:
                with self.lock:
                    if not self.running or self.closed:
                        break
                    item = next((i for i in self.items if i["status"] == "ready"), None)
                    if item is None:
                        break
                    settings = dict(self.settings)
                    item.update(status="processing", stage="Preparing", error=None, progress=None,
                                detail="Starting the transcription engine", phase=1,
                                started_at=time.time(), stage_started_at=time.time(), finished_at=None, eta_seconds=None)
                    self.active_id = item["id"]
                    self.persist()
                try:
                    self._process(item, settings)
                except Exception as exc:
                    with self.lock:
                        if item["status"] != "cancelled":
                            item.update(status="failed", stage="Failed; other files will continue", error=friendly_error(exc))
                finally:
                    with self.lock:
                        if self.tree:
                            self.tree.close()
                            self.tree = None
                        self.active_id = None
                        item["finished_at"] = time.time()
                        self.persist()
        finally:
            with self.lock:
                self.running = False
                self.persist()

    def _process(self, item, settings):
        model = settings["model"]
        output = self.output_path(item, model)
        with self.lock:
            item["output"] = str(output)
            if output.exists():
                item.update(status="skipped", stage="Subtitles already exist", progress=1)
                return
        log_path = self.data / "logs" / f"{item['id']}.log"
        with job_directory(self.data / "jobs") as job_dir:
            request = dict(source=item["source"], audio_index=item["audio_index"], subtitle_index=item.get("subtitle_index"),
                           model=model, device=settings["device"], duration=item.get("duration", 0),
                           ffmpeg=executable("ffmpeg", settings["ffmpeg"]), job_dir=str(job_dir))
            request_path = job_dir / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            with log_path.open("w", encoding="utf-8") as log:
                log.write(json.dumps(request) + "\n")
                with self.lock:
                    if item["status"] == "cancelled":
                        return
                    process = subprocess.Popen([settings["python"], "-u", "-m", "app.worker", str(request_path)],
                                               cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                               text=True, encoding="utf-8", errors="replace",
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                               env={**os.environ, "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1"})
                    self.tree = ProcessTree(process)
                    process.stdin.write("GO\n")
                    process.stdin.flush()
                    process.stdin.close()
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    if line.startswith("EVENT "):
                        event = json.loads(line[6:])
                        with self.lock:
                            if item["status"] != "cancelled":
                                apply_event(item, event)
                code = process.wait()
                process.stdout.close()
                with self.lock:
                    if item["status"] == "cancelled":
                        return
                    if code or not (job_dir / "result.srt").exists():
                        raise RuntimeError(item.get("error") or "Transcription stopped unexpectedly. View the log for details.")
                    item["stage"] = "Saving subtitles"
                    output.parent.mkdir(parents=True, exist_ok=True)
                    save_srt(output, (job_dir / "result.srt").read_text(encoding="utf-8"))
                    item["published_output"] = str(output)
                    apply_event(item, dict(stage="Complete", progress=1, detail=f"Saved {item.get('cues', 0)} Japanese subtitle cues"))
                    item["status"] = "complete"

    def shutdown(self):
        with self.lock:
            self.closed = True
            self.running = False
            if self.active_id:
                self.cancel(self.active_id)
            self.persist()
        if self.thread:
            self.thread.join(timeout=15)
