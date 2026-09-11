"""Stable cross-agent entrypoint for FINAL-001."""
import sys

from quick_delivery import main

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


if __name__ == "__main__":
    raise SystemExit(main())
