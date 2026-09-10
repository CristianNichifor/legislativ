"""Run the real public-generation browser checks against isolated, ephemeral fixtures."""

import functools
import os
import shutil
import signal
import subprocess
import sys
import threading
from contextlib import ExitStack
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]


def stop(_signal, _frame):
    raise KeyboardInterrupt


def copy_tracked(root):
    tracked = (
        subprocess.check_output(["git", "-c", f"safe.directory={ROOT}", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    for name in filter(None, tracked):
        source = ROOT / name
        # Rebuild web/ entirely; never seed from checkout data or generated/private files.
        if name.startswith("web/") or source.is_symlink() or not source.is_file():
            continue
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (root / "node_modules").symlink_to(ROOT / "node_modules", target_is_directory=True)


def serve(server, cleanup):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cleanup.callback(thread.join, 5)
    cleanup.callback(server.shutdown)


def main():
    signal.signal(signal.SIGTERM, stop)
    with (
        TemporaryDirectory(prefix="legislativ-generation-browser-") as directory,
        ExitStack() as cleanup,
    ):
        root = Path(directory)
        copy_tracked(root)
        sys.path.insert(0, str(root))
        from tests import browser_generation_fixture as fixture

        source = cleanup.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), fixture.Handler))
        fixture.PORT = source.server_port
        handler = functools.partial(SimpleHTTPRequestHandler, directory=root / "web")
        app = cleanup.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), handler))
        environment = os.environ | {
            "BROWSER_SOURCE_PORT": str(source.server_port),
            "BROWSER_BASE_URL": f"http://127.0.0.1:{app.server_port}",
        }
        subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.construieste_web",
                "--sursa",
                "fixturi",
                "--canal-browser",
                f"http://127.0.0.1:{source.server_port}/channel.json",
                "--permite-http-local-browser",
            ],
            cwd=root,
            env=environment,
            check=True,
            timeout=120,
        )
        source.payloads = fixture.fixtures()
        source.mode = "unpublished"
        serve(source, cleanup)
        serve(app, cleanup)
        print(
            f"Generation fixture: app={environment['BROWSER_BASE_URL']}, "
            f"source={source.server_port}",
            flush=True,
        )
        subprocess.run(
            ["node", "tests/browser_generation.cjs"],
            cwd=root,
            env=environment,
            check=True,
            timeout=240,
        )


if __name__ == "__main__":
    main()
