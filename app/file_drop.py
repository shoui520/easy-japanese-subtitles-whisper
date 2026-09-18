"""WebView drops with explicit original-file selection for temporary copies."""
from collections import Counter
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit

from app.media import VIDEO_FILE_FILTER
from app.runtime import ROOT


def temporary_roots():
    roots = [ROOT / '.runtime/tmp', Path(tempfile.gettempdir())]
    for name in ('TEMP', 'TMP'):
        if os.environ.get(name):
            roots.append(Path(os.environ[name]))
    if os.environ.get('LOCALAPPDATA'):
        roots.append(Path(os.environ['LOCALAPPDATA']) / 'Temp')
    return [root.resolve() for root in roots]


def original_paths(paths, pick_originals, roots=None):
    """Never guess a source directory or accept an implicit temp-copy output."""
    paths = [Path(path) for path in paths]
    if not paths:
        raise ValueError('Windows did not provide file paths. Use Add files or Add folder.')
    if any(not path.is_absolute() or not path.exists() for path in paths):
        raise ValueError('Windows did not provide existing original file paths. Use Add files or Add folder.')
    roots = temporary_roots() if roots is None else roots
    suspect = [path for path in paths if any(path.resolve().is_relative_to(root.resolve()) for root in roots)]
    if not suspect:
        return [str(path) for path in paths]
    # Do not partially enqueue a mixed drop if the user cancels the correction.
    selected = pick_originals()
    if not selected:
        return []
    selected = [Path(path) for path in selected]
    def identities(files):
        return Counter((path.name, path.stat().st_size) for path in files if path.is_file())
    if any(not path.is_file() for path in suspect + selected) or identities(suspect) != identities(selected):
        raise ValueError('Select the original versions of all the dropped videos. Nothing was added. You can also use Add files or Add folder.')
    if any(path.resolve() == copy.resolve() for path in selected for copy in suspect):
        raise ValueError('That is still the temporary copy. Select the video in its original folder.')
    return [str(path) for path in paths if path not in suspect] + [str(path) for path in selected]


DROP_SCRIPT = """
if (!window.__easySubsDropHandler) {
  window.__easySubsDropHandler = true;
  document.addEventListener('drop', event => {
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer?.files?.length) {
      chrome.webview.postMessageWithAdditionalObjects('FilesDropped', event.dataTransfer.files);
    } else {
      showError('Windows did not provide file paths. Use Add files or Add folder.');
    }
  });
}
"""


def attach(window, queue):
    import webview
    from System import Action

    def error(message):
        window.evaluate_js(f'showError({json.dumps(str(message))})')

    def process(paths):
        try:
            def pick():
                error('Windows supplied temporary copies. Select the original videos in the file picker so subtitles are saved in the correct folders.')
                return window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                                  file_types=(VIDEO_FILE_FILTER,))
            paths = original_paths(paths, pick)
            if paths:
                queue.add(paths)
        except Exception as exc:
            error(exc)

    def received(sender, args):
        if args.get_WebMessageAsJson() != '"FilesDropped"':
            return
        # Only accept messages from this application's own loopback document.
        expected, actual = urlsplit(window.original_url), urlsplit(str(args.Source))
        if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path):
            return
        objects = args.get_AdditionalObjects()
        paths = [str(item.Path) for item in list(objects or []) if 'CoreWebView2File' in str(type(item))]
        # Keep literal paths; no URL decoding or basename-based matching.
        threading.Thread(target=process, args=(paths,), daemon=True).start()

    def install():
        control = window.native.webview
        control.AllowDrop = False
        window.native.AllowDrop = False
        control.AllowExternalDrop = True
        if not getattr(window, '_file_drop_handler', None):
            control.WebMessageReceived += received
            window._file_drop_handler = received
    window.native.Invoke(Action(install))
    window.evaluate_js(DROP_SCRIPT)
