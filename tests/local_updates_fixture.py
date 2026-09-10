"""Real localhost update UI against isolated SQLite fixtures; no external downloads."""

import signal
import sys
import tempfile
from contextlib import suppress
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_local_runtime import CHANNEL, Transport, fixture_release  # noqa: E402

from scripts.local_runtime import open_runtime  # noqa: E402
from scripts.server import face_handler  # noqa: E402


class Releases(Transport):
    def __init__(self, root):
        super().__init__()
        self.channels = []
        for version in ("2026-09-10", "2026-09-11"):
            fixture_release(root / version, self, version, "Lege fixture " + version)
            self.channels.append(self.payloads[CHANNEL])

    def small(self, url):
        if url == CHANNEL and len(self.channels) > 1:
            return self.channels.pop(0)
        return super().small(url)


def stop(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop)
    with tempfile.TemporaryDirectory(prefix="legislativ-ui-fixture-") as directory:
        root = Path(directory)
        with (
            open_runtime(root / "home", CHANNEL, transport=Releases(root)) as runtime,
            ThreadingHTTPServer(
                ("127.0.0.1", 0), face_handler(runtime.manager.current_state, runtime=runtime)
            ) as server,
        ):
            server.daemon_threads = False
            print(f"http://127.0.0.1:{server.server_port}", flush=True)
            with suppress(KeyboardInterrupt):
                server.serve_forever()
