"""The data files validate against their schemas, and the schemas resolve.

In the monorepo this was `scripts/validate_data.py`, one gate over every simulator's data. Split
out, that gate does not come with the package, so it is rebuilt here as a test — smaller, and
scoped to this package's own two documents.

`jsonschema` and `referencing` are dev dependencies rather than runtime ones. Nothing the linter
does at run time needs them: the extractors are `re` and `difflib`, and a document is validated
when it is written, not every time it is read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

RADACINA = Path(__file__).resolve().parent.parent
DATE = RADACINA / "data"
SCHEME = RADACINA / "schema"


def _registru() -> Registry:
    """Make the shared vocabulary resolvable by its bare filename, as the monorepo's gate did."""
    resurse = [
        (cale.name, Resource.from_contents(json.loads(cale.read_text(encoding="utf-8"))))
        for cale in SCHEME.glob("*.json")
    ]
    return Registry().with_resources(resurse)


def _documente() -> list[Path]:
    return sorted(DATE.glob("*.json"))


def test_there_is_data_to_validate():
    assert _documente(), "pachetul are date, deci are ce valida"


@pytest.mark.parametrize("fisier", _documente(), ids=lambda p: p.name)
def test_every_document_points_at_a_schema_that_exists(fisier: Path):
    """A document without a `$schema` is not merely unvalidated. In the monorepo the shared gate
    resolved the empty reference to the data directory itself, passed an `exists()` check and then
    died reading a directory — which is how this package first turned CI red there."""
    document = json.loads(fisier.read_text(encoding="utf-8"))
    ref = document.get("$schema", "")
    assert ref, f"{fisier.name}: nu declară $schema"
    assert (fisier.parent / ref).resolve().is_file(), (
        f"{fisier.name}: $schema trimite la {ref}, care nu e un fișier"
    )


@pytest.mark.parametrize("fisier", _documente(), ids=lambda p: p.name)
def test_every_document_validates(fisier: Path):
    document = json.loads(fisier.read_text(encoding="utf-8"))
    schema_cale = (fisier.parent / document["$schema"]).resolve()
    schema = json.loads(schema_cale.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=_registru())
    erori = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    assert not erori, "\n".join(
        f"{fisier.name}: {'/'.join(map(str, e.path))}: {e.message}" for e in erori[:10]
    )


def test_the_vendored_vocabulary_says_it_is_a_copy():
    """A copied vocabulary drifts silently. The file has to carry the fact that it is a copy, or
    the next person to read it will not know there is an upstream to keep it level with."""
    provenance = json.loads((SCHEME / "provenance.schema.json").read_text(encoding="utf-8"))
    assert "VENDORED" in provenance["description"]
    assert "romania-reforms" in provenance["description"]


def test_the_three_confidence_levels_are_the_ones_the_package_uses():
    """`assumed` on the gold set and `derived` on every inferred finding mean what this file says
    they mean. If the vocabulary is re-vendored and these change, the labels stop being true."""
    provenance = json.loads((SCHEME / "provenance.schema.json").read_text(encoding="utf-8"))
    niveluri = provenance["$defs"]["provenance"]["properties"]["confidence"]["enum"]
    assert niveluri == ["verbatim", "derived", "assumed"]

    severitati = provenance["$defs"]["limitation"]["properties"]["severity"]["enum"]
    assert severitati == ["blocking", "material", "note"]
