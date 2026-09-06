"""Vendor the three typefaces into `app/fonts/`, subset to the alphabet this app actually sets.

The app ships as a static, offline-first page whose CSP is `font-src 'self'`. That single directive
is why this script exists: a `<link>` to `fonts.googleapis.com` is *blocked* by that policy, so for
as long as the page pulled its webfonts from Google it silently rendered in Georgia and whatever
the system called sans-serif. Self-hosting is not an optimisation here — it is the only way the
chosen faces render at all.

Three faces, three jobs:

- **Aileron** (`--sans`) — USR's typeface, and so the whole UI chrome: header, tabs, labels,
  findings, buttons. CC0-1.0, Sora Sagano, taken from the designer's own release at
  <https://dotcolon.net/fonts/aileron/> (v0.102). Not from `@fontsource/aileron`, whose only subset
  is `latin` and is therefore missing ă Ă ș Ș ț Ț — unusable for Romanian.
- **Spectral** (`--serif`) — the consolidated act text and the plain-language rewrite, i.e. the two
  places a reader reads *law*. Kept serif on purpose: the document should look like a document.
- **IBM Plex Mono** (`--mono`) — locators, cross-references, fragments, diff output.

Both OFL faces come from `google/fonts` as unhinted TTF and are subset here rather than pulled from
a CDN's pre-made slices, so all three families end up covering exactly the same codepoints and no
glyph falls back mid-word.

## The charset

`CHARSET` is deliberately wider than Romanian. It is every block the page could plausibly set in a
text face — Latin through Latin Extended-B (Romanian's comma-below ș ț live at U+0218–021B, in
Extended-B, *not* in Latin-1), general punctuation, currency, and the arrow/geometric/dingbat
blocks. Subsetting keeps only what a font actually has, so asking for more than a face carries
costs nothing; asking for less risks a missing glyph in a legal text we do not control.

The app also sets a handful of symbols no text face carries — ⚠ ⚙ ★ ⟲ ⤢ — which fall through to
the system emoji/symbol font. That is the behaviour today and stays the behaviour; the fallback
chains in the `--sans`/`--serif`/`--mono` tokens are what catch them.

## The one repair

Aileron v0.102 has no U+00A0. A no-break space is not decoration in a legal text — it is what holds
`art. 5` and `30 de zile` together across a line break — and a missing one drops the run into the
fallback face mid-sentence. Since U+00A0 is metrically identical to U+0020 in this design, we map
it onto the existing `space` glyph rather than leave the hole. Nothing is invented: it is the
font's own space, reachable from a second codepoint.

Needs `fonttools` and `brotli` (dev group only — the built page ships the `.woff2` files, not this
script). Run: `uv run python -m scripts.fonturi`.
"""

from __future__ import annotations

import io
import shutil
import urllib.request
import zipfile
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "app" / "fonts"

UA = "Mozilla/5.0 (X11; Linux x86_64)"

AILERON_ZIP = "https://dotcolon.net/files/fonts/aileron_0102.zip"
GOOGLE = "https://raw.githubusercontent.com/google/fonts/main"

# Latin + Latin-1 + Extended-A + Extended-B (Romanian ș ț), punctuation, super/subscripts,
# currency, maths, arrows, box drawing, geometric shapes, misc symbols, dingbats.
CHARSET = (
    "U+0020-007E,U+00A0-00FF,U+0100-017F,U+0180-024F,"
    "U+2000-206F,U+2070-209F,U+20A0-20BF,U+2100-214F,U+2190-21FF,U+2200-22FF,"
    "U+2500-257F,U+25A0-25FF,U+2600-26FF,U+2700-27BF,U+27C0-27EF,U+2900-297F"
)

# (output stem, source, weight, style). The weights are the three the stylesheet actually asks for
# — 400, 600, 700 — plus a true italic per text face, so the browser never has to synthesise one.
AILERON = [
    ("aileron-400", "Aileron-Regular.otf"),
    ("aileron-400i", "Aileron-Italic.otf"),
    ("aileron-600", "Aileron-SemiBold.otf"),
    ("aileron-700", "Aileron-Bold.otf"),
]
OFL = [
    ("spectral-400", "ofl/spectral/Spectral-Regular.ttf"),
    ("spectral-400i", "ofl/spectral/Spectral-Italic.ttf"),
    ("spectral-600", "ofl/spectral/Spectral-SemiBold.ttf"),
    ("spectral-700", "ofl/spectral/Spectral-Bold.ttf"),
    ("plex-mono-400", "ofl/ibmplexmono/IBMPlexMono-Regular.ttf"),
    ("plex-mono-600", "ofl/ibmplexmono/IBMPlexMono-SemiBold.ttf"),
]

# The codepoints a Romanian legal text cannot render without. Checked after subsetting, on every
# file, so a bad upstream or an over-tight charset fails the build instead of shipping tofu.
OBLIGATORII = "aăâîșțAĂÂÎȘȚ0123456789 ,.;:()[]«»„”–—…§°·"

LICENTE = """# Fonts vendored into this app

All three are redistributable and are shipped subset (see `scripts/fonturi.py`).

## Aileron — `aileron-*.woff2`

Sora Sagano, version 0.102. **CC0-1.0** (public domain dedication) —
<https://creativecommons.org/publicdomain/zero/1.0/>. Source: <https://dotcolon.net/fonts/aileron/>.
No attribution is required; it is recorded here because it is true, not because it is owed.

This is the typeface usr.ro sets, which is why it is the typeface of this app's interface.

## Spectral — `spectral-*.woff2`

Production Type. **SIL Open Font License 1.1** —
<https://openfontlicense.org/>. Source: <https://github.com/google/fonts/tree/main/ofl/spectral>.

## IBM Plex Mono — `plex-mono-*.woff2`

IBM. **SIL Open Font License 1.1**. Source:
<https://github.com/google/fonts/tree/main/ofl/ibmplexmono>.

The OFL permits redistribution of modified (here: subset) copies provided they are not sold on
their own and do not use the Reserved Font Name. The files keep their original family names and
are served as part of this application.
"""


def descarca(url: str) -> bytes:
    cerere = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(cerere, timeout=60) as raspuns:  # noqa: S310 — fixed https hosts
        return raspuns.read()


def repara_nbsp(font: TTFont) -> bool:
    """Point U+00A0 at the font's own `space` glyph when the face never mapped it.

    Returns True when a repair was made, so the caller can say so out loud.
    """
    nume_spatiu = font.getBestCmap().get(0x0020)
    if nume_spatiu is None:
        return False
    reparat = False
    for tabel in font["cmap"].tables:
        if tabel.isUnicode() and 0x00A0 not in tabel.cmap:
            tabel.cmap[0x00A0] = nume_spatiu
            reparat = True
    if reparat:
        # hmtx is keyed by glyph, not codepoint, so the advance width comes along for free.
        font["hmtx"].metrics.setdefault(nume_spatiu, font["hmtx"].metrics[nume_spatiu])
    return reparat


def taie(sursa: bytes, stem: str) -> int:
    """Subset one face to CHARSET, repair U+00A0, write `app/fonts/<stem>.woff2`."""
    font = TTFont(io.BytesIO(sursa))
    reparat = repara_nbsp(font)

    optiuni = subset.Options()
    optiuni.flavor = "woff2"
    optiuni.desubroutinize = True
    optiuni.layout_features = ["*"]  # keep kerning and the default ligature/positioning set
    optiuni.name_IDs = ["*"]  # keep family/licence strings — the OFL wants them intact
    optiuni.notdef_outline = True
    optiuni.drop_tables = ["FFTM"]
    optiuni.unicodes = subset.parse_unicodes(CHARSET)

    subsetter = subset.Subsetter(options=optiuni)
    subsetter.populate(unicodes=optiuni.unicodes)
    subsetter.subset(font)

    acoperire = set(font.getBestCmap())
    lipsa = [c for c in OBLIGATORII if ord(c) not in acoperire]
    if lipsa:
        raise SystemExit(f"{stem}: nu are glifele obligatorii {lipsa!r} — nu pot livra asta")

    iesire = FONTS / f"{stem}.woff2"
    font.flavor = "woff2"
    font.save(iesire)
    marca = " (+U+00A0)" if reparat else ""
    octeti = iesire.stat().st_size
    print(f"  {iesire.name:22s} {octeti / 1024:6.1f} KB  {len(acoperire)} glife{marca}")
    return octeti


def main() -> None:
    if FONTS.exists():
        shutil.rmtree(FONTS)
    FONTS.mkdir(parents=True)
    total = 0

    print(f"Aileron — {AILERON_ZIP}")
    arhiva = zipfile.ZipFile(io.BytesIO(descarca(AILERON_ZIP)))
    for stem, nume in AILERON:
        total += taie(arhiva.read(nume), stem)

    print(f"Spectral + IBM Plex Mono — {GOOGLE}")
    for stem, cale in OFL:
        total += taie(descarca(f"{GOOGLE}/{cale}"), stem)

    (FONTS / "LICENTE.md").write_text(LICENTE, encoding="utf-8")
    print(f"\n{len(AILERON) + len(OFL)} fișiere, {total / 1024:.0f} KB în app/fonts/")


if __name__ == "__main__":
    main()
