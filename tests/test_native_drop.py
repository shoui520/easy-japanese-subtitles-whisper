import os
import subprocess
import sys

import pytest

from app.runtime import ROOT


@pytest.mark.skipif(os.name != 'nt', reason='Windows WebView2 / OLE integration')
def test_native_drop_preserves_original_paths():
    result = subprocess.run([sys.executable, '-m', 'tests.verify_native_drop'], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS:' in result.stdout


def test_browser_drop_no_longer_supplies_queue_paths():
    assert 'pywebviewFullPath' not in (ROOT / 'app/main.py').read_text()
    assert 'DOMEventHandler' not in (ROOT / 'app/main.py').read_text()
