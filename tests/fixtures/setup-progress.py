import json
import os
from pathlib import Path
import sys
import time

if '--wait-for-start' in sys.argv and input() != 'GO':
    sys.exit(1)
if os.environ.get('SETUP_EXPECTED_PROFILE') != sys.argv[1]:
    sys.exit(9)
def report(**event):
    print('SETUP ' + json.dumps(event), flush=True)
report(stage='Downloading media tools', detail='Test progress', progress=.5)
time.sleep(.4)
report(stage='Installing application components', detail='1 of 4 packages installed (25%)\nInstalling numpy - 0m 01s elapsed', progress=.25)
time.sleep(.4)
if os.environ.get('SETUP_TEST_FAIL') == '1':
    report(stage='Device check failed', detail='Choose a compatible driver or CPU.', progress=None, error='Choose a compatible driver or CPU.')
    sys.exit(1)
ready = Path(__file__).resolve().parent.parent / '.runtime/ready.json'
ready.parent.mkdir(exist_ok=True)
ready.write_text('{}')
report(stage='Complete', detail='Finished', progress=1)
