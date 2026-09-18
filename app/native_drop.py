"""Windows-native paths; never accept browser-materialized temporary videos."""
import json
import threading

from app.runtime import ROOT


def attach(window, queue):
    import clr
    from System import Action, Array, String, Boolean
    if getattr(window, '_native_drop_installed', False):
        return
    window.native.Invoke(Action(lambda: setattr(window.native.webview, 'AllowExternalDrop', False)))
    library = ROOT / 'native/EasySubs.Native.dll'
    if not library.is_file():
        library = ROOT / 'build/native/EasySubs.Native.dll'
    clr.AddReference(str(library))
    from EasySubs import NativeDrop

    def error(message):
        threading.Thread(target=window.evaluate_js,
                         args=(f'showError({json.dumps(str(message))})',), daemon=True).start()

    def dropped(paths):
        paths = [str(path) for path in paths]
        def add():
            try:
                queue.add(paths)
            except Exception as exc:
                error(exc)
        threading.Thread(target=add, daemon=True).start()

    def hover(active):
        # ExecuteScriptAsync is nonblocking on the native UI thread.
        if not window.native.IsDisposed and window.native.webview.CoreWebView2 is not None:
            window.native.webview.CoreWebView2.ExecuteScriptAsync(
                "document.getElementById('dropzone')?.classList.toggle('dragging'," + str(active).lower() + ")")

    def install():
        control = window.native.webview
        control.AllowExternalDrop = False
        callbacks = (Action[Array[String]](dropped), Action[Boolean](hover), Action[String](error))
        NativeDrop.Attach(control, *callbacks)
        NativeDrop.Attach(window.native, *callbacks)
        window._native_drop_callbacks = callbacks
        window._native_drop_installed = True

    window.native.Invoke(Action(install))
