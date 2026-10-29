"""Run the mxl2jianpu CLI without setting PYTHONPATH.

    python mxl2jianpu/run.py tools
    python mxl2jianpu/run.py pages score.pdf -o look --dpi 200

Same commands as `python -m mxl2jp.cli`, but usable from any directory and on
any platform without configuring the import path first.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mxl2jp.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
