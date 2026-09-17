"""Structured progress for UI; percentages always refer to the current stage."""
import time

PHASES = ["Preparing", "Reading subtitle timings", "Extracting Japanese audio",
          "Loading model", "Transcribing", "Saving subtitles", "Complete"]


def apply_event(item, event, now=None):
    now = time.time() if now is None else now
    stage = event.get("stage", item.get("stage", "Preparing"))
    if stage != item.get("stage"):
        item.update(stage_started_at=now, detail="", eta_seconds=None)
    item.update(event)
    item["updated_at"] = now
    item["phase"] = 4 if stage == "Downloading model" else PHASES.index(stage) + 1 if stage in PHASES else None
    p = item.get("progress")
    if p is not None:
        item["progress"] = max(0, min(1, p))
    elapsed = now - item.get("stage_started_at", now)
    # Estimate only a measured stage; never extrapolate download/model-load time.
    if stage == "Transcribing" and p is not None and .03 <= p < 1 and elapsed >= 5:
        item["eta_seconds"] = max(0, round(elapsed * (1 - p) / p))
    else:
        item["eta_seconds"] = None
