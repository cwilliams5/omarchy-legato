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
- [x] B4b Honor each show's `autoStartFrom` (start a new episode N seconds
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
- [x] D2 Pausing before the machine sleeps: a logind delay guard while an
  episode is loaded (`sleepguard`, `pauseOnSleep`). Built 2026-11-21; the
  guard's lifecycle checked live, a real lid-close still to confirm.
  (Was: open question.) Omarchy pauses
  no media on suspend; Legato's gap check already prevents bad pushes, but
  the audio plays on behind the lock screen after waking.

### E. From Cody's first day of use (2026-11-21)

- [x] E1 Effects on their own row (they ran into the volume slider).
- [x] E2 Trim kept working with the video window (it used to switch off,
  and closing the window with its own × never put it back); polls repair
  the filter chain.
- [x] E3 Video window without mpv's on-screen controls; always on top as
  a choice (now in the window's own menu, E9, not a setting).
- [x] E4 Settings page behind the gear (`g`), built from the schema.
- [x] E5 Right-click menu (play, move to top/bottom, remove, mark played);
  right- and middle-click no longer remove from Up Next.
- [ ] E6 Drag to reorder Up Next. The web player does it with
  `POST /up_next/sync {"version":2,"upNext":{"changes":[{"action":5,
  "modified":<ms>,"episodes":[{uuid,title,url,podcast,published}, ...]}]}}`,
  the whole list in its new order (action 5 = replace). Risk: a replace
  sent while the phone changes Up Next can drop the phone's change, so
  re-read the list just before sending. UI: a drag handle on queued rows.
- [ ] E7 Optional: after the video window closes, restart mpv at the same
  spot to give back the ~450 MB the GPU driver keeps mapped (an audio-only
  player is ~90 MB); today the idle unload does it eventually.

- [ ] E8 **Bug (Cody, 2026-11-21): right-clicking the video window shows
  no menu.** Cause: `bind_video_window_keys()` binds `MBTN_RIGHT` to
  `context-menu`, which does nothing on Linux; mpv's menu here is
  context_menu.lua, opened by `script-message-to context_menu open`
  (verified live). Change the binding and its assertion in
  tests/test_bridge.py (`test_closing_the_video_window_never_quits_the_player`),
  deploy, then Cody re-opens the video (re-applies keys to his running
  player) and right-clicks it.
- [x] E9 Video window on Omarchy's floating workspaces: placed and pinned
  (rule through `o.window`, named, re-sent before each load while video is
  on), no title bar (`hyprbars:no_bar`), geometry only learned from a
  window that got the rule; a right-click menu with Always on top: On/Off
  (`videopin`, remembered in prefs.json), pause/play, hide; menu text at
  full size (`--osd-scale-by-window=no`). Confirmed by Cody except the
  menu itself (E8).
- [x] E10 Up Next right-click menu confirmed by Cody.
- [ ] D2 follow-up: Cody's real lid-close test (play, close the lid, the
  phone shows the position, reopen: paused).

### Release prep (go-public)

- [ ] CLAUDE.md current: status, rules, platform facts, Credits
  (refreshed 2026-11-21 late; check again at release)
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
- 2026-11-21 (evening): B4 decided (effects global and Legato's own: the
  Android app uploads none, tested with Cody changing his phone's settings
  and a watcher). Volume Boost (+10 dB into a limiter, after trim). B4b skip
  intro/outro (Cody's PD Stories skips 15 s). D2 pause before sleep: a
  logind delay guard while an episode is loaded; lifecycle checked live
  (appears with playback, restarts after exiting, leaves nothing behind on
  stop, steady across polls). Left: a real lid-close test by Cody, then D1
  screenshots and release prep.

- 2026-11-21 (night): Cody's first day of use: E1-E5 done and deployed;
  the live player's trim was restored by the new filter repair; the two
  episodes right-click had dropped from Up Next were put back. Measured a
  paused player: 0% CPU, ~90 MB audio-only, ~570 MB once a video has been
  shown in it (GPU driver), which is what unloadAfterMinutes trades against
  media keys working.
- 2026-11-21 (late): the video window froze (mpv's video output deadlocked
  on the NVIDIA dGPU). Fixed: video renders on the display's GPU (Intel:
  0.11 s to show, 98 MB, vaapi), a watchdog ends a hung player (only our
  own mpv, proven by socket peer credentials), old players get their
  controls hidden, and the decoder may drop frames so trimmed video catches
  up. Checked live and restored.
- 2026-11-21 (later still): on a floating workspace the video window grew
  Omarchy's title bar (dead minimize/maximize on a pinned window) and, a
  few episodes on, opened big and unpinned (Omarchy's floating open rule
  won over Legato's). Fixed: rule via o.window, named, re-sent before each
  load while the video is on; hyprbars:no_bar; geometry only learned from a
  window that got the rule. New: the window's right-click menu (Always on
  top: On/Off, pause/play, hide), full-size text in it. Checked live on
  floating workspace 1 and restored.
