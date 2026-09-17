#!/usr/bin/env python3
"""Batch Japanese MKV -> SRT, with a choice of local Whisper models.

PowerShell (in the folder containing your episodes):
    python anime_subs.py                      # Anime model (unchanged default)
    python anime_subs.py --model anime
    python anime_subs.py --model turbo        # Standard OpenAI Whisper turbo
    python anime_subs.py --model large        # efwkjn/whisper-ja-1.5B
    python anime_subs.py --model both         # Anime batch, then turbo batch (unchanged)
    python anime_subs.py --model all          # Anime, turbo, then large; sequentially
    python anime_subs.py --list-tracks
    python anime_subs.py --model turbo --audio-stream 2

Use the same Python environment that contains your CUDA-enabled PyTorch.
FFmpeg and ffprobe must already be in PATH.
Additional packages, depending on the selected model:
    Anime / large: python -m pip install "transformers==4.57.6" accelerate
    Turbo: python -m pip install --upgrade openai-whisper

Outputs next to each MKV:
    Anime: <episode>.anime.ja.srt
    Turbo: <episode>.turbo.ja.srt
    Large: <episode>.large.ja.srt
"large" means efwkjn/whisper-ja-1.5B, NOT OpenAI's original large model.
Existing outputs for that model are skipped; no existing SRT is overwritten.
The Japanese audio track is selected independently for each MKV. All models
use the same audio extraction and SRT formatting. The anime decoding settings
are unchanged and also used for large; turbo uses OpenAI's standard CLI decoding
defaults. Japanese transcription is explicitly selected for all models. This is
a workflow comparison, not a controlled comparison with identical decoding
settings across the two backends.

Anime and large use FP16, SDPA attention, and one audio file at a time. Actual
VRAM requirements depend on the model and available GPU memory. No quantization,
CPU offloading, or automatic switch to a different model is applied.
The large model's first download is approximately 4.9 GB (not its VRAM usage).
Its author cautions about long-form performance and occasional repetition.

No videos are uploaded or modified. Model downloads are automatic.
"both" and "all" run batches sequentially in separate Python processes using
this same interpreter, so the models are never loaded on the GPU together.
Temporary WAVs are removed after each episode, including on normal failures.

Implementation references:
https://huggingface.co/efwkjn/whisper-ja-anime-v0.3
https://huggingface.co/efwkjn/whisper-ja-1.5B
https://huggingface.co/docs/transformers/v4.57.1/en/model_doc/whisper
https://github.com/openai/whisper
https://github.com/openai/whisper/blob/main/whisper/transcribe.py
https://ffmpeg.org/ffmpeg.html
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

HF_MODEL_IDS = {
    "anime": "efwkjn/whisper-ja-anime-v0.3",
    "large": "efwkjn/whisper-ja-1.5B",
}
OUTPUT_SUFFIXES = {
    "anime": ".anime.ja.srt",
    "turbo": ".turbo.ja.srt",
    "large": ".large.ja.srt",
}
MODEL_GROUPS = {
    "both": ("anime", "turbo"),  # Keep existing commands backward compatible.
    "all": ("anime", "turbo", "large"),
}
SAMPLE_RATE = 16000


def command(args: list[str]) -> str:
    """Use an argument list, not a shell: brackets and apostrophes stay literal."""
    result = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{args[0]} failed.")
    return result.stdout


def audio_streams(video: Path) -> list[dict[str, Any]]:
    data = command([
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index:stream_tags=language,title",
        "-of", "json", str(video),
    ])
    return json.loads(data).get("streams", [])


def tags(stream: dict[str, Any]) -> dict[str, str]:
    return {key.lower(): str(value) for key, value in stream.get("tags", {}).items()}


def describe_streams(streams: list[dict[str, Any]]) -> str:
    if not streams:
        return "  No audio streams."
    return "\n".join(
        f"  index={s['index']}  language={tags(s).get('language', 'untagged')}"
        f"  title={tags(s).get('title', '')}"
        for s in streams
    )


def select_stream(streams: list[dict[str, Any]], override: int | None) -> int:
    if override is not None:
        if any(int(s["index"]) == override for s in streams):
            return override
        raise ValueError(f"Stream {override} is not an audio stream in this file.")
    matches = []
    for stream in streams:
        language = tags(stream).get("language", "").strip().lower().replace("_", "-")
        if language.split("-")[0] in {"ja", "jpn", "jp"}:
            matches.append(int(stream["index"]))
    if len(matches) != 1:
        raise ValueError(
            f"Found {len(matches)} Japanese-tagged audio tracks; not guessing.\n"
            f"{describe_streams(streams)}\n"
            "Confirm the Japanese stream, then rerun with --audio-stream NUMBER."
        )
    return matches[0]


def extract_audio(video: Path, stream_index: int, wav: Path) -> None:
    # Account for initial audio delay and gaps without changing the source MKV.
    command([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
        "-i", str(video), "-map", f"0:{stream_index}", "-vn", "-sn", "-dn",
        "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-af", "aresample=async=1:first_pts=0", "-c:a", "pcm_s16le", str(wav),
    ])


def read_audio(wav: Path) -> Any:
    import numpy as np

    with wave.open(str(wav), "rb") as handle:
        if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError("Expected mono, 16-bit, 16 kHz WAV audio.")
        samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    if samples.size == 0:
        raise ValueError("The extracted audio is empty.")
    return samples.astype(np.float32) / 32768.0


def timestamp(milliseconds: int) -> str:
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def render_srt(cues: list[tuple[float, float, str]], duration: float) -> str:
    """Validate timestamps; never invent a time for a malformed segment."""
    blocks = []
    last_start = -1
    end_of_audio = max(0, round(duration * 1000))
    for start, end, text in cues:
        text = " ".join(text.split()).strip()
        if not text:
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            raise ValueError("The model returned a non-finite timestamp.")
        start_ms = max(0, round(start * 1000))
        end_ms = min(end_of_audio, round(end * 1000))
        if end_ms <= start_ms:
            print("  WARNING: Dropped a zero-length or out-of-range subtitle cue.", flush=True)
            continue
        if start_ms < last_start:
            raise ValueError("The model returned out-of-order timestamps; no SRT was saved.")
        blocks.append(f"{len(blocks) + 1}\n{timestamp(start_ms)} --> {timestamp(end_ms)}\n{text}\n")
        last_start = start_ms
    if not blocks:
        raise ValueError("The model produced no usable timed subtitles; no SRT was saved.")
    return "\n".join(blocks) + "\n"


def save_srt(output: Path, content: str) -> None:
    # Publish only the finished file, so an interrupted run can safely be resumed.
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="\n", dir=str(output.parent),
            prefix=".anime-subs-", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        if output.exists():
            raise FileExistsError(f"Output already exists; refusing to overwrite: {output.name}")
        # Windows rename refuses to replace an existing file.
        temporary.rename(output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_hf_model(model_id: str, device: str = "cuda", cache_dir: str | None = None) -> tuple[Any, Any]:
    """Load a Transformers Whisper model and its own matching audio/token processor."""
    import torch

    try:
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
    except ImportError as exc:
        raise RuntimeError(
            'Missing Transformers dependency. In this same Python environment run: '
            'python -m pip install "transformers==4.57.6" accelerate'
        ) from exc
    print(f"Loading {model_id}. The first run downloads the model files.", flush=True)
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=False, cache_dir=cache_dir)
    try:
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_id, dtype=torch.float16 if device != "cpu" else torch.float32, low_cpu_mem_usage=True,
            use_safetensors=True, attn_implementation=("eager" if device.startswith("xpu") or getattr(torch.version, "hip", None) else "sdpa"), trust_remote_code=False,
            cache_dir=cache_dir,
        ).to(device).eval()
    except torch.cuda.OutOfMemoryError as exc:
        raise RuntimeError(
            f"Not enough free GPU memory to load {model_id}. Close GPU-heavy "
            "applications and rerun. Finished SRT files are kept. "
            "No different model was substituted."
        ) from exc
    # The anime model has a custom vocabulary; the large checkpoint differs.
    # Always use each repository's own tokenizer, feature extractor and generation
    # configuration rather than reusing the anime or OpenAI turbo processor.
    expected_ja = model.generation_config.lang_to_id.get("<|ja|>")
    if expected_ja is None or processor.tokenizer.convert_tokens_to_ids("<|ja|>") != expected_ja:
        raise RuntimeError(f"Model/tokenizer Japanese token IDs do not match for {model_id}.")
    if processor.feature_extractor.feature_size != model.config.num_mel_bins:
        raise RuntimeError(f"Model/processor audio feature sizes do not match for {model_id}.")
    return model, processor


def transcribe(model: Any, processor: Any, audio: Any, progress_callback=None) -> list[tuple[float, float, str]]:
    import torch

    # Preserve the entire episode; Whisper's own long-form decoder advances
    # through it. Returned segments include absolute offsets, including silence.
    inputs = processor(
        audio, sampling_rate=SAMPLE_RATE, return_tensors="pt",
        truncation=False, padding="longest", return_attention_mask=True,
    )
    inputs["input_features"] = inputs["input_features"].to(model.device, dtype=model.dtype)
    inputs["attention_mask"] = inputs["attention_mask"].to(model.device)
    last_percent = -10

    def progress(batch: Any) -> None:
        nonlocal last_percent
        done, total = batch[0].detach().cpu().tolist()
        percent = min(100, int(100 * done / max(total, 1)))
        if progress_callback:
            progress_callback(percent / 100)
        if progress_callback is None and percent >= last_percent + 10:
            print(f"  Transcribing: {percent}%", flush=True)
            last_percent = percent

    with torch.inference_mode():
        result = model.generate(
            **inputs,
            language="japanese", task="transcribe",
            return_timestamps=True, return_segments=True,
            return_dict_in_generate=False,
            condition_on_prev_tokens=False, num_beams=1,
            temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
            logprob_threshold=-1.0, no_speech_threshold=0.6,
            monitor_progress=progress,
        )
    if not isinstance(result, dict) or "segments" not in result:
        raise RuntimeError("Timed segments were not returned. Use transformers==4.57.6.")
    cues = [
        (
            float(segment["start"]), float(segment["end"]),
            processor.tokenizer.decode(segment["tokens"].tolist(), skip_special_tokens=True),
        )
        for segment in result["segments"][0]
    ]
    if progress_callback is None:
        print("  Transcribing: 100%", flush=True)
    return cues


def transcribe_turbo(model: Any, audio: Any) -> list[tuple[float, float, str]]:
    """Use OpenAI's original model/tokenizer and standard CLI decoding defaults."""
    import torch

    with torch.inference_mode():
        result = model.transcribe(
            audio,
            language="ja", task="transcribe", fp16=model.device.type != "cpu", verbose=False,
            # The Python API does not select the CLI's beam/best-of values
            # automatically. Set them explicitly to match the standard CLI.
            beam_size=5, best_of=5,
        )
    if not isinstance(result, dict) or "segments" not in result:
        raise RuntimeError("OpenAI Whisper did not return timed segments.")
    return [
        (float(segment["start"]), float(segment["end"]), str(segment["text"]))
        for segment in result["segments"]
    ]


def run_models(model_names: tuple[str, ...], folder: Path, audio_stream: int | None) -> int:
    """Finish each model's process before starting the next; reclaim GPU memory."""
    failed = False
    for model_name in model_names:
        print(f"\n=== Running {model_name} batch ===", flush=True)
        arguments = [
            sys.executable, str(Path(__file__).resolve()), str(folder),
            "--model", model_name,
        ]
        if audio_stream is not None:
            arguments.extend(["--audio-stream", str(audio_stream)])
        # Blocking, no shell: paths containing [], spaces or apostrophes
        # are passed literally. Use the parent's exact Python environment.
        result = subprocess.run(arguments)
        if result.returncode in (130, -2, -1073741510, 3221225786):
            return 130
        if result.returncode:
            failed = True
            print(f"{model_name} batch finished with errors.", file=sys.stderr, flush=True)
    suffixes = ", ".join(OUTPUT_SUFFIXES[name] for name in model_names)
    print(f"\nModel batches finished. Output suffixes: {suffixes}", flush=True)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", nargs="?", default=".", help="MKV folder; defaults to the current folder")
    parser.add_argument(
        "--model", choices=("anime", "turbo", "large", "both", "all"), default="anime",
        help="anime (default), OpenAI turbo, large (efwkjn/whisper-ja-1.5B), "
             "both (anime + turbo), or all three sequentially",
    )
    parser.add_argument("--audio-stream", type=int, help="Absolute ffprobe audio-stream index, for EVERY input file")
    parser.add_argument("--list-tracks", action="store_true", help="Only list audio tracks; do not load the model")
    args = parser.parse_args()
    if args.audio_stream is not None and args.audio_stream < 0:
        parser.error("--audio-stream must be a non-negative absolute stream index")

    # Keep non-ASCII paths printable even on older Windows console settings.
    for console in (sys.stdout, sys.stderr):
        if hasattr(console, "reconfigure"):
            console.reconfigure(errors="replace")

    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            raise RuntimeError(f"{executable} is not in PATH. Install FFmpeg and reopen PowerShell.")
    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Not a folder: {folder}")
    videos = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mkv"),
        key=lambda p: p.name.casefold(),
    )
    if not videos:
        raise ValueError(f"No MKV files in {folder}")

    if args.model in MODEL_GROUPS and not args.list_tracks:
        return run_models(MODEL_GROUPS[args.model], folder, args.audio_stream)

    # Track listing never needs a model, even with --model both/all.
    output_suffix = OUTPUT_SUFFIXES.get(args.model, OUTPUT_SUFFIXES["anime"])
    jobs: list[tuple[Path, Path, int]] = []
    failures = 0
    skipped = 0
    for video in videos:
        output = video.with_name(video.stem + output_suffix)
        if not args.list_tracks and output.exists():
            print(f"SKIP (output exists): {output.name}", flush=True)
            skipped += 1
            continue
        try:
            streams = audio_streams(video)
            if args.list_tracks:
                print(f"{video.name}\n{describe_streams(streams)}\n", flush=True)
                continue
            stream_index = select_stream(streams, args.audio_stream)
            jobs.append((video, output, stream_index))
            print(f"QUEUED: {video.name} -> audio stream {stream_index}", flush=True)
        except (ValueError, RuntimeError) as exc:
            failures += 1
            print(f"SKIP: {video.name}\n{exc}\n", file=sys.stderr, flush=True)
    if args.list_tracks:
        return 1 if failures else 0
    if not jobs:
        print(f"No pending files. Existing outputs: {skipped}; track errors: {failures}.")
        return 1 if failures else 0

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is missing. Run this script with your existing CUDA-enabled Python environment."
        ) from exc
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available in this Python environment. Use your CUDA-enabled PyTorch environment.")

    print(f"GPU: {torch.cuda.get_device_name(0)}", flush=True)
    processor = None
    if args.model == "turbo":
        try:
            import whisper
        except ImportError as exc:
            raise RuntimeError(
                "Missing OpenAI Whisper. In this same Python environment run: "
                "python -m pip install --upgrade openai-whisper"
            ) from exc
        if not hasattr(whisper, "load_model"):
            raise RuntimeError(
                "The imported 'whisper' module is not OpenAI Whisper. Install 'openai-whisper' "
                "and ensure there is no unrelated whisper.py in this folder."
            )
        print("Loading OpenAI Whisper turbo. The first run downloads the model files.", flush=True)
        model = whisper.load_model("turbo", device="cuda").eval()
    else:
        model_id = HF_MODEL_IDS[args.model]
        if args.model == "large":
            print(
                "Large = efwkjn/whisper-ja-1.5B. Using FP16 / SDPA, one episode at a time.\n"
                "The first model download is approximately 4.9 GB.\n"
                "Author's caveat: long-form performance and occasional repetition; "
                "review the resulting subtitles.",
                flush=True,
            )
        model, processor = load_hf_model(model_id)

    completed = 0
    for number, (video, output, stream_index) in enumerate(jobs, 1):
        print(f"\n[{number}/{len(jobs)}] {video.name}", flush=True)
        try:
            with tempfile.TemporaryDirectory(prefix="anime-subs-") as temporary:
                wav = Path(temporary) / "japanese.wav"
                print(f"  Extracting audio stream {stream_index}...", flush=True)
                extract_audio(video, stream_index, wav)
                audio = read_audio(wav)
                duration = len(audio) / SAMPLE_RATE
                if args.model == "turbo":
                    cues = transcribe_turbo(model, audio)
                else:
                    cues = transcribe(model, processor, audio)
                content = render_srt(cues, duration)
                save_srt(output, content)
                del audio, cues, content
            completed += 1
            print(f"  SAVED: {output.name}", flush=True)
        except torch.cuda.OutOfMemoryError:
            print("CUDA out of memory. Close GPU-heavy apps and rerun; finished SRT files will be skipped.", file=sys.stderr)
            return 1
        except Exception as exc:
            failures += 1
            print(f"  FAILED: {video.name}\n  {exc}", file=sys.stderr, flush=True)
        finally:
            gc.collect()
            torch.cuda.empty_cache()
    print(f"\nFinished. Created: {completed}; existing: {skipped}; failed/skipped for errors: {failures}.")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped. Completed SRT files are kept; rerun the same command to resume.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
