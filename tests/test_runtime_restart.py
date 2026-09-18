from types import SimpleNamespace
import sys

import pytest


@pytest.mark.parametrize('busy', [False, True])
def test_native_runtime_change_closes_cleanly_or_refuses_busy_queue(tmp_path, monkeypatch, busy):
    import app.main as main
    import webview
    monkeypatch.setenv('EASY_SUBS_LAUNCHER', '1')
    actual_queue = main.Queue
    captured = {}

    def queue(*args):
        result = actual_queue(*args)
        result.running = busy
        return result

    class Event:
        def __iadd__(self, handler):
            return self

    def destroy():
        captured['destroyed'] = True

    def window(*args, **kwargs):
        captured['bridge'] = kwargs['js_api']
        return SimpleNamespace(events=SimpleNamespace(loaded=Event()), destroy=destroy)

    def start(**kwargs):
        if busy:
            with pytest.raises(ValueError, match='Finish or cancel'):
                captured['bridge'].change_runtime()
        else:
            captured['bridge'].change_runtime()

    monkeypatch.setattr(main, 'Queue', queue)
    monkeypatch.setattr(sys, 'argv', ['app.main', '--data-dir', str(tmp_path)])
    monkeypatch.setattr(webview, 'create_window', window)
    monkeypatch.setattr(webview, 'start', start)
    if busy:
        main.main()
        assert 'destroyed' not in captured
    else:
        with pytest.raises(SystemExit) as exit_info:
            main.main()
        assert exit_info.value.code == 42
        assert captured['destroyed']
