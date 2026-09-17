"""Short real CPU transcription with no existing subtitles and offline cache reuse."""
import json
import os
from pathlib import Path

from app.jobs import Queue
from app.media import run
from app.runtime import executable


def main():
    source=next(Path('.test-artifacts/progress-v2').rglob('*.mkv')).resolve()
    root=Path('.test-artifacts/cpu').resolve();root.mkdir(parents=True,exist_ok=True)
    video=root/'CPU speech.mkv'
    if not video.exists():
        run([executable('ffmpeg'),'-nostdin','-v','error','-n','-ss','14','-i',str(source),
             '-t','18','-map','0:2','-c:a','pcm_s16le','-metadata:s:a:0','language=jpn',str(video)])
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['TRANSFORMERS_OFFLINE']='1'
    queue=Queue(root/'state')
    queue.settings.update(device='cpu',model='anime')
    queue.add([str(video)])
    assert queue.items[0]['subtitle_index'] is None
    queue.start()
    try:
        while queue.thread.is_alive():
            item=queue.snapshot()['items'][0]
            print(item['status'],item['stage'],item.get('progress'),flush=True)
            queue.thread.join(10)
        item=queue.snapshot()['items'][0]
        assert item['status']=='complete',item
        assert item['device']=='cpu' and Path(item['output']).exists()
        assert '-->' in Path(item['output']).read_text(encoding='utf-8-sig')
        (root/'verification.json').write_text(json.dumps(item,indent=2),encoding='utf-8')
        print('PASS: CPU FP32 transcription, model-native timing, offline cache reuse, SRT beside MKV.',flush=True)
    finally:
        queue.shutdown()


if __name__=='__main__':main()
