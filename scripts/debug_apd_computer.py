"""Entry point for local-only, outputs-disabled PC debug."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from apd_runtime.computer_debug import main
if __name__ == '__main__':
    raise SystemExit(main())
