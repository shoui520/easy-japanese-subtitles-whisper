from __future__ import annotations

import argparse
import json
import secrets
import socket
import threading
import time

from app.api import create_app
from app.jobs import Queue
from app.media import VIDEO_FILE_FILTER
from app.runtime import DATA


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Serve UI without the desktop shell")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", default=str(DATA))
    parser.add_argument("--output-dir", help="Override output for read-only source verification")
    parser.add_argument("--protect-root", action="append", default=[], help="Refuse publishing any output under this directory")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    queue = Queue(args.data_dir, args.output_dir, args.protect_root)
    change_runtime = False
    token = secrets.token_urlsafe(32)
    import uvicorn
    sock = socket.socket()
    sock.bind(("127.0.0.1", args.port))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(queue, token), log_level="warning", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/#{token}"
    print(f"Easy Japanese Subtitles: {url}" if args.headless else "Starting Easy Japanese Subtitles", flush=True)
    if args.paths:
        threading.Thread(target=queue.add, args=(args.paths,), daemon=True).start()
    try:
        if args.headless:
            while thread.is_alive():
                time.sleep(.25)
        else:
            import webview

            class Bridge:
                def change_runtime(self):
                    nonlocal change_runtime
                    import os
                    if os.environ.get('EASY_SUBS_LAUNCHER') != '1':
                        raise ValueError('Open Easy Japanese Subtitles.exe to install or change the runtime.')
                    with queue.lock:
                        if queue.running:
                            raise ValueError('Finish or cancel the current queue before changing the runtime.')
                        change_runtime = True
                    window.destroy()

                def open_output_folder(self, item_id):
                    import os
                    from pathlib import Path
                    with queue.lock:
                        item = queue.find(item_id)
                        if item["status"] not in {"complete", "skipped"} or not item.get("output"):
                            raise ValueError("This file has no saved subtitles yet.")
                        folder = Path(item["output"]).parent
                    os.startfile(str(folder))

                def pick_files(self):
                    paths = window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=(VIDEO_FILE_FILTER,))
                    return queue.add(list(paths)) if paths else []

                def pick_folder(self):
                    paths = window.create_file_dialog(webview.FileDialog.FOLDER)
                    return queue.add(list(paths)) if paths else []

            window = webview.create_window("Easy Japanese Subtitles", url, js_api=Bridge(), width=1150, height=840, min_size=(820, 600))

            def loaded():
                from app.file_drop import attach
                try:
                    attach(window, queue)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    window.evaluate_js('showError("Drag and drop could not start. Use Add files or Add folder.")')

            window.events.loaded += loaded
            webview.start(gui="edgechromium", private_mode=True)
    finally:
        queue.shutdown()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
    if change_runtime:
        raise SystemExit(42)


if __name__ == "__main__":
    main()
