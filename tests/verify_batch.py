"""Exercise a real mixed-folder batch, failure isolation, skips, and cancellation.

Input must be the disposable full-episode COPY produced by verify_progress_run.
"""
import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from app.jobs import Queue
from app.media import run
from app.runtime import executable


def wait(queue):
    previous=None
    while queue.thread.is_alive():
        state=[(i['name'],i['status'],i['stage'],round(i.get('progress') or 0,2)) for i in queue.snapshot()['items']]
        if state!=previous:print(state,flush=True);previous=state
        queue.thread.join(1)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('copy');parser.add_argument('--artifacts',required=True)
    parser.add_argument('--model',choices=['anime','turbo','large'],default='anime')
    args=parser.parse_args()
    source=Path(args.copy).resolve()
    assert '.test-artifacts' in source.parts,'Use the disposable copy only.'
    root=Path(args.artifacts).resolve();root.mkdir(parents=True,exist_ok=True)
    videos=[]
    for name,subtitles in [('Folder A 日本語',True),("Folder B [Queen's]",False)]:
        folder=root/name;folder.mkdir(exist_ok=True)
        video=folder/'Episode 01.mkv'
        if not video.exists():
            args_ff=[executable('ffmpeg'),'-nostdin','-v','error','-n','-ss','140','-i',str(source),'-t','35','-map','0:v:0','-map','0:a']
            if subtitles:args_ff+=['-map','0:s']
            args_ff+=['-c','copy',str(video)]
            run(args_ff)
        videos.append(video)
    queue=Queue(root/'state')
    queue.settings['model']=args.model
    queue.add([str(videos[0].parent),str(videos[1]),str(videos[0])])
    assert len(queue.items)==2
    assert queue.items[0]['subtitle_index']==4
    assert queue.items[1]['subtitle_index'] is None
    # A failure after inspection must not stop the next file.
    bad=dict(queue.items[0],id='missing-test',name='Missing source',source=str(root/'missing.mkv'))
    queue.items.insert(0,bad)
    queue.start();wait(queue)
    assert [i['status'] for i in queue.items]==['failed','complete','complete'],queue.snapshot()
    for video,item in zip(videos,queue.items[1:]):
        assert Path(item['output']).parent==video.parent
        assert Path(item['output']).is_file()
    assert not list((root/'state/jobs').iterdir())
    # Reprocessing must skip complete SRTs and leave their bytes unchanged.
    hashes={i['output']:hashlib.sha256(Path(i['output']).read_bytes()).hexdigest() for i in queue.items[1:]}
    queue.remove(['missing-test'])
    for item in queue.items:queue.edit(item['id'],{})
    queue.start();wait(queue)
    assert all(i['status']=='skipped' for i in queue.items)
    assert hashes=={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in hashes}
    # New output directory ensures cancellation actually starts a worker.
    queue.output_dir=root/'cancel-output'
    queue.edit(queue.items[0]['id'],{})
    queue.start()
    deadline=time.monotonic()+30
    while queue.tree is None and queue.thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
    assert queue.tree is not None
    process=queue.tree.process
    queue.cancel(queue.items[0]['id']);wait(queue)
    assert queue.items[0]['status']=='cancelled'
    assert process.poll() is not None
    assert not list((root/'state/jobs').iterdir())
    assert not list((root/'cancel-output').rglob('*.srt'))
    (root/'verification.json').write_text(json.dumps({'model':args.model,'mixed_folders':True,'failure_continues':True,'no_subtitle_fallback':True,'skip_preserves_srt':True,'cancellation':True,'outputs':list(hashes)},indent=2),encoding='utf-8')
    queue.shutdown()
    print('PASS: mixed folders, same filenames, guided + unguided transcription, failure continuation, skip, cancellation, cleanup.',flush=True)


if __name__=='__main__':main()
