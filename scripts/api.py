"""The official way in: legislatie.just.ro's own SOAP web service.

The Ministry of Justice publishes a free web service — documented at
`legislatie.just.ro/ServiciulWebLegislatie.htm`, endpoint `/apiws/FreeWebService.svc/SOAP` —
and it is strictly better than reading the HTML pages. It needs no registration, it returns
structured records with the full text inline, and it carries `DataVigoare`, the in-force date
the HTML search refuses to filter by. Using it is also the courteous thing: it is the channel
the publisher built to be read by machines, so this package stops pretending to be a browser.

**Written against the standard library, like everything else here.** The reference client the
government shipped in 2015 (`govro/legislatie-just-python-soap-client`, MIT) uses `suds`, and the
newer `ro-eli-mcp` wraps the same endpoint for an MCP host — both confirmed the request shape
below, and neither is a dependency this package will take. The service speaks one fixed SOAP
dialect; two envelopes filled by string formatting are less to reason about than a SOAP stack,
and they keep the runtime footprint at zero. Both references were read for the contract, not
vendored.

**What was learned by calling it, not by reading about it:**

- The endpoint is `.svc/SOAP`, a named binding. Posting to `.svc` or `?wsdl` returns 404, which
  is how an afternoon disappears; the address is in the WSDL's `soap:address`, nowhere else.
- The token comes from `GetToken` and is passed to every `Search`. It dies after roughly **114
  searches**, and — this is the part that cost two collection runs — it does *not* announce that
  with a fault. It announces it with **`HTTP 500`**, which urllib raises before there is a body
  to parse, so a client watching for an auth fault never sees it and a caller that treats 500 as
  a transient server error retries a discarded token forever at zero throughput. Measured: 114
  searches at ~0.5s, then 500 on every subsequent call, then 0.6s again on a fresh token. So the
  client counts its own requests and rotates the token before the limit, and still treats a 500
  as "refresh once and retry" for the case where the count is wrong.
- `Search` takes a page number, a page size, and optional year / number / title / free-text. It
  has **no act-type filter**: a search for number 98 returns the DECRET, the HG, the DECIZIE and
  the ORDIN that also bear 98. Type scoping is the caller's job, done against `TipAct` on the way
  out — which `colector.py` does, because the linter wants six normative types out of 172.
- Results come **ten to a page**, and that is not configurable upward in practice. A year of
  legislation is hundreds of pages, so the collector paginates and the client just serves a page.

This module fetches and shapes. It does not decide what to keep, how fast to ask, or when to
stop — those are the collector's, because they are policy about someone else's server and belong
where they can be seen.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date

from scripts.text import normalizeaza

ENDPOINT = "https://legislatie.just.ro/apiws/FreeWebService.svc/SOAP"
NS_TEMPURI = "http://tempuri.org/"
NS_DATA = "http://schemas.datacontract.org/2004/07/FreeWebService"
USER_AGENT = (
    "legislativ-linter/0.1 (+https://github.com/CristianNichifor/legislativ; "
    "contact: cristian@cnwebify.com)"
)

_TOKEN_ENV = (
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
    '<s:Body><GetToken xmlns="http://tempuri.org/"/></s:Body></s:Envelope>'
)

# `i:nil="true"` is how the service is told a field is absent; an empty element is a different
# query (title equals empty string) and matches nothing. Every optional field defaults to nil.
_SEARCH_ENV = (
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
    '<s:Body><Search xmlns="http://tempuri.org/">'
    '<SearchModel xmlns:d="{ns_data}" '
    'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
    "<d:NumarPagina>{pagina}</d:NumarPagina>"
    "<d:RezultatePagina>{pe_pagina}</d:RezultatePagina>"
    "{an}{numar}{text}{titlu}"
    "</SearchModel><tokenKey>{token}</tokenKey></Search></s:Body></s:Envelope>"
)


class ApiError(RuntimeError):
    """The service answered, but not with a result — a fault, or an expired token."""


class TokenExpired(ApiError):
    """The token is stale. The caller may retry once after refreshing it."""


class RaspunsLent(ApiError):
    """The service accepted the connection and then withheld the body past the deadline.

    Distinct from a socket timeout on purpose. Under sustained collection this service does not
    stop answering — it dribbles the body out a byte at a time, so every individual `recv`
    succeeds and a per-operation timeout never fires. Only a deadline over the whole read
    notices, and only a caller that then *closes* the response gets its socket back.
    """


@dataclass(frozen=True)
class Inregistrare:
    """One act as the API returns it. `text` is the full body, inline.

    `link_html` is the portal URL, kept for two reasons: it is the human-checkable citation a
    finding must carry, and it is the only bridge to the richer `S_*` HTML when a provision needs
    parsing to the article level, which this flat text does not support.
    """

    titlu: str
    tip_act: str
    numar: str
    an: int | None
    data_vigoare: date | None
    emitent: str
    publicatie: str
    link_html: str
    text: str

    @property
    def id_portal(self) -> str:
        m = re.search(r"/(\d+)\s*$", self.link_html)
        return m.group(1) if m else ""


def _element(nume: str, valoare: object | None) -> str:
    if valoare is None or valoare == "":
        return f'<d:{nume} i:nil="true"/>'
    return f"<d:{nume}>{valoare}</d:{nume}>"


def _citeste(raspuns, termen_corp: float | None) -> bytes:
    """The whole body, under a wall-clock deadline that a trickle cannot reset.

    `read()` would block until the body is complete, which is precisely what a trickling server
    never lets happen; `read1()` returns whatever has arrived, so the deadline is re-checked on
    every chunk. When it lapses the response is closed here rather than left to a garbage
    collector that may never run — an unclosed response is an fd in CLOSE-WAIT, and enough of
    those is a collector that has stopped collecting while still looking alive.
    """
    if termen_corp is None:
        return raspuns.read()
    limita = time.monotonic() + termen_corp
    bucati: list[bytes] = []
    citeste = getattr(raspuns, "read1", None) or raspuns.read
    while True:
        if time.monotonic() > limita:
            raspuns.close()
            primite = sum(len(b) for b in bucati)
            raise RaspunsLent(
                f"corpul răspunsului nu s-a încheiat în {termen_corp:.0f}s ({primite} octeți)"
            )
        bucata = citeste(65536)
        if not bucata:
            return b"".join(bucati)
        bucati.append(bucata)


def _post(
    action: str,
    envelope: str,
    *,
    timeout: float,
    opener=urllib.request.urlopen,
    termen_corp: float | None = None,
) -> str:
    cerere = urllib.request.Request(
        ENDPOINT,
        data=envelope.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{NS_TEMPURI}IFreeWebService/{action}"',
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
        },
        method="POST",
    )
    with opener(cerere, timeout=timeout) as raspuns:
        brut = _citeste(raspuns, termen_corp)
        if raspuns.headers.get("Content-Encoding") == "gzip":
            import gzip

            brut = gzip.decompress(brut)
    text = brut.decode("utf-8", errors="replace")
    if "<s:Fault" in text or "<Fault" in text:
        mesaj = re.search(r"<(?:faultstring|Reason)[^>]*>(.*?)</", text, re.S)
        detaliu = mesaj.group(1).strip() if mesaj else "fault fără mesaj"
        if re.search(r"token", detaliu, re.I):
            raise TokenExpired(detaliu)
        raise ApiError(detaliu)
    return text


def get_token(
    *, timeout: float = 30.0, opener=urllib.request.urlopen, termen_corp: float | None = None
) -> str:
    text = _post("GetToken", _TOKEN_ENV, timeout=timeout, opener=opener, termen_corp=termen_corp)
    m = re.search(r"<GetTokenResult>([^<]+)</GetTokenResult>", text)
    if not m:
        raise ApiError("GetToken nu a întors un token")
    return m.group(1).strip()


def _camp(rec: str, nume: str) -> str:
    m = re.search(rf"<[ab]:{nume}>(.*?)</[ab]:{nume}>", rec, re.S)
    if not m:
        return ""
    import html

    return html.unescape(m.group(1)).strip()


def _data(brut: str) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", brut)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _inregistrare(rec: str) -> Inregistrare:
    an = _camp(rec, "An")
    return Inregistrare(
        titlu=normalizeaza(_camp(rec, "Titlu")),
        tip_act=normalizeaza(_camp(rec, "TipAct")),
        numar=_camp(rec, "Numar").strip(),
        an=int(an) if an.isdigit() else None,
        data_vigoare=_data(_camp(rec, "DataVigoare")),
        emitent=normalizeaza(_camp(rec, "Emitent")),
        publicatie=normalizeaza(_camp(rec, "Publicatie")),
        link_html=_camp(rec, "LinkHtml").strip(),
        text=normalizeaza(_camp(rec, "Text")),
    )


def search(
    token: str,
    *,
    pagina: int = 1,
    pe_pagina: int = 10,
    an: int | None = None,
    numar: int | str | None = None,
    titlu: str | None = None,
    text: str | None = None,
    timeout: float = 60.0,
    opener=urllib.request.urlopen,
    termen_corp: float | None = None,
) -> list[Inregistrare]:
    """One page of results. Empty list means the page is past the end, which is how paging stops.

    The optional filters are ANDed by the service. There is no type filter here on purpose —
    the service has none, and pretending otherwise in the signature would be a lie about what
    the query can do.
    """
    envelope = _SEARCH_ENV.format(
        ns_data=NS_DATA,
        pagina=pagina,
        pe_pagina=pe_pagina,
        an=_element("SearchAn", an),
        numar=_element("SearchNumar", numar),
        text=_element("SearchText", text),
        titlu=_element("SearchTitlu", titlu),
        token=token,
    )
    raspuns = _post("Search", envelope, timeout=timeout, opener=opener, termen_corp=termen_corp)
    return [_inregistrare(r) for r in re.findall(r"<[ab]:Legi>(.*?)</[ab]:Legi>", raspuns, re.S)]


@dataclass
class Client:
    """A token that refreshes itself once when the service says it is stale.

    Stateful on purpose, and the one stateful thing in this package: a token is a fact about a
    conversation with a server, not about a law, so it does not belong in the pure layers. The
    refresh-once rule keeps a genuinely broken service (faulting on every call) from becoming an
    infinite loop.
    """

    timeout: float = 60.0
    opener: object = field(default=urllib.request.urlopen)
    termen_corp: float | None = None
    cereri_per_token: int = 100
    _token: str | None = None
    _cereri: int = 0

    def token(self) -> str:
        if self._token is None or self._cereri >= self.cereri_per_token:
            self._token = get_token(
                timeout=self.timeout, opener=self.opener, termen_corp=self.termen_corp
            )
            self._cereri = 0
        return self._token

    def _cere(self, **kwargs) -> list[Inregistrare]:
        tok = self.token()
        self._cereri += 1
        return search(tok, timeout=self.timeout, opener=self.opener, **kwargs)

    def search(self, **kwargs) -> list[Inregistrare]:
        kwargs.setdefault("termen_corp", self.termen_corp)
        try:
            return self._cere(**kwargs)
        except TokenExpired:
            self._token = None
            return self._cere(**kwargs)
        except urllib.error.HTTPError as e:
            # A dead token is reported as `HTTP 500`, not as a fault. Measured against the live
            # service: 114 searches at ~0.5s, then 500 on every call with that token, and 0.6s
            # on a fresh one. urllib raises before there is a body, so `TokenExpired` — which is
            # parsed out of a fault — never sees it. Retrying the 500 without refreshing is an
            # infinite loop against a token the service has already discarded, and it is what
            # made two collection runs sit at zero while still looking alive.
            if e.code != 500:
                raise
            self._token = None
            return self._cere(**kwargs)
