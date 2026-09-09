"""Inherited by smoke-test subprocesses; record and reject external networking."""

import os
import sys


def guard(event, args):
    if event == "socket.connect":
        address = args[1]
        allowed = isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
    elif event == "socket.getaddrinfo":
        allowed = args[0] in {"127.0.0.1", "::1", "localhost"}
    else:
        return
    if not allowed:
        with open(os.environ["LAUNCH_NETWORK_LOG"], "a") as log:
            log.write(event + "\n")
        raise RuntimeError("External network access during cold start")


sys.addaudithook(guard)
