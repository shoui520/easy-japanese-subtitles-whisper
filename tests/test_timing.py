"""Synthetic delayed audio proves extraction preserves the subtitle time origin."""
import shutil
import wave

import pytest

from app.media import audio_command, extract_with_progress, run, subtitle_regions


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg integration test')
def test_delayed_audio_shares_subtitle_timeline(tmp_path):
    import numpy as np
    ffmpeg=shutil.which('ffmpeg')
    subtitle=tmp_path/'guide.srt'
    subtitle.write_text('1\n00:00:01,000 --> 00:00:02,000\nDialogue\n',encoding='utf-8')
    source=tmp_path/"[test] Queen's 日本語.mkv"
    run([ffmpeg,'-nostdin','-v','error','-n','-f','lavfi','-i','color=size=16x16:rate=10:duration=3',
         '-itsoffset','1','-f','lavfi','-i','sine=frequency=440:sample_rate=16000:duration=1',
         '-i',str(subtitle),'-map','0:v','-map','1:a','-map','2:s','-c:v','ffv1','-c:a','pcm_s16le','-c:s','srt',str(source)])
    wav=tmp_path/'audio.wav';events=[]
    extract_with_progress(audio_command(source,1,wav,ffmpeg),3,lambda p,t:events.append((p,t)),tmp_path/'ffmpeg.log')
    with wave.open(str(wav),'rb') as stream:
        samples=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2')
    assert np.max(np.abs(samples[:int(.9*16000)]))==0
    assert np.max(np.abs(samples[int(1.1*16000):int(1.9*16000)]))>100
    assert subtitle_regions(source,2,ffmpeg)==[(1,2)]
    assert events
