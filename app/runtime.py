from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("EASY_SUBS_DATA", str(ROOT / ".app-data"))).resolve()


def executable(name, override=""):
    found = override or shutil.which(name)
    if not found or not Path(found).is_file():
        raise RuntimeError(f"{name} was not found. Install FFmpeg with WinGet or select its executable in Setup.")
    return str(Path(found).resolve())


def python_candidates():
    paths = [os.environ.get("EASY_SUBS_PYTHON", ""), sys.executable]
    found = shutil.which("python")
    if found:
        paths.append(found)
    return list(dict.fromkeys(p for p in paths if p and Path(p).is_file()))


def check_python(path):
    # Runs in the chosen interpreter; the UI environment need not contain torch.
    code = '''import sys,json,importlib.util,importlib.metadata as m
r={"python":sys.executable,"version":sys.version.split()[0],"packages":{}}
for name,dist in [("torch","torch"),("transformers","transformers"),("whisper","openai-whisper"),("accelerate","accelerate")]:
 try:r["packages"][name]=m.version(dist)
 except m.PackageNotFoundError:r["packages"][name]=None
try:
 import torch
 r["cuda"]=torch.cuda.is_available()
 r["gpu"]=torch.cuda.get_device_name(0) if r["cuda"] else None
 r["vram_gb"]=round(torch.cuda.get_device_properties(0).total_memory/1024**3,1) if r["cuda"] else None
except Exception as e:r["cuda"]=False;r["error"]=str(e)
print(json.dumps(r))'''
    try:
        result = subprocess.run([path, "-c", code], capture_output=True, text=True,
                                timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        return {"python": path, "error": "This Python could not start or load its transcription packages.", "packages": {}}


def friendly_error(exc):
    message = str(exc)
    lowered = message.lower()
    if "out of memory" in lowered:
        return "This model needs more available memory. Close GPU-heavy apps, choose a smaller model, or use CPU."
    if "no module named" in lowered or "missing transformers" in lowered:
        return "The selected Python is missing transcription packages. Open Setup and select a prepared environment."
    if "permission" in lowered or "access is denied" in lowered:
        return "Windows denied file access. Choose a writable output folder and check file permissions."
    if "no such file or directory" in lowered or isinstance(exc, FileNotFoundError):
        return "A required file is no longer available. Check the source video and selected tool paths, then add it again."
    if any(x in lowered for x in ("connectionerror", "connection error", "connection refused", "connection reset", "timed out", "timeout", "http error", "httpsconnectionpool", "network is unreachable", "download interrupted")):
        return "The model download could not finish. Check your connection and retry; cached files are kept."
    if "cuda" in lowered:
        return "GPU processing could not start. Check your NVIDIA driver or select CPU in Setup."
    return message[:600] or "Processing failed. Open the log for details."


class ProcessTree:
    """Windows Job Object: closing the handle kills worker AND its FFmpeg children."""
    def __init__(self, process):
        self.process = process
        self.handle = None
        if os.name != "nt":
            return
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [("PerProcessUserTimeLimit", c.c_int64), ("PerJobUserTimeLimit", c.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", c.c_size_t),
                        ("MaximumWorkingSetSize", c.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", c.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(c.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO), ("ProcessMemoryLimit", c.c_size_t),
                        ("JobMemoryLimit", c.c_size_t), ("PeakProcessMemoryUsed", c.c_size_t), ("PeakJobMemoryUsed", c.c_size_t)]
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = self.kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not handle or not self.kernel.SetInformationJobObject(handle, 9, c.byref(limits), c.sizeof(limits)) or not self.kernel.AssignProcessToJobObject(handle, int(process._handle)):
            if handle:
                self.kernel.CloseHandle(handle)
            process.kill()
            raise RuntimeError("Windows could not establish safe process cleanup. Restart the app outside a restricted launcher.")
        self.handle = handle

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        elif self.process.poll() is None:
            self.process.kill()
