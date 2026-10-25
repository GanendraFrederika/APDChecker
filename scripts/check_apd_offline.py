"""Run only on the host; cannot connect to Luckfox or Arduino."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from apd_runtime.offline import main
if __name__ == '__main__':
    raise SystemExit(main())
