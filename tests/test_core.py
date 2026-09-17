import json
import os
import sys
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anime_subs import render_srt, save_srt
from app.api import create_app
from app.jobs import Queue
from app.media import choose_audio, choose_subtitles, enumerate_videos, regions_from_srt
from app.runtime import ROOT, executable


def track(index, lang, title, codec="ass", forced=False):
    return dict(index=index, language=lang, title=title, codec=codec, forced=forced)


def test_dual_audio_and_signs_first():
    assert choose_audio([track(1,"eng","English"), track(2,"jpn","Japanese")]) == 2
    assert choose_subtitles([track(3,"eng","English - Signs/Songs"), track(4,"eng","English - Full")]) == 4
    assert choose_subtitles([track(3,"eng","Signs/Songs")]) is None


def test_ambiguity_is_not_guessed():
    assert choose_audio([track(0,"und",""), track(1,"und","")]) is None
    assert choose_audio([track(1,"jpn","Main"), track(2,"jpn","Commentary")]) is None
    assert choose_subtitles([track(3,"eng","Full A"), track(4,"eng","Full B")]) is None
    assert choose_audio([track(5,"und","Japanese Stereo")]) == 5


def test_regions_include_time_zero_and_final_region():
    text="1\n00:00:00,000 --> 00:00:02,000\nHi\n\n2\n00:00:03,000 --> 00:00:04,000\nA\n\n3\n00:01:00,000 --> 00:01:02,000\nEnd"
    assert regions_from_srt(text) == [(0,4),(60,62)]
    assert regions_from_srt("00:00:00,000 --> 00:01:00,000") == [(0,25),(25,50),(50,60)]


def test_folder_queue_duplicates_unicode_and_recursion(tmp_path):
    folder=tmp_path/"[Anime] Queen's 日本語"
    folder.mkdir()
    video=folder/"01.MKV";video.touch()
    nested=folder/"Season 2";nested.mkdir();(nested/"02.mkv").touch()
    (folder/"ignore.txt").touch()
    (folder/'03.AVI').touch();(nested/'04.mp4').touch()
    (folder/'01.srt').touch()
    assert len(list(enumerate_videos([str(folder),str(video)])))==4
    assert len(list(enumerate_videos([str(folder)],False)))==2
    assert len(list(enumerate_videos([str(folder/'03.AVI'),str(nested/'04.mp4')])))==2


def test_remove_group_only_changes_queue(tmp_path):
    q = Queue(tmp_path/'state')
    video = tmp_path/'episode.avi'; video.write_bytes(b'video unchanged')
    subtitle = video.with_suffix('.srt'); subtitle.write_text('subtitle unchanged')
    q.items = [dict(id='a', source=str(video), status='ready'),
               dict(id='b', source=str(tmp_path/'other.mp4'), status='processing')]
    q.remove(['a'])
    assert [i['id'] for i in q.items] == ['b']
    assert video.read_bytes() == b'video unchanged'
    assert subtitle.read_text() == 'subtitle unchanged'
    with pytest.raises(ValueError):
        q.remove(['b'])


def test_srt_and_no_overwrite(tmp_path):
    output=tmp_path/"test.srt"
    content=render_srt([(0,1,"日本語"),(1,2,"")],3)
    save_srt(output,content)
    before=output.read_bytes()
    with pytest.raises(FileExistsError):save_srt(output,"replacement")
    assert output.read_bytes()==before
    assert "00:00:00,000 --> 00:00:01,000" in content
    with pytest.raises(ValueError):render_srt([(float('nan'),1,'a')],2)


def test_outputs_beside_each_source_and_protected(tmp_path):
    q=Queue(tmp_path/'data')
    a=tmp_path/'A'/'01.mkv'; b=tmp_path/'B'/'01.mkv'
    assert q.output_path({'source':str(a)},'anime').parent==a.parent
    assert q.output_path({'source':str(b)},'anime').parent==b.parent
    q.protected=[tmp_path/'A']
    with pytest.raises(ValueError):q.output_path({'source':str(a)},'anime')
    q.output_dir=tmp_path/'outputs'
    assert q.output_path({'source':str(a)},'anime') != q.output_path({'source':str(b)},'anime')


def test_api_rejects_foreign_pages_and_missing_token(tmp_path):
    q=Queue(tmp_path/'data');client=TestClient(create_app(q,'secret'))
    assert client.get('/api/state').status_code==403
    assert client.get('/api/state',headers={'x-app-token':'secret'}).status_code==200
    assert client.post('/api/start',headers={'x-app-token':'secret','origin':'https://evil.example'}).status_code==403
    assert client.get('/',headers={'host':'evil.example'}).status_code==403
    assert 'secret' not in client.get('/').text


def test_missing_dependencies_without_host_path(tmp_path,monkeypatch):
    monkeypatch.setenv('PATH',str(tmp_path))
    with pytest.raises(RuntimeError,match='was not found'):executable('ffmpeg')
    # UI core imports independently of model packages and user site.
    result=subprocess.run([sys.executable,'-I','-S','-c',f"import sys;sys.path.insert(0,{str(ROOT)!r});import app.media,app.backends,app.jobs;print('isolated')"],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_restart_marks_running_as_interrupted(tmp_path):
    q=Queue(tmp_path)
    q.items=[{'id':'x','source':'x.mkv','status':'processing'}];q.persist()
    other=Queue(tmp_path)
    assert other.items[0]['status']=='interrupted'


def test_progress_eta_and_stage_reset():
    from app.progress import apply_event
    item={'stage':'Loading model','detail':'Loading weights'}
    apply_event(item,{'stage':'Transcribing','progress':0},now=100)
    apply_event(item,{'stage':'Transcribing','progress':.25},now=110)
    assert item['eta_seconds']==30
    assert item['phase']==5
    apply_event(item,{'stage':'Saving subtitles','progress':None},now=140)
    assert item['detail']=='' and item['eta_seconds'] is None and item['phase']==6


def test_destination_is_visible_before_start(tmp_path):
    q=Queue(tmp_path/'data')
    source=tmp_path/'episodes'/'01.mkv'
    q.items=[{'id':'test','source':str(source),'status':'ready'}]
    assert Path(q.snapshot()['items'][0]['output'])==source.with_suffix('.srt')


def test_player_friendly_names_and_existing_sidecars(tmp_path):
    q=Queue(tmp_path/'state')
    source=tmp_path/"[Judas] Queen's Blade S1 - 01.mkv"
    source.touch()
    item={'source':str(source)}
    plain=source.with_suffix('.srt')
    japanese=source.with_suffix('.ja.srt')
    for model in ('anime','turbo','large'):
        assert q.output_path(item,model)==plain
    # Other episodes and embedded subtitle tracks do not affect the name.
    (tmp_path/"[Judas] Queen's Blade S1 - 010.srt").write_text('unrelated')
    assert q.output_path(item,'anime')==plain
    source.with_suffix('.en.srt').write_text('English subtitles')
    assert q.output_path(item,'anime')==japanese
    plain.write_text('Existing subtitles')
    assert q.output_path(item,'anime')==japanese
    japanese.write_text('Existing Japanese')
    item.update(id='test',status='ready')
    q._process(item,q.settings)
    assert item['status']=='skipped'
    assert plain.read_text()=='Existing subtitles'
    assert japanese.read_text()=='Existing Japanese'


def test_retry_keeps_previously_published_plain_srt(tmp_path):
    q=Queue(tmp_path/'state')
    source=tmp_path/'Episode.mkv';plain=source.with_suffix('.srt')
    plain.write_text('Previously completed')
    item={'source':str(source),'published_output':str(plain)}
    assert q.output_path(item,'anime')==plain


def test_missing_file_in_downloads_is_not_network_error():
    from app.runtime import friendly_error
    message=friendly_error(RuntimeError('Error opening C:/Users/test/Downloads/missing.mkv: No such file or directory'))
    assert 'file is no longer available' in message
    assert 'download' not in message.lower()


@pytest.mark.skipif(os.name!='nt',reason='Windows ownership locks')
def test_stale_cleanup_preserves_active_and_unowned_directories(tmp_path):
    from app.temporary import clean_stale, job_directory, SIGNATURE
    stale=tmp_path/'job-stale';stale.mkdir()
    (stale/'.easy-subs-job').write_bytes(SIGNATURE)
    (stale/'audio.wav').write_bytes(b'test audio')
    unrelated=tmp_path/'job-not-ours';unrelated.mkdir()
    (unrelated/'keep.txt').write_text('keep')
    with job_directory(tmp_path) as active:
        assert clean_stale(tmp_path)==1
        assert active.exists() and unrelated.exists()
    assert not stale.exists() and unrelated.exists()


@pytest.mark.skipif(os.name!='nt',reason='Windows process tree')
def test_cancel_kills_descendants():
    import time
    import psutil
    from app.runtime import ProcessTree
    code="import sys,subprocess,time;sys.stdin.readline();child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);print(child.pid,flush=True);time.sleep(120)"
    process=subprocess.Popen([sys.executable,'-u','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    tree=ProcessTree(process)
    try:
        process.stdin.write('GO\n');process.stdin.flush()
        child_pid=int(process.stdout.readline())
        descendants=psutil.Process(process.pid).children(recursive=True)
        assert any(p.pid==child_pid for p in descendants)
        tree.close();process.wait(timeout=10)
        _,alive=psutil.wait_procs(descendants,timeout=10)
        assert not alive
    finally:
        tree.close();process.stdin.close();process.stdout.close()


def test_download_events_for_both_backend_units():
    from app.download_progress import report_downloads
    import whisper
    import importlib
    hf=importlib.import_module('huggingface_hub.utils.tqdm')
    events=[]
    with report_downloads(lambda *args,**kwargs:events.append((args,kwargs))):
        with whisper.tqdm(total=100,unit='iB',desc='Turbo') as bar:bar.update(100)
        with hf.tqdm(total=200,unit='B',desc='Anime') as bar:bar.update(200)
    downloads=[e for e in events if e[0][0]=='Downloading model']
    assert any(e[1]['downloaded_bytes']==100 for e in downloads)
    assert any(e[1]['downloaded_bytes']==200 for e in downloads)


def test_close_preserves_pending_queue(tmp_path):
    q=Queue(tmp_path)
    q.items=[{'id':'queued','source':'pending.mkv','status':'ready'}]
    q.shutdown()
    restored=Queue(tmp_path)
    assert restored.items[0]['status']=='ready'
