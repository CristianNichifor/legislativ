"""Build and serve an isolated static app from tracked public fixtures, never local corpora."""

import functools
import shutil
import signal
import subprocess
from contextlib import suppress
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]


class StaticHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith("/nested/"):
            path = path.removeprefix("/nested")
        return super().translate_path(path)


def stop(_signal, _frame):
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, stop)
with TemporaryDirectory(prefix="legislativ-static-browser-") as directory:
    root = Path(directory)
    tracked = (
        subprocess.check_output(["git", "-c", f"safe.directory={ROOT}", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    for name in filter(None, tracked):
        source = ROOT / name
        if source.is_file():
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    (root / "node_modules").symlink_to(ROOT / "node_modules", target_is_directory=True)
    for command in [
        ["python3", "-m", "scripts.construieste_web", "--sursa", "fixturi"],
        [
            "python3",
            "-m",
            "scripts.export_cautare",
            "--db",
            "web/data/corpus.db",
            "--tinta",
            "acte.jsonl",
        ],
        ["node", "infra/pagefind.mjs", "acte.jsonl", "web/pagefind"],
    ]:
        subprocess.run(command, cwd=root, check=True)
    handler = functools.partial(StaticHandler, directory=root / "web")
    with ThreadingHTTPServer(("127.0.0.1", 5191), handler) as server, suppress(KeyboardInterrupt):
        server.serve_forever()
