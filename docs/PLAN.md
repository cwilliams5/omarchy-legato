# Legato: development plan

Written 2026-11-21 after naming and setup. It's the source of truth for
what's left: a session that starts cold (after a context compaction, or a
different Claude) reads CLAUDE.md, then this, and carries on from the first
unchecked item. Update it as you go: tick items, add what you learn, and
keep the log at the end.

## Goal

Legato 1.0.0 on the Omarchy plugin marketplace: the sync-safe player it
already is, plus Pocket Casts-style Trim Silence, an optional video window,
title display options, its own icon in the bar, and a README and screenshots
of its own.

## Decisions already made (don't re-litigate)

- Name Legato, logo Slur, palette Ink/Rose/Gold/Ivory (BRANDING.md).
- A hard fork with its own id (`io.github.cwilliams5.legato`); the original
  stays credited in LICENSE, README, About and CLAUDE.md.
- The three fixes are still offered upstream, from the old fork's branches,
  with Cody reviewing the exact text first.
- No automatic import of the original plugin's sign-in or settings.
- Version 0.2.0 now, 1.0.0 at release. Distribution: the plugin marketplace.
- Trim Silence uses Pocket Casts' exact Mild/Medium/Mad Max values
  (CLAUDE.md, platform facts), with speed applied after trimming.
- Nothing polls while paused or idle (CLAUDE.md rule 4): new features keep
  that.

## Phases

### A. After the rename

- [x] A1 Upstream: three issues and three PRs to Nine Point Labs from
  `cwilliams5/omarchy-pocketcasts` (branches `fix/resume-checks-server`,
  `perf/event-driven` on top of it, `fix/report-load-failures` on top of
  that). Draft the text, Cody reviews it, then post. Keep the old fork while
  they're open. Posted 2026-11-21: issues #4 #5 #6, PRs #7 #8 #9
  (Ninepointlabs-Omarchy-Extras/omarchy-pocketcasts).
- [ ] A2 Qt 6.12 colours: the 7 bare `Color.` references (Panel.qml,
  BarWidget.qml, AboutView.qml) become `Commons.Color` with `import
  qs.Commons as Commons`. Check the accent and the About page render in
  Cody's theme.
- [ ] A3 Bar chip icon: the Legato mark (an SVG in `currentColor`) instead
  of the font glyph `󰦔`, when nothing is loaded.
- [ ] A4 Title display: a setting for the chip's label: off, a static
  title cut off with "…", or the scrolling marquee (today's behavior).

### B. Trim Silence

- [ ] B1 Bridge: `trim off|mild|medium|madmax`, saved in `prefs.json`,
  applied when mpv starts and live: mpv's `af` with
  `lavfi=[silenceremove=stop_periods=-1:stop_duration=..:stop_silence=..:stop_threshold=-42dB:detection=peak:timestamp=copy]`.
- [ ] B2 Check that `time-pos` stays in the episode's own time with
  `timestamp=copy` (positions pushed to Pocket Casts must not drift). Test
  with generated audio that has known silences (tone, gap, tone).
- [ ] B3 Panel control and an IPC command (`cycleTrim`); show the level
  beside the speed.
- [ ] B4 Look into Pocket Casts' per-show effects (speed and trim sync to
  the server on Android): if the web API exposes them, follow the phone's
  settings per show.
- [ ] B5 Optional: "time saved", as the Pocket Casts apps show it.

### C. Video window (picture in picture)

- [ ] C1 Bridge: `video on|off` sets mpv's `vid` and `force-window`,
  with `--wayland-app-id=legato-video`; mpv's close button
  (`keybind CLOSE_WIN`) hides the video instead of quitting playback.
- [ ] C2 Placement: when the window appears, float it, pin it (all
  workspaces), size it and put it in a corner through Hyprland dispatches;
  remember where the user moved it. Never open it on a hidden workspace.
- [ ] C3 The panel's video button shows only when the episode has a video
  track.
- [ ] C4 Decide how Trim Silence and video mix (pause trimming while the
  video shows, or accept small skips).
- [ ] C5 Hardware decoding only while visible; nothing decoded while hidden.

### D. Polish

- [ ] D1 Fresh screenshots of Legato's own UI (replace preview*.png).
- [ ] D2 Open question: pausing before the machine sleeps. Omarchy pauses
  no media on suspend; Legato's gap check already prevents bad pushes, but
  the audio plays on behind the lock screen after waking.

### Release prep (go-public)

- [ ] CLAUDE.md current: status, rules, platform facts, Credits
- [ ] Then run the `go-public` skill

## Testing

- `tests/run` before every commit: both suites, about 20 s, nothing on
  screen. Each new behavior gets an end-to-end test against the fake server
  (`tests/test_bridge.py`, `PlayerTestCase`; set `AUDIO_SECONDS` for longer
  audio, and the fake serves byte ranges).
- Live checks on Cody's machine follow CLAUDE.md, "Working on it": a test
  episode he isn't listening to, his state recorded and restored, muted,
  never interrupting his playback.
- Resource checks: `tools/sample-bridge.py 180 "<label>"` while playing,
  paused and idle. Baseline after the fixes: 6 launches per 3 minutes
  playing, 0 paused, 0 idle.

## Log

- 2026-11-21: Reviewed the two Pocket Casts plugins; Nine Point Labs' synced
  but rewound other devices on resume and polled constantly. Fixed both plus
  silent load failures as a soft fork, tested live (bug reproduced on the
  original, fixed in the patch; launches 37 → 6 per 3 minutes playing, 5 → 0
  idle). Cody's phone ↔ laptop test passed. Hard-forked and named Legato
  (logo Slur); renamed, 0.2.0, private. Next: A1.
