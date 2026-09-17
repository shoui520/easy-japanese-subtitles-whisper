"""Compute runtime selection, independent of transcription model and GPU vendor names."""
DEVICE_CHOICES = {"auto", "cpu", "cuda", "xpu", "rocm"}
LABELS = {"cpu": "CPU", "cuda": "CUDA", "xpu": "XPU", "rocm": "ROCm / HIP"}


def discover(torch):
    devices = []
    hip = bool(getattr(torch.version, "hip", None))
    for kind, api in (("rocm" if hip else "cuda", torch.cuda),
                      ("xpu", getattr(torch, "xpu", None))):
        entry = {"id": kind, "label": LABELS[kind], "available": False,
                 "torch_device": "cuda" if kind == "rocm" else kind}
        try:
            if api is not None and api.is_available():
                props = api.get_device_properties(0)
                entry.update(available=True, name=api.get_device_name(0),
                             vram_gb=round(props.total_memory / 1024**3, 1))
        except Exception as exc:
            entry["error"] = str(exc)
        devices.append(entry)
    devices.append(dict(id="cpu", label="CPU", available=True, torch_device="cpu", name="CPU"))
    return devices


def select_device(requested, devices):
    if requested not in DEVICE_CHOICES:
        raise ValueError("Choose Automatic, CUDA, XPU, ROCm / HIP, or CPU.")
    if requested == "auto":
        return next(d for d in devices if d["available"])
    selected = next((d for d in devices if d["id"] == requested and d["available"]), None)
    if selected is None:
        raise RuntimeError(f"{LABELS[requested]} is unavailable in the selected Python environment. "
                           "Check that your GPU is supported, its driver is installed, and the matching "
                           "PyTorch build is selected in Setup; or choose CPU.")
    return selected


def smoke_test(torch, selection):
    """Fail before extracting an episode if even basic FP16 compute cannot run."""
    if selection["id"] == "cpu":
        return
    try:
        with torch.inference_mode():
            sample = torch.ones((8, 8), device=selection["torch_device"], dtype=torch.float16)
            value = (sample @ sample).float().sum().item()
            if value != 512:
                raise RuntimeError("Unexpected GPU calculation result")
    except Exception as exc:
        raise RuntimeError(f"{selection['label']} could not run the GPU check. Check your card's "
                           "supported driver/runtime combination or select CPU. Details: " + str(exc)) from exc
