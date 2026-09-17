"""Full-file AVI/MP4 integration test using disposable byte-identical copies."""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from app.jobs import Queue
from app.media import enumerate_videos


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    roots = [
        (Path(r'D:\Seeding\TV\Anime\[dp] Ichigo 100% OVAs + Special'), '.avi'),
        (Path(r'D:\Seeding\TV\Anime\Bakugan 1-4\Bakugan Mechtanium Surge - 01-46 [C-W]'), '.mp4'),
    ]
    artifacts = Path('.test-artifacts').resolve()
    artifacts.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='containers-', dir=artifacts))
    print('Artifacts:', root, flush=True)
    originals, copies, hashes = [], [], {}
    for folder, extension in roots:
        found = [p for p, _ in enumerate_videos([folder]) if p.suffix.lower() == extension]
        assert found, folder
        source = found[0]
        print('Discovered', len(found), extension, 'files; testing', source.name, flush=True)
        dest = root / extension[1:] / source.name
        dest.parent.mkdir()
        hashes[str(source)] = digest(source)
        shutil.copyfile(source, dest)
        assert digest(dest) == hashes[str(source)]
        originals.append(source); copies.append(dest)
    queue = Queue(root/'state', protected_roots=[folder for folder, _ in roots])
    queue.settings.update(model='anime', device='auto')
    try:
        queue.add([str(copies[0].parent), str(copies[1]), str(copies[0])])
        assert len(queue.items) == 2
        for item in queue.items:
            print('Tracks:', item['name'], item['audio'], item['subtitles'], flush=True)
            if item['audio_index'] is None:
                # Explicit test-only manual choice; never infer Japanese from AVI/MP4.
                assert len(item['audio']) == 1, 'Review ambiguous test audio manually'
                queue.edit(item['id'], {'audio_index': item['audio'][0]['index']})
                print('Test manually selected sole audio stream; language tag:', item['audio'][0]['language'], flush=True)
            assert item['status'] == 'ready', item
        queue.start()
        while queue.thread.is_alive():
            print([(i['name'], i['stage'], round(i.get('progress') or 0, 2))
                   for i in queue.snapshot()['items']], flush=True)
            queue.thread.join(10)
        for item, source, copy in zip(queue.items, originals, copies):
            assert item['status'] == 'complete', item
            output = Path(item['output'])
            assert output == copy.with_suffix('.srt')
            assert '-->' in output.read_text(encoding='utf-8-sig')
            assert digest(source) == digest(copy) == hashes[str(source)]
        assert not list((root/'state/jobs').iterdir())
        (root/'verification.json').write_text(json.dumps({
            'full_file_transcription': True, 'originals_unchanged': True,
            'source_hashes': hashes, 'items': queue.snapshot()['items'],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS: full AVI + MP4, folder/loose discovery, SRT beside each copy, cleanup, original hashes unchanged.', flush=True)
    finally:
        queue.shutdown()


if __name__ == '__main__':
    main()
