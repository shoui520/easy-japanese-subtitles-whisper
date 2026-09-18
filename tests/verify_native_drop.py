"""Hidden WebView integration: deliver a real OLE data object to its registered target."""
import os
from pathlib import Path
import subprocess
import threading
import webview

from app.native_drop import attach
from app.runtime import ROOT
from app.jobs import Queue as AppQueue


def main():
    root = ROOT / '.test-artifacts/native-drop'
    root.mkdir(parents=True, exist_ok=True)
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    native_library = ROOT / 'build/native/EasySubs.Native.dll'
    native_library.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(compiler), '/nologo', '/target:library', '/platform:x64',
                    '/reference:System.Windows.Forms.dll', '/out:' + str(native_library),
                    str(ROOT / 'launcher/NativeDrop.cs')], check=True)
    library = root / 'NativeDropSmoke.dll'
    subprocess.run([str(compiler), '/nologo', '/target:library', '/reference:System.Windows.Forms.dll',
                    '/reference:' + str(ROOT / 'build/native/EasySubs.Native.dll'),
                    '/out:' + str(library), str(ROOT / 'tests/NativeDropSmoke.cs')], check=True)
    folder = root / ('long-folder-' * 12) / ('long-folder-' * 8)
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "[日本語] Queen's 100%20.mkv"
    source.touch()
    second = root / source.name
    second.touch()
    paths = [str(source), str(second), str(folder)]
    if os.environ.get('EASY_SUBS_DROP_FIXTURE'):
        real_source = Path(os.environ['EASY_SUBS_DROP_FIXTURE']).absolute()
        assert real_source.is_file(), str(real_source)
        paths.append(str(real_source))
    assert len(paths[0]) > 260
    finished = threading.Event()
    errors = []
    actual_queue = AppQueue(root / 'state')
    class Queue:
        def add(self, incoming):
            try:
                assert incoming == paths, (incoming, paths)
                actual_queue.add(incoming)
                for original in (Path(path) for path in paths if Path(path).is_file()):
                    item = next(item for item in actual_queue.items if item['source'] == str(original.resolve()))
                    assert actual_queue.output_path(item, 'anime').parent == original.resolve().parent
                print('PASS: long original path, duplicate basenames and folder preserved by native OLE drop.', flush=True)
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()
    window = webview.create_window('Native drop integration test', html='<div id="dropzone"></div>', hidden=True)
    def loaded():
        try:
            attach(window, Queue())
            import clr
            clr.AddReference(str(library))
            from System import Action, Array, String
            from EasySubs.Tests import NativeDropSmoke
            window.native.Invoke(Action(lambda: NativeDropSmoke.Test(window.native.webview, Array[String](paths))))
            if not finished.wait(10):
                raise RuntimeError('Drop never reached the queue')
        except Exception as exc:
            errors.append(exc)
        finally:
            window.destroy()
    window.events.loaded += loaded
    webview.start(gui='edgechromium', private_mode=True)
    actual_queue.shutdown()
    if errors:
        raise errors[0]


if __name__ == '__main__':
    main()
