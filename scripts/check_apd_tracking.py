"""Offline workshop detection replay; does not connect to Luckfox/MCU."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from apd_runtime.tracking_offline import main
if __name__ == '__main__':
    raise SystemExit(main())
