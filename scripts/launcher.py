"""Offline standard-library launcher."""

import argparse
import ntpath
import os
import socket
import subprocess
import sys
from pathlib import Path, PurePosixPath


def default_data_home(platform=None, environ=None, home=None):
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    home = str(Path.home()) if home is None else str(home)
    if platform == "win32":
        base = environ.get("LOCALAPPDATA") or ntpath.join(home, "AppData", "Local")
        if not ntpath.isabs(base):
            base = ntpath.join(home, "AppData", "Local")
        return ntpath.join(base, "legislativ")
    if platform == "darwin":
        return str(PurePosixPath(home) / "Library" / "Application Support" / "legislativ")
    base = environ.get("XDG_DATA_HOME", "")
    if not PurePosixPath(base).is_absolute():
        base = str(PurePosixPath(home) / ".local" / "share")
    return str(PurePosixPath(base) / "legislativ")


def available_port(preferred):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-home", type=Path, default=Path(default_data_home()))
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--fara-browser", action="store_true")
    ap.add_argument("--data-channel", help="canalul HTTPS de actualizare configurat")
    args = ap.parse_args(argv)
    if sys.version_info < (3, 12):  # noqa: UP036 - downloaded runtime may use older Python
        ap.error("Python 3.12+ este necesar; Python nu este inclus.")
    if not 0 <= args.port <= 65535:
        ap.error("--port trebuie sa fie intre 0 si 65535")
    root = Path(__file__).resolve().parent.parent
    data_home = args.data_home.expanduser().resolve()
    if data_home == root or root in data_home.parents:
        ap.error("--data-home trebuie sa fie in afara directorului aplicatiei")
    data_home.mkdir(parents=True, exist_ok=True)
    (data_home / "private").mkdir(mode=0o700, exist_ok=True)
    port = available_port(args.port)
    command = [
        sys.executable,
        "-B",
        str(root / "scripts" / "_launch_server.py"),
        "--data-home",
        str(data_home),
        "--port",
        str(port),
    ]
    if args.fara_browser:
        command.append("--fara-browser")
    if args.data_channel:
        command.extend(["--data-channel", args.data_channel])
    print(f"Date locale: {data_home}\nPornesc pe http://127.0.0.1:{port}", flush=True)
    try:
        return subprocess.call(command, cwd=data_home)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
