"""Disposable inference process. Input video is only ever opened for reading."""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from anime_subs import SAMPLE_RATE, read_audio, render_srt
from app.backends import WhisperBackend
from app.media import audio_command, extract_with_progress, subtitle_regions
from app.runtime import friendly_error
from app.download_progress import report_downloads


def emit(stage, progress=None, **fields):
    print("EVENT " + json.dumps(dict(stage=stage, progress=progress, **fields)), flush=True)


def process(request):
    import torch
    source = Path(request["source"])
    job_dir = Path(request["job_dir"])
    device = request.get("device", "auto")
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. Select CPU or check the NVIDIA driver.")
    ffmpeg = request["ffmpeg"]
    emit("Reading subtitle timings", detail="Finding dialogue in the selected subtitle track" if request.get("subtitle_index") is not None else "Using the model's own timestamps")
    regions = None
    if request.get("subtitle_index") is not None:
        regions = subtitle_regions(source, request["subtitle_index"], ffmpeg)
        if not regions:
            raise RuntimeError("The selected subtitle track has no usable timings. Choose another track or model timestamps.")
    emit("Extracting Japanese audio", 0, detail="Reading the selected audio track; your video is unchanged")
    wav = job_dir / "audio.wav"
    # copyts keeps audio and subtitles in the same container time coordinate.
    # Resampling pads positive delay / trims negative timestamps at time zero.
    args = audio_command(source, request['audio_index'], wav, ffmpeg)
    extract_with_progress(args, request.get("duration", 0),
                          lambda p, seconds: emit("Extracting Japanese audio", p, processed_seconds=seconds,
                                                  total_seconds=request.get("duration", 0)), job_dir / "ffmpeg.log")
    audio = read_audio(wav)
    duration = len(audio) / SAMPLE_RATE
    emit("Loading model", device=device, detail="Preparing the transcription model; first use may download model files")
    backend = WhisperBackend(request["model"], device)
    with report_downloads(emit):
        backend.load()
    cues = []
    if regions is None:
        emit("Transcribing", 0, detail="Listening to Japanese audio", processed_seconds=0, total_seconds=duration)
        cues = backend.transcribe(audio, lambda p: emit("Transcribing", p, processed_seconds=p*duration, total_seconds=duration))
    else:
        regions = [(max(0, a), min(duration, b)) for a, b in regions if a < duration and b > 0]
        total = sum(b-a for a,b in regions)
        completed = 0
        for i, (a, b) in enumerate(regions):
            # Half-gap padding preserves context without processing audio twice.
            lo = max(0, a - .1, (regions[i-1][1] + a) / 2 if i else 0)
            hi = min(duration, b + .1, (b + regions[i+1][0]) / 2 if i+1 < len(regions) else duration)
            piece = audio[round(lo*SAMPLE_RATE):round(hi*SAMPLE_RATE)]
            def region_progress(p):
                done = completed + (b-a)*p
                emit("Transcribing", done/max(total, .001),
                     detail=f"Dialogue section {i+1} of {len(regions)}",
                     processed_seconds=done, total_seconds=total,
                     sections_done=i, sections_total=len(regions))
            region_progress(0)
            if not len(piece):
                continue
            result = backend.transcribe(piece, region_progress)
            cues.extend((lo+start, min(hi, lo+end), text) for start, end, text in result)
            region_progress(1)
            completed += b-a
    emit("Saving subtitles", None, detail="Validating Japanese text and timestamps")
    # The supervisor alone publishes the finished SRT. Worker never writes beside input.
    content = render_srt(cues, duration)
    (job_dir / "result.srt").write_text(content, encoding="utf-8")
    emit("Saving subtitles", None, detail="Writing the finished SRT", cues=len(cues), regions=len(regions) if regions is not None else None)
    backend.unload()


def main():
    # Wait until supervisor has attached the Windows Job Object before any children spawn.
    if sys.stdin.readline().strip() != "GO":
        return 1
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        process(request)
        return 0
    except Exception as exc:
        traceback.print_exc()
        emit("Failed", error=friendly_error(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
