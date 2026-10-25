"""Read-only local CCTV dashboard; no camera/serial side effects on import.
Run --help. Serial defaults OFF; supervised PPE1/v2.2 opt-in only.
"""
from apd_runtime.live_camera import main

if __name__ == "__main__":
    raise SystemExit(main())
