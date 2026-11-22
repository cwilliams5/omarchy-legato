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
- [x] A2 Qt 6.12 colours: the 7 bare `Color.` references (Panel.qml,
  BarWidget.qml, AboutView.qml) become `Commons.Color` with `import
  qs.Commons as Commons`. Check the accent and the About page render in
  Cody's theme.
- [x] A3 Bar chip icon: the Legato mark (an SVG in `currentColor`) instead
  of the font glyph `󰦔`, when nothing is loaded.
- [x] A4 Title display: a setting for the chip's label: off, a static
  title cut off with "…", or the scrolling marquee (today's behavior).

### B. Trim Silence

- [x] B1 Bridge: `trim off|mild|medium|madmax`, saved in `prefs.json`,
  applied when mpv starts and live: mpv's `af` with
  `lavfi=[silenceremove=stop_periods=-1:stop_duration=..:stop_silence=..:stop_threshold=-42dB:detection=peak:timestamp=copy]`.
- [x] B2 Check that `time-pos` stays in the episode's own time with
  `timestamp=copy` (positions pushed to Pocket Casts must not drift). Test
  with generated audio that has known silences (tone, gap, tone).
- [x] B3 Panel control and an IPC command (`cycleTrim`); show the level
  beside the speed.
- [x] B4 Follow the phone's effects: **decided 2026-11-21, not for v1.**
  Legato keeps one global speed, Trim Silence and Volume Boost of its own,
  for every show, not synced (option A). Why: Pocket Casts' Android app
  doesn't upload playback effects. Test: Cody changed his global effects
  (1.5x Mad Max boost on → 1.3x Mild boost off) and one show's own effects;
  20+ minutes and a watcher later the server still had the old global speed
  (last modified 2025-09, probably from another device) and no per-show
  change. Revisit "Follow phone" (read-only: global, or the show's own
  effects when `playbackEffects` is on; Legato's buttons as a per-episode
  override) if that changes. Where the data lives:
  - global: `POST /user/named_settings/update {"m":"web"}` (the web
    player's own read): `playbackSpeed`, `trimSilence` (0-3),
    `volumeBoost`/`volumeBoostGlobal`, `skipBack`, `skipForward`;
  - per show: `/user/podcast/list` `settings`: `playbackEffects`,
    `playbackSpeed`, `trimSilence`, `volumeBoost`, `autoStartFrom`,
    `autoSkipLast`.
  Per-show settings inside Legato (option D) were ruled out: too much UI
  for v1.
- [x] B4v Volume Boost, global like the others (Pocket Casts' +10 dB, into
  a limiter, after Trim Silence).
- [ ] B4b Honor each show's `autoStartFrom` (start a new episode N seconds
  in) and `autoSkipLast` (treat N seconds before the end as the end), as the
  apps do. Legato ignores both today (one of Cody's shows skips a 15 s
  intro). Unlike the effects, these do reach the server ("changed" on all of
  Cody's shows).
- [ ] B5 Optional: "time saved", as the Pocket Casts apps show it.

### C. Video window (picture in picture)

- [x] C1 Bridge: `video on|off` sets mpv's `vid` and `force-window`,
  with `--wayland-app-id=legato-video`; mpv's close button
  (`keybind CLOSE_WIN`) hides the video instead of quitting playback.
- [x] C2 Placement: when the window appears, float it, pin it (all
  workspaces), size it and put it in a corner through Hyprland dispatches;
  remember where the user moved it. Never open it on a hidden workspace.
- [x] C3 The panel's video button shows only when the episode has a video
  track.
- [x] C4 Decide how Trim Silence and video mix: trimming pauses while the
  video shows (cutting audio under a picture makes it jump) and comes back
  when it closes.
- [x] C5 Hardware decoding only while visible; nothing decoded while hidden.

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
- 2026-11-21 (later): A1 posted (issues #4-6, PRs #7-9 upstream). A2-A4
  done (Qt 6.12 colours, the mark in the bar, a still title by default).
  B1-B3 done: Trim Silence with Pocket Casts' values; `timestamp=copy`
  measured to keep positions in episode time. B4 researched (needs Cody's
  call). C1-C5 done and checked live with a real video episode: the window
  floats, pins, sits bottom-right without taking focus, remembers where it
  was moved, and hiding it keeps playback going. Found on the way: mpv needs
  WAYLAND_DISPLAY to draw a window (the closed environment had dropped it),
  and mpv 0.41 reads the clipboard at start unless told not to.
