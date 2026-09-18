"""PGS guides use decoded display states, never OCR or packet duration guesses."""
import json
import os
from pathlib import Path

import pytest

from app import media
from app.runtime import executable


def frame(time, visible=True, end=4294967295, start=0):
    return dict(media_type='subtitle', pts_time=str(time), num_rects=int(visible),
                start_display_time=start, end_display_time=end)


def test_pgs_clears_updates_and_delayed_origin():
    frames = [frame(1.210), frame(1.251), frame(1.293), frame(4, False),
              frame(10), frame(12, False)]
    assert media.regions_from_pgs(frames, 20) == [(1.210, 4), (10, 12)]


def test_pgs_finite_duration_gaps_and_final_display():
    assert media.regions_from_pgs([frame(1, end=1000), frame(8)], 10) == [(1, 2), (8, 10)]
    assert media.regions_from_pgs([frame(0), frame(60, False)], 70) == [(0, 25), (25, 50), (50, 60)]
    assert media.regions_from_pgs([frame(-2), frame(1, False), frame(9)], 10) == [(0, 1), (9, 10)]
    assert media.regions_from_pgs([frame(0, start=500, end=1500)], 2) == [(.5, 1.5)]
    assert media.regions_from_pgs([frame(1, False)], 10) == []


def test_pgs_missing_and_invalid_timestamps_are_not_silently_guessed():
    with pytest.raises(RuntimeError, match='no end timing'):
        media.regions_from_pgs([frame(1)])
    with pytest.raises(RuntimeError, match='invalid timings'):
        media.regions_from_pgs([frame('NaN')], 10)
    with pytest.raises(RuntimeError, match='invalid timings'):
        media.regions_from_pgs([{'media_type': 'subtitle', 'num_rects': 1}], 10)


def test_pgs_english_selection_and_ambiguity(monkeypatch):
    def track(index, lang, title=''):
        return dict(index=index, language=lang, title=title, codec='hdmv_pgs_subtitle')
    assert media.choose_subtitles([track(2, 'chi'), track(3, 'eng')]) == 3
    assert media.choose_subtitles([track(2, 'eng', 'Signs/Songs')]) is None
    assert media.choose_subtitles([track(2, 'eng'), track(3, 'eng')]) is None
    monkeypatch.setattr(media, 'run', lambda args: json.dumps(dict(streams=[
        dict(index=i, codec_type='subtitle', codec_name='hdmv_pgs_subtitle', tags={'language': 'eng'})
        for i in (2, 3)])))
    assert media.inspect(Path('video.mkv'), 'probe')['needs_subtitle_choice']


def test_pgs_routes_to_selected_probe_stream_not_srt_conversion(monkeypatch):
    commands = []
    def run(args):
        commands.append(args)
        return json.dumps({'frames': [frame(1.21), frame(3, False)]})
    monkeypatch.setattr(media, 'run', run)
    source = Path("[日本語] Queen's video.mkv")
    assert media.subtitle_regions(source, 3, 'ffmpeg', codec='hdmv_pgs_subtitle',
                                  ffprobe='private/ffprobe.exe', duration=10) == [(1.21, 3)]
    assert commands == [['private/ffprobe.exe', '-v', 'error', '-select_streams', '3',
                         '-show_frames', '-of', 'json', str(source)]]


@pytest.mark.skipif(not os.environ.get('EASY_SUBS_PGS_FIXTURE'), reason='Optional local PGS video')
def test_real_pgs_video_read_only():
    source = Path(os.environ['EASY_SUBS_PGS_FIXTURE'])
    before = source.stat()
    metadata = media.inspect(source, executable('ffprobe'))
    selected = next(t for t in metadata['subtitles'] if t['index'] == metadata['subtitle_index'])
    assert selected['codec'] == 'hdmv_pgs_subtitle'
    regions = media.subtitle_regions(source, selected['index'], executable('ffmpeg'),
                                     codec=selected['codec'], ffprobe=executable('ffprobe'),
                                     duration=metadata['duration'])
    assert regions
    assert all(0 <= a < b <= metadata['duration'] and b-a <= 25.000001 for a, b in regions)
    assert all(left[1] <= right[0] for left, right in zip(regions, regions[1:]))
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert source.stat().st_size == before.st_size
    print(f'PGS track {selected["index"]}: {len(regions)} regions, {regions[0]} through {regions[-1]}')
