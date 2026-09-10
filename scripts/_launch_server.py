"""Run the server with an explicit import root and separate writable cwd."""

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
runpy.run_module("scripts.server", run_name="__main__")
