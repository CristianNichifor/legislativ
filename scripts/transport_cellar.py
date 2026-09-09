"""Bounded official-host transport for user-triggered Cellar acquisition."""

import time
import urllib.request
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

HOSTS = {"publications.europa.eu", "op.europa.eu", "eur-lex.europa.eu"}
MAX_TOTAL = 16 * 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024
MAX_REQUESTS = 20
MAX_SECONDS = 90


def url_oficial(url):
    if not isinstance(url, str) or len(url) > 4000 or "\\" in url or any(ord(c) < 33 for c in url):
        raise ValueError("Adresa Cellar invalida.")
    p = urlsplit(url)
    if (
        p.scheme not in {"https", "http"}
        or p.hostname not in HOSTS
        or p.username
        or p.password
        or p.port not in (None, 443 if p.scheme == "https" else 80)
    ):
        raise ValueError("Sunt permise numai surse UE oficiale.")
    return urlunsplit(("https", p.hostname, p.path, p.query, ""))


class TransportCellar:
    def __init__(self):
        self.remaining = MAX_TOTAL
        self.requests = 0
        self.deadline = time.monotonic() + MAX_SECONDS
        transport = self

        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                transport.check_request()
                return super().redirect_request(req, fp, code, msg, headers, url_oficial(newurl))

        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirect())

    def check_time(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise ValueError("Preluarea Cellar a depasit timpul permis.")
        return left

    def check_request(self):
        self.check_time()
        self.requests += 1
        if self.requests > MAX_REQUESTS:
            raise ValueError("Prea multe cereri Cellar.")

    @contextmanager
    def __call__(self, request, *, timeout=15):
        self.check_request()
        url = url_oficial(request.full_url)
        req = urllib.request.Request(
            url,
            data=request.data,
            headers=dict(request.header_items()),
            method=request.get_method(),
        )
        with self.opener.open(req, timeout=min(timeout, 15, self.check_time())) as response:
            url_oficial(response.geturl())
            if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise ValueError("Codificare Cellar neacceptata.")
            limit = min(self.remaining, 2 * 1024 * 1024 if request.data else MAX_RESPONSE)

            def read():
                data = bytearray()
                while True:
                    self.check_time()
                    chunk = response.read(min(65536, limit - len(data) + 1))
                    self.check_time()
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ValueError("Sursa Cellar depaseste limita de descarcare.")
                self.remaining -= len(data)
                return bytes(data)

            yield SimpleNamespace(headers=response.headers, read=read)
