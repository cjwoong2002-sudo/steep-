#!/usr/bin/env python3
"""진입점.  사용법: python run.py --regions us"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from roic_screener.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
