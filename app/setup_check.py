"""Device verification used before activating a newly installed runtime."""
import json
import sys


def main():
    try:
        import torch
        from app.devices import discover, select_device, smoke_test
        selected = select_device(sys.argv[1], discover(torch))
        smoke_test(torch, selected)
        print('Processing device check passed: ' + selected['name'], flush=True)
        return 0
    except Exception as exc:
        print(str(exc), flush=True)
        message = ('The selected GPU could not run. Check that your card and driver support this runtime, '
                   'then retry; or choose CPU. Intel XPU and AMD ROCm require supported GPUs, not just the matching brand.')
        print('SETUP ' + json.dumps(dict(stage='Device check failed', detail=message, progress=None, error=message)), flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
