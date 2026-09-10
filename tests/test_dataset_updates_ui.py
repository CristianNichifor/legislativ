import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not shutil.which("node") or not os.environ.get("PLAYWRIGHT_MODULE"),
    reason="Set PLAYWRIGHT_MODULE to an installed Playwright package",
)
def test_dataset_updates_browser():
    script = Path(__file__).with_name("dataset_updates_browser.cjs")
    subprocess.run(["node", str(script)], check=True, timeout=90)
