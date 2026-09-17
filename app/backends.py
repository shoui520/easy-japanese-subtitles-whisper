"""Adapters reuse the original prototype's decoding and tokenizer validation."""
from anime_subs import HF_MODEL_IDS, load_hf_model, transcribe, transcribe_turbo

MODELS = {
    "anime": {"name": "Japanese Anime", "description": "efwkjn/whisper-ja-anime-v0.3"},
    "turbo": {"name": "Whisper Turbo", "description": "Official OpenAI Whisper"},
    "large": {"name": "Japanese Large", "description": "efwkjn/whisper-ja-1.5B · more memory required"},
}


class WhisperBackend:
    def __init__(self, name, device):
        self.name, self.device = name, device
        self.model = self.processor = None

    def load(self):
        if self.name == "turbo":
            import whisper
            import urllib.request
            original = urllib.request.urlopen
            def with_timeout(*args, **kwargs):
                kwargs.setdefault("timeout", 30)
                return original(*args, **kwargs)
            urllib.request.urlopen = with_timeout
            try:
                if self.device.startswith("xpu"):
                    # Whisper's sparse alignment-head buffer is only used for word
                    # alignment (disabled here). Keep it on CPU: XPU sparse support
                    # must not be required for ordinary segment timestamps.
                    self.model = whisper.load_model("turbo", device="cpu").eval()
                    heads = self.model._buffers.pop("alignment_heads")
                    try:
                        self.model.to(self.device)
                    finally:
                        self.model.register_buffer("alignment_heads", heads, persistent=False)
                else:
                    self.model = whisper.load_model("turbo", device=self.device).eval()
            finally:
                urllib.request.urlopen = original
        else:
            self.model, self.processor = load_hf_model(HF_MODEL_IDS[self.name], self.device)

    def transcribe(self, audio, progress):
        if self.name == "turbo":
            # Official Whisper reports frames through tqdm, not a callback.
            # Adapt it inside this single-job worker without changing decoding.
            import importlib
            module = importlib.import_module("whisper.transcribe")
            original = module.tqdm.tqdm

            class ProgressBar(original):
                def update(self, amount=1):
                    result = super().update(amount)
                    if self.total:
                        progress(min(1, self.n / self.total))
                    return result

            module.tqdm.tqdm = ProgressBar
            try:
                return transcribe_turbo(self.model, audio)
            finally:
                module.tqdm.tqdm = original
        return transcribe(self.model, self.processor, audio, progress)

    def unload(self):
        self.model = self.processor = None
        import gc
        gc.collect()
