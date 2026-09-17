"""Real full-episode run on a COPY. Verifies default beside-video output and progress."""
import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

from app.jobs import Queue


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('source');parser.add_argument('--artifacts',required=True)
    args=parser.parse_args()
    source=Path(args.source).resolve();root=Path(args.artifacts).resolve()
    assert not root.is_relative_to(source.parent)
    root.mkdir(parents=True,exist_ok=True)
    video_dir=root/'[Local test] 日本語';video_dir.mkdir(exist_ok=True)
    copy=video_dir/source.name
    assert not copy.exists(), 'Use a fresh artifact folder; do not overwrite a previous test.'
    before=digest(source)
    shutil.copyfile(source,copy)
    assert digest(copy)==before
    queue=Queue(root/'state',protected_roots=[source.parent])
    queue.add([str(video_dir)])
    assert queue.items[0]['audio_index']==2 and queue.items[0]['subtitle_index']==4
    queue.start()
    observed=[]
    try:
        while queue.thread.is_alive():
            item=queue.snapshot()['items'][0]
            event={k:item.get(k) for k in ('status','stage','progress','detail','processed_seconds','total_seconds','eta_seconds','phase')}
            if not observed or observed[-1]!=event:
                observed.append(event);print(json.dumps(event),flush=True)
            queue.thread.join(.25)
        item=queue.snapshot()['items'][0]
        assert item['status']=='complete',item
        output=Path(item['output'])
        assert output.parent==copy.parent and output.exists()
        assert digest(copy)==before and digest(source)==before
        assert not list((root/'state/jobs').iterdir()),'Temporary files were not cleaned'
        assert any(e['stage']=='Transcribing' and 0<e['progress']<1 for e in observed)
        assert any(e['eta_seconds'] is not None for e in observed)
        (root/'verification.json').write_text(json.dumps({'result':item,'events':observed,'source_sha256':before,'copy_sha256':digest(copy),'source_unchanged':True,'output_beside_mkv':True},indent=2),encoding='utf-8')
        print('PASS: full episode, live progress + ETA, SRT beside copied MKV, originals unchanged, temporary audio removed.',flush=True)
    finally:
        queue.shutdown()


if __name__=='__main__':main()
