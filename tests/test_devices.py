from types import SimpleNamespace as NS
import sys

import pytest

from app.devices import discover, select_device, smoke_test
from app.backends import WhisperBackend


def fake_torch(cuda=False, hip=None, xpu=False):
    def api(available, name):
        return NS(is_available=lambda: available, get_device_name=lambda i: name,
                  get_device_properties=lambda i: NS(total_memory=8*1024**3))
    return NS(version=NS(hip=hip), cuda=api(cuda, 'test GPU'), xpu=api(xpu, 'Intel test GPU'))


@pytest.mark.parametrize('cuda,hip,xpu,expected,torch_device', [
    (True, None, False, 'cuda', 'cuda'),
    (True, '7.2', False, 'rocm', 'cuda'),
    (False, None, True, 'xpu', 'xpu'),
    (False, None, False, 'cpu', 'cpu'),
])
def test_auto_detects_runtime_not_cuda_api_name(cuda, hip, xpu, expected, torch_device):
    result = select_device('auto', discover(fake_torch(cuda, hip, xpu)))
    assert result['id'] == expected
    assert result['torch_device'] == torch_device


def test_explicit_selection_never_silently_uses_different_runtime():
    devices = discover(fake_torch(True, '7.2'))
    with pytest.raises(RuntimeError, match='CUDA is unavailable'):
        select_device('cuda', devices)
    assert select_device('cpu', devices)['id'] == 'cpu'
    with pytest.raises(RuntimeError, match='XPU is unavailable'):
        select_device('xpu', devices)
    with pytest.raises(ValueError):
        select_device('directml', devices)


def test_broken_or_missing_xpu_does_not_break_cpu():
    torch = fake_torch()
    del torch.xpu
    assert select_device('auto', discover(torch))['id'] == 'cpu'
    torch.xpu = NS(is_available=lambda: (_ for _ in ()).throw(RuntimeError('driver failure')))
    devices = discover(torch)
    assert next(d for d in devices if d['id'] == 'xpu')['error'] == 'driver failure'
    assert select_device('auto', devices)['id'] == 'cpu'


def test_failed_compute_probe_is_actionable():
    with pytest.raises(RuntimeError, match='XPU could not run the GPU check'):
        smoke_test(NS(), {'id': 'xpu', 'label': 'XPU', 'torch_device': 'xpu'})
    smoke_test(NS(), {'id': 'cpu'})


def test_turbo_xpu_leaves_unused_sparse_alignment_buffer_on_cpu(monkeypatch):
    calls = []
    heads = object()
    class Model:
        def __init__(self): self._buffers = {'alignment_heads': heads}
        def eval(self): return self
        def to(self, device):
            assert 'alignment_heads' not in self._buffers
            calls.append(device)
            return self
        def register_buffer(self, name, value, persistent):
            assert not persistent
            self._buffers[name] = value
    def load(name, device):
        assert name == 'turbo' and device == 'cpu'
        return Model()
    monkeypatch.setitem(sys.modules, 'whisper', NS(load_model=load))
    backend = WhisperBackend('turbo', 'xpu')
    backend.load()
    assert calls == ['xpu']
    assert backend.model._buffers['alignment_heads'] is heads


@pytest.mark.parametrize('device', ['cuda', 'cpu'])
def test_turbo_existing_device_routes_unchanged(monkeypatch, device):
    calls = []
    def load(name, device):
        calls.append(device)
        return NS(eval=lambda: 'model')
    monkeypatch.setitem(sys.modules, 'whisper', NS(load_model=load))
    backend = WhisperBackend('turbo', device)
    backend.load()
    assert calls == [device]


@pytest.mark.parametrize('device,hip,attention,dtype', [
    ('xpu', None, 'eager', 'fp16'), ('cuda', '7.2', 'eager', 'fp16'),
    ('cuda', None, 'sdpa', 'fp16'), ('cpu', None, 'sdpa', 'fp32'),
])
def test_hf_device_precision_and_attention(monkeypatch, device, hip, attention, dtype):
    from anime_subs import load_hf_model
    calls = {}
    model = NS(generation_config=NS(lang_to_id={'<|ja|>': 1}), config=NS(num_mel_bins=80))
    model.to = lambda target: calls.update(device=target) or model
    model.eval = lambda: model
    def load(name, **kwargs):
        calls.update(kwargs)
        return model
    processor = NS(tokenizer=NS(convert_tokens_to_ids=lambda text: 1),
                   feature_extractor=NS(feature_size=80))
    torch = fake_torch(hip=hip)
    torch.float16 = 'fp16'; torch.float32 = 'fp32'
    torch.cuda.OutOfMemoryError = MemoryError
    monkeypatch.setitem(sys.modules, 'torch', torch)
    monkeypatch.setitem(sys.modules, 'transformers', NS(
        AutoModelForSpeechSeq2Seq=NS(from_pretrained=load),
        AutoProcessor=NS(from_pretrained=lambda *a, **kw: processor)))
    load_hf_model('test-model', device)
    assert calls['attn_implementation'] == attention
    assert calls['dtype'] == dtype
    assert calls['device'] == device


def test_api_accepts_xpu_and_rocm(tmp_path):
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.jobs import Queue
    queue = Queue(tmp_path/'state')
    with TestClient(create_app(queue, 'secret'), base_url='http://127.0.0.1') as client:
        for device in ('xpu', 'rocm', 'cpu'):
            response = client.post('/api/settings', json={'device': device}, headers={'X-App-Token': 'secret'})
            assert response.status_code == 200
            assert queue.settings['device'] == device
