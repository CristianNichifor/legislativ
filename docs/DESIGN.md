# Sistemul de design — aliniat la identitatea USR

The app's colour and type come from USR's public identity. This file records what was taken, what
was changed, and why — so the next person to touch a token can tell a brand decision from an
accessibility one, and does not quietly undo the second while honouring the first.

Everything lives in one place: the `:root` block at the top of `app/index.html`, in three copies
(light, `prefers-color-scheme: dark`, and an explicit `[data-theme="dark"]`). `web/index.html` is
generated from it and must not be edited.

## Where the brand values come from

Read off the stylesheet usr.ro serves (`_next/static/chunks/*.css`), not sampled from screenshots:

| | value |
| --- | --- |
| `--blue` (primary) | `#002a59` |
| `--red` (accent) | `#ff0021` |
| link blue | `#00458c` |
| slate ramp | `#093349` · `#4c698a` · `#7f94ac` · `#b2bfcd` · `#e5e9ee` · `#f0f2f5` |
| typeface | Aileron (Light / Regular / SemiBold / Bold / Italic) |

## The three rules

1. **Brand navy is structure.** Ink, headings, the deep end of the neutral ramp.
2. **Brand blue is interaction.** Links, focus rings, the active tab, the primary button. Nothing
   that is merely decorative gets it, and nothing that encodes severity gets it either.
3. **Brand red is severity — and only the blocking level of it.** It never appears as decoration.

The severity ramp itself (`--blocking` / `--material` / `--note` / `--good`) stays four
distinguishable hues rather than collapsing into the two brand colours. It is functional colour: a
check can list fifty findings, and triage-at-a-glance is the feature. Red, amber, teal and green
keep working for the ~8% of men with red–green colour vision deficiency, where a red/navy two-step
would not.

## Tokens

### Light

| token | value | note |
| --- | --- | --- |
| `--paper` | `#f0f2f5` | USR verbatim |
| `--surface` | `#fff` | |
| `--sunk` | `#e5e9ee` | USR verbatim |
| `--ink` | `#0a1f38` | navy-black, not neutral black |
| `--ink-mid` | `#365170` | |
| `--ink-mute` | `#526984` | see *deviations* |
| `--rule` | `#b2bfcd` | USR verbatim |
| `--rule-soft` | `#e5e9ee` | USR verbatim |
| `--accent` | `#00458c` | USR link blue |
| `--accent-wash` | `#e3ecf7` | |
| `--on-accent` | `#fff` | foreground for anything sitting *on* `--accent` |
| `--brand-red` | `#ff0021` | USR verbatim — non-text marks only |
| `--blocking` | `#c00019` | see *deviations* |
| `--material` | `#8a5c14` | |
| `--note` | `#0f5f78` | |
| `--good` | `#2f6b43` | |

### Dark

USR ships no dark mode, so this half is derived. The pleasing part: USR's *light* slate ramp
inverts directly into the dark text ramp, so `#e5e9ee` / `#b2bfcd` / `#7f94ac` are still brand
values, just doing the opposite job.

| token | value | note |
| --- | --- | --- |
| `--paper` | `#0a1420` | |
| `--surface` | `#111d2c` | |
| `--sunk` | `#16232f` | |
| `--ink` | `#e5e9ee` | USR verbatim, role inverted |
| `--ink-mid` | `#b2bfcd` | USR verbatim, role inverted |
| `--ink-mute` | `#7f94ac` | USR verbatim, role inverted |
| `--rule` | `#24374e` | |
| `--rule-soft` | `#1a2a3c` | |
| `--accent` | `#6ea8e8` | brand blue lifted for a dark ground |
| `--accent-wash` | `#12283f` | |
| `--on-accent` | `#0a1420` | dark text on the pale accent |
| `--brand-red` | `#ff0021` | USR verbatim |
| `--blocking` | `#ff5c70` | |
| `--material` | `#d7ab6b` | |
| `--note` | `#6fb3cc` | |
| `--good` | `#7fb98f` | |

## Contrast

Every text token clears **WCAG AA (4.5:1)** against all three of its backgrounds — `--surface`,
`--paper` and `--sunk` — in both themes. `--brand-red` is held to the 3:1 non-text bar because it
is never used for text.

| | worst case | ratio |
| --- | --- | --- |
| `--ink` | on `--paper` | 14.8 |
| `--ink-mid` | on `--sunk` | 6.7 |
| `--ink-mute` (light) | on `--sunk` | 4.6 |
| `--ink-mute` (dark) | on `--sunk` | 5.1 |
| `--accent` (light) | on `--paper` | 8.4 |
| `--accent` (dark) | on `--surface` | 6.8 |
| `--on-accent` | on `--accent`, dark | 7.4 |
| `--blocking` (light) | on `--paper` | 5.8 |
| `--blocking` (dark) | on `--surface` | 5.7 |
| `--material` | on `--paper` | 5.2 |
| `--note` | on `--paper` | 6.4 |
| `--good` | on `--paper` | 5.7 |
| `--brand-red` (non-text) | on `--paper` | 3.6 |

## The deviations, and why

Two USR values are not used as published, because as published they fail AA. This app is read by
people checking whether a law does what it claims to; illegible is not a style choice here.

- **`#7f94ac` is 3.1:1 on white.** It is used in dark mode only, where it measures 5.9:1 and is
  brand-verbatim. Light mode's muted text is `#526984` instead.
- **`#ff0021` is 4.0:1 on white** — below the 4.5:1 text bar, above the 3:1 non-text one. So the
  pure brand red survives as `--brand-red` on marks that carry no text: the 2–3px severity rails on
  cards, chips and consolidated provisions, the abrogation dot in the table of contents, and the
  ring and edges in the graph. Text and 1px borders use `--blocking` (`#c00019`, 6.5:1) — the same
  red, darkened until it can be read.

The pairing is deliberate rather than a compromise: the rail is the mark, the words beside it are
the label, and they are allowed to be two tunings of one colour.

## Type

| slot | face | where |
| --- | --- | --- |
| `--sans` | **Aileron** 400 / 400i / 600 / 700 | all interface chrome: header, tabs, labels, findings, buttons, chips |
| `--serif` | **Spectral** 400 / 400i / 600 / 700 | the consolidated act text and the plain-language rewrite — the two places a reader reads *law* |
| `--mono` | **IBM Plex Mono** 400 / 600 | locators, cross-references, fragments, diff output |

Aileron is USR's typeface, so it carries the brand everywhere a reader sees interface. The serif is
kept for the law itself on purpose: a document should look like a document, and long passages of
statute read better with one. IBM Plex Sans, the old UI face, is gone.

All three are **self-hosted** and vendored into `app/fonts/` by `scripts/fonturi.py`; the build
copies them to `web/fonts/` and the service worker precaches them. This is not an optimisation —
the page runs under `font-src 'self'`, which blocks `fonts.gstatic.com` outright. For as long as
the page linked Google Fonts, it silently rendered in Georgia and the system sans.

Note for anyone tempted by `@fontsource/aileron`: its only subset is `latin`, which has no
**ă Ă ș Ș ț Ț**. Aileron comes from the designer's own release instead. It is CC0-1.0 and also has
no U+00A0; `scripts/fonturi.py` maps that codepoint onto the font's own `space` glyph, because a
missing no-break space in a legal text drops the run into a fallback face mid-sentence.

## The graph palette

`PALETA` in `app/index.html` gives each act a stable colour so every dot reads as its own node.
Twelve hues on the OKLCH wheel at a single lightness (L .545, C .115), spread over the 308° left
after cutting a wedge out around the brand red — a red ring means *abrogat*, so no act's own colour
may imitate one. Nearest swatch sits 26° off it and reads as ochre. Uniform lightness means no act
looks more important than another; every swatch clears 3:1 on both grounds.

## What is deliberately absent

No logo, no party name, no navy header bar. The palette and the typeface carry the identity to
anyone who knows it, and the tool stays legible as a civic instrument rather than party material.
That was a decision, not an omission — revisit it explicitly if it should change.
