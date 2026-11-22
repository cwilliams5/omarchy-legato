# Legato branding

Picked (2026-11-21): Slur, in `legato/`. The other Legato marks are in
`alternatives/`; the Rubato marks drawn while choosing between the two names
are in `alternatives/naming-comparisons/`.

## The name

- **Legato** is the musical instruction to play notes smoothly, with no break
  between them. Legato carries one episode across your phone and your
  computers without a break: pause here, carry on there, come back, and it's
  where you left off.
- It's Italian for **"tied together"**: your devices, tied together through
  Pocket Casts' sync.
- **Trim Silence** closes the gaps between words, so the speech
  itself gets more legato.

Legato is a Pocket Casts player, not part of Pocket Casts: the name
deliberately doesn't borrow theirs.

**Other finalists:** Rubato ("stolen time": fits speed and Trim Silence, but
says nothing about moving between devices, which is the point), Presto,
Cue, Shuttle (an Android music player of that name exists), Playhead,
Splice, Formant.

**Avoid in later renames:** "Pocket Casts" in the name (it's their name, and
the original plugin's). Taken by other Omarchy plugins: Segue, Spool,
Homing, Relay.

## The logo

The legato slur, the curved line that tells a player to connect the notes,
over two noteheads. At bar size it reads as a pair of headphones: the slur
for "no break", the headphones for listening. It won because it's the
clearest of the marks at 16px and it carries both layers. The wordmark
repeats the slur under the word, the way it sits under a phrase of music; in
the side-by-side lockups the word goes without it, since the mark already is
one.

Alternatives:

- **Ell** (`alternatives/ell/`): a script ℓ drawn as one unbroken stroke
  around a play triangle. The most elegant, but at 16px it's just an ℓ, which
  reads as the liter symbol.
- **Handoff** (`alternatives/handoff/`): a phone tied to a monitor by the
  slur. Says exactly what Legato does, but at bar size it's a generic
  "devices" icon.
- **Naming comparisons:** Rubato's metronome (at 16px it drifted toward a
  slashed A) and its stolen-time clock (clean, but a plain clock says nothing
  about listening). A first clock with r-shaped hands read as the ®
  symbol and was dropped.

## Voice

Plain and practical. Windows terms where they help. No hype, no emoji.
"Legato" in sentences; the lowercase wordmark only as a logo.

"Pocket Casts" appears only to say what Legato works with ("a Pocket Casts
player for Omarchy"), never as part of its name, and wherever Legato is
described the unofficial notice goes with it: not affiliated with or
endorsed by Pocket Casts or Automattic.

## Palette

| Role | Name | Hex |
|---|---|---|
| Background | Ink | `#1B1F2A` |
| Accent | Rose | `#F2789F` |
| Highlight | Gold | `#F4C26B` |
| Text | Ivory | `#F5EFE6` |
| Accent on light | Deep rose | `#D94F7C` |

Contrast: Ivory on Ink 14.4:1, Rose on Ink 6.2:1, Deep rose on white 3.9:1.

Legato's panel and bar chip follow the user's Omarchy theme. This palette is
for the logo, README art and the social preview.

## Rules for the logo

- **One color first** (`currentColor`), so it can follow a theme. The accent
  (the slur) is optional; the noteheads are always `currentColor`.
- **It reads at 16px.**
- **Drawn as paths:** no fonts needed.
- **`build.py` regenerates everything:** `python3 branding/build.py`.

## Files

```
branding/
  build.py                  regenerates everything below
  BRANDING.md               this file
  legato/                   the picked mark
    icon.svg                one color (currentColor)
    icon-color.svg          with the rose slur
    wordmark.svg            one color, slur under the word
    wordmark-color.svg
    lockup-light.svg        mark + word, dark ink, for light backgrounds
    lockup-dark.svg         mark + word, light ink, for dark backgrounds
    tile.svg                the mark on an Ink rounded square (app icon)
    preview.png             the sheet it was chosen from
  alternatives/
    ell/  handoff/          the other Legato marks
    naming-comparisons/     Rubato's marks and the comparison grid
icon.svg                    (repo root) the app tile, for listings and the README
```
