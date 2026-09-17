"""Explicit read-only real-media verification; all writes stay under --artifacts."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from app.jobs import Queue
from app.media import subtitle_regions
from app.runtime import executable


def inventory(folder):
    result={}
    for path in sorted(folder.rglob('*')):
        if path.is_file():
            with path.open('rb') as f:
                digest=hashlib.file_digest(f,'sha256').hexdigest()
            result[str(path.relative_to(folder))]={'size':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns,'sha256':digest}
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('source');parser.add_argument('--artifacts',required=True)
    parser.add_argument('--transcribe',action='store_true')
    args=parser.parse_args()
    source=Path(args.source).resolve();artifacts=Path(args.artifacts).resolve()
    assert not artifacts.is_relative_to(source)
    artifacts.mkdir(parents=True,exist_ok=True)
    before=inventory(source)
    (artifacts/'source-before.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
    q=Queue(artifacts/'state',artifacts/'outputs',[source])
    try:
        q.add([str(source)])
        report=[]
        for item in q.items:
            assert item['audio_index']==2,item
            assert item['subtitle_index']==4,item
            regions=subtitle_regions(Path(item['source']),4,executable('ffmpeg'))
            assert len(regions)>20
            report.append({'file':item['name'],'audio':item['audio_index'],'subtitles':item['subtitle_index'],'regions':len(regions),'last_region':regions[-1]})
        (artifacts/'tracks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report),flush=True)
        if args.transcribe:
            # Full first episode only; leave other episodes out of the inference batch.
            q.items=q.items[:1]
            q.settings['model']='anime'
            q.start()
            while q.thread.is_alive():
                print(json.dumps(q.snapshot()['items'][0]),flush=True)
                q.thread.join(20)
            item=q.snapshot()['items'][0]
            assert item['status'] in {'complete','skipped'},item
            content=Path(item['output']).read_text(encoding='utf-8-sig')
            assert '-->' in content and any('\u3040'<=c<='\u9fff' for c in content)
            (artifacts/'result.json').write_text(json.dumps(item,indent=2),encoding='utf-8')
    finally:
        q.shutdown()
        after=inventory(source)
        (artifacts/'source-after.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
        assert before==after,'SOURCE INTEGRITY CHECK FAILED'
        print('All source file contents and modification times unchanged.',flush=True)


if __name__=='__main__':main()
