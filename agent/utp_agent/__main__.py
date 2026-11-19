"""入口：python -m utp_agent [--once]"""
from __future__ import annotations

import sys

from .loop import run

if __name__ == "__main__":
    run(once="--once" in sys.argv)
