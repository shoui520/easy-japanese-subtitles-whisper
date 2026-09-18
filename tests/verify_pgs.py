"""Opt-in real PGS-guided anime transcription; all outputs stay in artifacts."""
import argparse
import hashlib
import json
from pathlib import Path

from app.jobs import Queue


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('--artifacts', required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    artifacts = Path(args.artifacts).resolve()
    assert not artifacts.is_relative_to(source.parent)
    before = digest(source)
    queue = Queue(artifacts / 'state', artifacts / 'outputs', [source.parent])
    try:
        queue.add([str(source)])
        item = queue.items[0]
        selected = next(t for t in item['subtitles'] if t['index'] == item['subtitle_index'])
        assert selected['codec'] == 'hdmv_pgs_subtitle'
        queue.settings['model'] = 'anime'
        queue.start()
        last = None
        while queue.thread.is_alive():
            item = queue.snapshot()['items'][0]
            state = (item['stage'], item.get('detail'))
            if state != last:
                print(state, flush=True)
                last = state
            queue.thread.join(1)
        item = queue.snapshot()['items'][0]
        assert item['status'] == 'complete', item
        result = Path(item['output']).read_text(encoding='utf-8-sig')
        assert '-->' in result and any('\u3040' <= c <= '\u9fff' for c in result)
        assert not list((artifacts / 'state/jobs').iterdir())
        assert digest(source) == before
        (artifacts / 'verification.json').write_text(json.dumps(item, indent=2), encoding='utf-8')
        print('PASS: PGS-guided anime transcription, Japanese SRT, temporary files cleaned, source unchanged.', flush=True)
    finally:
        queue.shutdown()


if __name__ == '__main__':
    main()
