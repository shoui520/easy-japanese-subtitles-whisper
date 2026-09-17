"""Read-only media inspection and explicit stream selection."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

TEXT_SUBS = {"ass", "ssa", "subrip", "webvtt", "mov_text", "text"}
VIDEO_EXTENSIONS = frozenset({
    ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".webm", ".wmv", ".asf",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".vob", ".flv", ".ogv",
})
VIDEO_FILE_FILTER = "Video files (" + ";".join("*" + ext for ext in sorted(VIDEO_EXTENSIONS)) + ")"


def run(args):
    result = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:] or "The media tool could not read this file.")
    return result.stdout


def extract_with_progress(args, duration, callback, error_path):
    """FFmpeg's machine-readable progress, not parsing its decorative console log."""
    with Path(error_path).open("w+", encoding="utf-8") as errors:
        process = subprocess.Popen([args[0], "-progress", "pipe:1", "-nostats", *args[1:]],
                                   stdout=subprocess.PIPE, stderr=errors, text=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            for line in process.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us":
                    try:
                        seconds = max(0, int(value) / 1_000_000)
                        callback(min(1, seconds / duration) if duration > 0 else None, seconds)
                    except ValueError:
                        pass
            if process.wait():
                errors.seek(0)
                raise RuntimeError(errors.read()[-3000:] or "Audio extraction failed.")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()


def audio_command(source, index, wav, ffmpeg):
    return [ffmpeg, "-nostdin", "-v", "error", "-n", "-copyts", "-i", str(source),
            "-map", f"0:{index}", "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
            "-af", "aresample=async=1:first_pts=0", "-c:a", "pcm_s16le", str(wav)]


def language(stream):
    return stream["language"].lower().replace("_", "-").split("-")[0]


def choose_audio(tracks):
    tagged = [t for t in tracks if language(t) in {"ja", "jpn", "jp"}]
    candidates = tagged or [t for t in tracks if re.search(r"japanese|日本語|\bjpn\b|\bjap\b", t["title"], re.I)]
    if len(candidates) == 1:
        return candidates[0]["index"]
    return None


def is_partial(track):
    title = track["title"].lower()
    return bool(track.get("forced") or re.search(r"signs?|songs?|forced|karaoke|commentary", title)) and not bool(re.search(r"\bfull\b|dialogue", title))


def choose_subtitles(tracks):
    candidates = [t for t in tracks if t["codec"] in TEXT_SUBS and not is_partial(t)]
    english = [t for t in candidates if language(t) in {"en", "eng"} or "english" in t["title"].lower()]
    candidates = english or candidates
    full = [t for t in candidates if re.search(r"\bfull\b|dialogue", t["title"], re.I)]
    candidates = full or candidates
    return candidates[0]["index"] if len(candidates) == 1 else None


def inspect(path: Path, ffprobe: str):
    data = json.loads(run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))
    audio, subtitles = [], []
    for s in data.get("streams", []):
        if s.get("codec_type") not in {"audio", "subtitle"}:
            continue
        tags = {k.lower(): str(v) for k, v in s.get("tags", {}).items()}
        track = dict(index=s["index"], language=tags.get("language", "und"),
                     title=tags.get("title", ""), codec=s.get("codec_name", "unknown"),
                     channels=s.get("channels"), start=s.get("start_time"),
                     forced=bool(s.get("disposition", {}).get("forced")))
        (audio if s["codec_type"] == "audio" else subtitles).append(track)
    selected = choose_subtitles(subtitles)
    # Absence of a usable full track is not permission to use a signs track.
    ambiguous = selected is None and any(t["codec"] in TEXT_SUBS and not is_partial(t) for t in subtitles)
    return dict(audio=audio, subtitles=subtitles, audio_index=choose_audio(audio),
                subtitle_index=selected, needs_subtitle_choice=ambiguous,
                duration=float(data.get("format", {}).get("duration", 0)),
                timing_note=("Using full subtitle timing regions" if selected is not None else
                             "Choose a subtitle track or use model timestamps" if ambiguous else
                             "No usable full subtitles; using model timestamps"))


def subtitle_regions(source, index, ffmpeg):
    """Extract text subtitles to memory; neither source nor sidecars are written."""
    text = run([ffmpeg, "-nostdin", "-v", "error", "-copyts", "-i", str(source),
                "-map", f"0:{index}", "-f", "srt", "-"])
    return regions_from_srt(text)


def regions_from_srt(text, max_seconds=25.0, max_gap=2.0):
    def seconds(parts):
        h, m, s, ms = map(int, parts)
        return h * 3600 + m * 60 + s + ms / 1000
    cues = []
    for match in re.finditer(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})", text):
        a, b = seconds(match.groups()[:4]), seconds(match.groups()[4:])
        if b > a:
            cues.append((a, b))
    # First union overlaps so padding/chunk boundaries cannot duplicate audio.
    merged = []
    for a, b in sorted(cues):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    grouped = []
    for a, b in merged:
        if grouped and a - grouped[-1][1] <= max_gap and b - grouped[-1][0] <= max_seconds:
            grouped[-1] = (grouped[-1][0], b)
        else:
            grouped.append((a, b))
    # Split unusually long cues as well; include the final pending region.
    result = []
    for a, b in grouped:
        while b - a > max_seconds:
            result.append((a, a + max_seconds))
            a += max_seconds
        result.append((a, b))
    return result


def enumerate_videos(paths, recursive=True):
    seen = set()
    for item in paths:
        p = Path(item).expanduser().resolve()
        files = sorted(p.rglob("*") if recursive else p.glob("*")) if p.is_dir() else [p]
        for file in files:
            if file.is_file() and file.suffix.lower() in VIDEO_EXTENSIONS:
                resolved = file.resolve()
                key = str(resolved).casefold()
                if key not in seen:
                    seen.add(key)
                    yield resolved, str(p if p.is_dir() else p.parent)
