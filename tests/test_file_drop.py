from pathlib import Path
import os
import subprocess
import sys
import pytest

from app.file_drop import original_paths
from app.jobs import Queue


def test_normal_drop_preserves_long_unicode_paths_and_duplicate_names(tmp_path):
    paths = []
    for folder in (tmp_path / ('long-' * 30) / ('directory-' * 10), tmp_path / 'other'):
        folder.mkdir(parents=True)
        path = folder / "[日本語] Queen's 100%20.mkv"
        path.write_bytes(b'video')
        paths.append(str(path))
    assert len(paths[0]) > 260
    assert original_paths(paths, lambda: pytest.fail('Unnecessary picker'), roots=[]) == paths
    queue = Queue(tmp_path / 'state')
    for path in paths:
        assert queue.output_path({'source': path}, 'anime').parent == Path(path).parent


def test_temp_copy_requires_original_and_output_uses_original_folder(tmp_path):
    temp = tmp_path / 'runtime/tmp'
    temp.mkdir(parents=True)
    original = tmp_path / 'videos/episode.mkv'
    original.parent.mkdir()
    original.write_bytes(b'video')
    copy = temp / original.name
    copy.write_bytes(b'video')
    paths = original_paths([str(copy)], lambda: [str(original)], roots=[temp])
    assert paths == [str(original)]
    queue = Queue(tmp_path / 'state')
    assert queue.output_path({'source': paths[0]}, 'anime') == original.with_suffix('.srt')
    assert not list(temp.glob('*.srt'))


def test_cancel_does_not_partially_enqueue_mixed_drop(tmp_path):
    temp = tmp_path / 'runtime/tmp'
    temp.mkdir(parents=True)
    copy = temp / 'episode.mkv'
    copy.touch()
    normal = tmp_path / 'normal.mkv'
    normal.touch()
    assert original_paths([str(normal), str(copy)], lambda: None, roots=[temp]) == []


def test_picker_cannot_confirm_same_temporary_copy(tmp_path):
    copy = tmp_path / 'episode.mkv'
    copy.touch()
    with pytest.raises(ValueError, match='still the temporary copy'):
        original_paths([str(copy)], lambda: [str(copy)], roots=[tmp_path])


def test_picker_rejects_wrong_video(tmp_path):
    temp = tmp_path / 'tmp'
    temp.mkdir()
    copy = temp / 'episode.mkv'
    copy.write_bytes(b'video')
    original = tmp_path / 'episode.mkv'
    original.write_bytes(b'a different video size')
    with pytest.raises(ValueError, match='original versions'):
        original_paths([str(copy)], lambda: [str(original)], roots=[temp])


def test_folder_drop_is_not_reinterpreted_as_browser_upload(tmp_path):
    assert original_paths([str(tmp_path)], lambda: pytest.fail('Unnecessary picker'), roots=[]) == [str(tmp_path)]


@pytest.mark.skipif(os.name != 'nt', reason='Windows WebView2 configuration')
def test_webview_initializes_with_external_drop_enabled(tmp_path):
    # Configuration/bridge test only: this is NOT a physical mouse-drag test.
    code = '''
import sys, threading, webview
from app.file_drop import attach
from types import SimpleNamespace
window = webview.create_window('Drop configuration test', html='<script>function showError(x){}</script>', hidden=True)
errors = []
done = threading.Event()
def loaded():
    try:
        attach(window, SimpleNamespace(add=lambda paths: None))
        from System import Action
        def check():
            assert window.native.webview.AllowExternalDrop
            assert not window.native.webview.AllowDrop
            assert not window.native.AllowDrop
        window.native.Invoke(Action(check))
        assert window.evaluate_js('window.__easySubsDropHandler') is True
        done.set()
    except Exception as exc:
        errors.append(exc)
    finally:
        window.destroy()
window.events.loaded += loaded
webview.start(gui='edgechromium', private_mode=True, storage_path=sys.argv[1])
if errors: raise errors[0]
assert done.is_set()
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'webview')],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
