from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response

from app.backends import MODELS
from app.runtime import ROOT, check_python, python_candidates, executable


def create_app(queue, token):
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.middleware("http")
    async def security(request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"error": "Invalid host"}, 403)
        if request.url.path.startswith("/api/"):
            if not hmac.compare_digest(request.headers.get("x-app-token", ""), token):
                return JSONResponse({"error": "Unauthorized"}, 403)
            origin = request.headers.get("origin")
            if origin and origin != f"http://{request.headers.get('host')}":
                return JSONResponse({"error": "Invalid origin"}, 403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @api.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"error": str(exc)}, 400)

    @api.exception_handler(RuntimeError)
    async def runtime_error(request, exc):
        return JSONResponse({"error": str(exc)}, 400)

    @api.get("/")
    def index():
        # Token arrives via fragment/native shell; never embed it in publicly readable HTML.
        return HTMLResponse((ROOT / "app/ui/index.html").read_text(encoding="utf-8"))

    @api.get("/assets/{name}")
    def asset(name: str):
        if name not in {"app.js", "style.css"}:
            return Response(status_code=404)
        return Response((ROOT / "app/ui" / name).read_text(encoding="utf-8"), media_type="text/javascript" if name.endswith("js") else "text/css")

    @api.get("/api/state")
    def state():
        return queue.snapshot()

    @api.post("/api/add")
    def add(body: dict):
        paths = body.get("paths", [])
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ValueError("Choose files or folders first.")
        return {"added": queue.add(paths)}

    @api.post("/api/edit/{item_id}")
    def edit(item_id: str, body: dict):
        queue.edit(item_id, body)
        return {"ok": True}

    @api.post("/api/remove")
    def remove(body: dict):
        queue.remove(body.get("ids", []))
        return {"ok": True}

    @api.post("/api/start")
    def start():
        queue.start()
        return {"ok": True}

    @api.post("/api/cancel")
    def cancel(body: dict):
        queue.cancel(body.get("id"))
        return {"ok": True}

    @api.post("/api/settings")
    def settings(body: dict):
        with queue.lock:
            if queue.running:
                raise ValueError("Stop the queue before changing processing settings.")
            if body.get("model", queue.settings["model"]) not in MODELS:
                raise ValueError("Unknown transcription model.")
            if body.get("device", queue.settings["device"]) not in {"auto", "cuda", "xpu", "rocm", "cpu"}:
                raise ValueError("Choose Automatic, CUDA, XPU, ROCm / HIP, or CPU.")
            for key in queue.settings:
                if key in body:
                    queue.settings[key] = body[key]
            queue.persist()
        return {"ok": True}

    @api.post("/api/diagnostics")
    def diagnostics():
        def media_tool(name):
            try:
                return executable(name, queue.settings[name])
            except RuntimeError:
                return None
        candidates = [queue.settings["python"]]
        return {"runtimes": [check_python(p) for p in candidates],
                "ffmpeg": media_tool("ffmpeg"),
                "ffprobe": media_tool("ffprobe")}

    @api.get("/api/log/{item_id}")
    def log(item_id: str):
        with queue.lock:
            queue.find(item_id)
        path = queue.data / "logs" / f"{item_id}.log"
        return {"text": path.read_text(encoding="utf-8")[-30000:] if path.exists() else "No processing log yet."}

    return api
