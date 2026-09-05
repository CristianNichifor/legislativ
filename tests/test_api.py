"""Tests for the SOAP client, against recorded responses.

The client is the one part of this package that talks to a network, so its tests must not. Two
real responses from `FreeWebService.svc/SOAP` are saved under `fixtures/` and replayed through
the `opener` seam the client exposes for exactly this — the same seam a caller would use to put a
cache in front of the service. What is checked is the contract: a token is extracted, a record is
shaped, an expired-token fault triggers exactly one refresh, and a fault that is not about the
token is not retried into a loop.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from scripts.api import ApiError, Client, TokenExpired, get_token, search

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _Raspuns(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener_din(*fisiere: str):
    """An opener that returns each fixture in turn, then repeats the last — like a service that
    keeps answering. Records every SOAPAction it was asked for, so a test can assert the flow."""
    corpuri = [(FIXTURES / f).read_bytes() for f in fisiere]
    apeluri: list[str] = []

    def opener(cerere, timeout=60):
        apeluri.append(cerere.headers.get("Soapaction", ""))
        corp = corpuri[min(len(apeluri) - 1, len(corpuri) - 1)]
        return _Raspuns(corp)

    opener.apeluri = apeluri
    return opener


def _opener_fault(mesaj: str):
    corp = (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        f"<s:Fault><faultstring>{mesaj}</faultstring></s:Fault></s:Body></s:Envelope>"
    ).encode()
    apeluri: list[str] = []

    def opener(cerere, timeout=60):
        apeluri.append(cerere.headers.get("Soapaction", ""))
        return _Raspuns(corp)

    opener.apeluri = apeluri
    return opener


def test_a_token_is_extracted_from_the_envelope():
    token = get_token(opener=_opener_din("api_token.xml"))
    assert token.startswith("TESTTOKEN") and len(token) == 58


def test_a_record_is_shaped_with_its_in_force_date_and_portal_id():
    recs = search("t", opener=_opener_din("api_search.xml"))
    assert len(recs) == 1
    r = recs[0]
    assert r.tip_act == "DECRET" and r.numar == "98"
    assert r.data_vigoare is not None and r.data_vigoare.year == 2016
    assert r.id_portal == "175121"
    assert r.link_html.endswith("/175121")
    assert len(r.text) > 200


def test_the_full_text_arrives_inline_and_flattened():
    """The API's `Text` is plain text — no `S_ART`, no `S_LGI`. That is the fact that makes this a
    two-source design: the API is the spine, and article-level structure still comes from the
    `DetaliiDocument` HTML for acts that need it."""
    r = search("t", opener=_opener_din("api_search.xml"))[0]
    assert "S_ART" not in r.text and "S_LGI" not in r.text
    assert "<span" not in r.text and "<div" not in r.text


def test_optional_filters_are_sent_as_nil_not_empty():
    """An empty element means "title equals empty string" and matches nothing; the service wants
    `i:nil="true"`. A regression here returns zero results and looks like an empty corpus."""
    captat = {}

    def opener(cerere, timeout=60):
        captat["body"] = cerere.data.decode("utf-8")
        return _Raspuns((FIXTURES / "api_search.xml").read_bytes())

    search("t", an=2016, opener=opener)
    assert "<d:SearchAn>2016</d:SearchAn>" in captat["body"]
    assert '<d:SearchNumar i:nil="true"/>' in captat["body"]
    assert '<d:SearchTitlu i:nil="true"/>' in captat["body"]


def test_an_expired_token_is_refreshed_exactly_once():
    """The token has a validity window this client cannot see, so it refreshes on the fault. Once,
    not forever — a service faulting on every call must not become an infinite loop."""
    faults = 0

    def opener(cerere, timeout=60):
        nonlocal faults
        action = cerere.headers.get("Soapaction", "")
        if "GetToken" in action:
            return _Raspuns((FIXTURES / "api_token.xml").read_bytes())
        faults += 1
        if faults == 1:
            corp = (
                b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                b"<s:Fault><faultstring>tokenKey expired</faultstring></s:Fault>"
                b"</s:Body></s:Envelope>"
            )
            return _Raspuns(corp)
        return _Raspuns((FIXTURES / "api_search.xml").read_bytes())

    client = Client(opener=opener)
    recs = client.search(an=2016)
    assert len(recs) == 1 and faults == 2


def test_a_token_fault_that_never_clears_stops_rather_than_loops():
    client = Client(opener=_opener_fault("tokenKey is invalid"))
    with pytest.raises(TokenExpired):
        client.search(an=2016)


def test_a_non_token_fault_is_not_retried():
    """A malformed query or a server error is not fixed by a new token, so it is raised at once —
    GetToken succeeds, the single Search faults, and there is no second Search."""
    cauta = 0

    def opener(cerere, timeout=60):
        nonlocal cauta
        if "GetToken" in cerere.headers.get("Soapaction", ""):
            return _Raspuns((FIXTURES / "api_token.xml").read_bytes())
        cauta += 1
        corp = (
            b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            b"<s:Fault><faultstring>Incorrect syntax near the keyword 'and'</faultstring>"
            b"</s:Fault></s:Body></s:Envelope>"
        )
        return _Raspuns(corp)

    with pytest.raises(ApiError):
        Client(opener=opener).search(an=2016)
    assert cauta == 1
