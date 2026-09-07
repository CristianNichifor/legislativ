"""A ceiling on requests per second, shared by every worker.

Concurrency and politeness are separate dials and this is the second one. Three connections that
each wait their turn against one clock is three times the throughput at the same load on the
server; three connections that each sleep between their own requests is three times the load. That
distinction is the whole reason this is a shared object rather than a `time.sleep` inside each
worker, and it is what makes it defensible to point more than one connection at a public body's
website.

Measured against cdep.ro, a Fișa takes 1.3 to 10.9 seconds to come back and 0.006 seconds to
parse: the job is almost entirely waiting, which is exactly the shape concurrency helps and better
code does not.

Lives on its own because both collectors need it and neither owns it — the corpus fetch reads
legislatie.just.ro, the passage fetch reads cdep.ro, and a dependency from one to the other only to
borrow a clock would say something untrue about how they relate.
"""

from __future__ import annotations

import threading
import time


class Ritm:
    """`pe_secunda` requests per second across every caller. Zero or less means no ceiling."""

    def __init__(self, pe_secunda: float) -> None:
        self._interval = 1.0 / pe_secunda if pe_secunda > 0 else 0.0
        self._lacat = threading.Lock()
        self._urmatorul = 0.0

    def asteapta(self) -> None:
        if not self._interval:
            return
        with self._lacat:
            acum = time.monotonic()
            if self._urmatorul > acum:
                time.sleep(self._urmatorul - acum)
                acum = time.monotonic()
            self._urmatorul = acum + self._interval
