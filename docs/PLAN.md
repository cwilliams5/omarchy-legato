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

- [x] D1 Fresh screenshots of Legato's own UI (media/, preview.png;
  2026-11-22, re-shot once after the video button's height fix).
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
- [x] E6 Drag to reorder Up Next: **decided 2026-11-21, not for v1.** The
  right-click menu's "to top" and "to bottom" are enough; drag would bring
  multi-select with it, and the feature keeps deepening. If it's ever
  revisited: the web player does it with
  `POST /up_next/sync {"version":2,"upNext":{"changes":[{"action":5,
  "modified":<ms>,"episodes":[{uuid,title,url,podcast,published}, ...]}]}}`,
  the whole list in its new order (action 5 = replace). Risk: a replace
  sent while the phone changes Up Next can drop the phone's change, so
  re-read the list just before sending. UI: a drag handle on queued rows.
- [x] E7 Restarting mpv after the video window closes, to give back GPU
  memory: **dropped 2026-11-21.** It was ~450 MB on the NVIDIA GPU; on the
  display's Intel GPU it's ~98 MB, and the idle unload frees it anyway.

- [x] E8 **Bug (Cody, 2026-11-21): right-clicking the video window shows
  no menu.** Cause: `bind_video_window_keys()` bound `MBTN_RIGHT` to
  `context-menu`, which does nothing on Linux; mpv's menu here is
  context_menu.lua, opened by `script-message-to context_menu open`.
  Fixed and deployed with E11; a running player gets it when its video
  window is next shown. Cody to confirm with a real right-click.
- [x] E9 Video window on Omarchy's floating workspaces: placed and pinned
  (rule through `o.window`, named, re-sent before each load while video is
  on), no title bar (`hyprbars:no_bar`), geometry only learned from a
  window that got the rule; a right-click menu with Always on top: On/Off
  (`videopin`, remembered in prefs.json), pause/play, hide; menu text at
  full size (`--osd-scale-by-window=no`). Confirmed by Cody except the
  menu itself (E8).
- [x] E10 Up Next right-click menu confirmed by Cody.
- [x] D2 follow-up: Cody's real lid-close test (play, close the lid, the
  phone shows the position, reopen: paused). Passed 2026-11-21.
- [x] E11 Video window transparency (Cody's idea, 2026-11-21), so the
  desktop shows through: Off (default) to 80% in tens, in the window's
  right-click menu (a "Transparency" submenu) and on the Settings page
  (a Video window section, with Always on top). Kept in prefs.json
  (`videoTransparency`) beside `videoPinned`. Applied as the window's own
  opacity (`set_prop`), not a rule: Omarchy's floating workspaces force
  every window opaque by a tag rule that beats another rule (tested). A
  `window.open` hook, added once per Hyprland config, sets it on each new
  video window. Built, tested and checked live on a stand-in window
  (new window at 30%, survives a rule re-evaluation, back to solid at 0);
  Cody to try it on the real one.

- [x] E12 (Cody, testing E11): the transparency made the right-click
  menu see-through too (mpv draws it inside the window). Now the window is
  solid while it has focus, which a right-click gives it. Confirmed by
  Cody, with E8, E11 and phase F.
- [x] E13 (Cody): keys pressed in the video window did mpv's own things.
  Now Legato's keys work there (Space, f/b and the arrows, n, s, p, t, o,
  v, +/-, the wheel for volume), through the service like the panel's,
  and mpv's built-in keys are off in it. Speed, Trim, Boost, volume and
  seeks show briefly on the video.

- [x] E14 (Cody, 2026-11-21): an episode's "video" was one still frame.
  Its MP4 carries the cover as a PNG video stream that mpv doesn't flag as
  cover art, so Legato offered the video window for it. Still-picture
  codecs no longer count as video; the video button also shows while the
  window is open, so a cover left showing can be hidden. (Also that night:
  a drag near the bar took Legato's chip off it, which disables the plugin;
  put back with `omarchy plugin enable io.github.cwilliams5.legato
  --section right --index 9`. Not a Legato bug.)

### F. Fresh-eyes review (2026-11-21, second session)

Two independent reviews (bridge, QML), each finding checked against the
code before it was taken; the worst reproduced against the fake server
first. Cody picked all of these. Each has a test.

- [x] F1 **An episode that ended here was set back to in progress.** mpv
  doesn't pause at the end (keep-open: `pause` stays off), so the view
  said playing: the poll timer kept running, each poll after 30 s pushed
  the end position as in progress, the idle unload never fired, and Play
  paused instead (pushing in progress again). Hit whenever autoplay was off
  or Up Next ran out. Now: an `ended` state, no pushes at the end, Play
  plays what was queued since or the episode again (`play_again`, which
  pushes it as in progress itself), dragging back from the end the same.
- [x] F2 **A skip or seek while paused pushed without asking**, so coming
  back after listening on the phone and skipping back first rewound the
  phone. Stop, Next, switching and the idle unload did the same with a
  paused position whose push failed before a sleep. One rule now (CLAUDE.md
  rule 1): paused, push only if moved and the last push was under 90 s
  ago; nothing while a resume is unconfirmed, not even on pause.
- [x] F3 The episode in the player, right-clicked in In Progress, New or a
  show page: Play reloaded it from Pocket Casts' older position; Remove or
  Move to bottom took it off the top of Up Next, which the next resume read
  as another device moving on. Now it offers only Play/Pause; `q`, `m` and
  the row buttons refuse it ("Next moves on").
- [x] F4 A "played" mark or Up Next removal that failed at an episode's
  end (network blip) is retried by later polls (`pendingFinish`, once a
  minute, six hours); the removal no longer depends on the mark; the next
  episode is put on top properly when the removal failed.
- [x] F5 The sleep guard's 4 s request timeout never applied (a default
  argument bound at definition); mpv commands waiting over 2 s (a slow
  `vid auto`) failed on the socket's connect timeout.
- [x] F6 prefs.json races: every change under its own lock
  (`prefs_update`), applied to mpv inside it; the poll re-reads prefs
  before repairing filters or saving the video window's spot. In the
  panel, a poll that began before a change is dropped for a fresh one.
- [x] F7 Seeks: holding `f`/`b`, wheel steps over the progress bar and
  right-clicks on the chip sent one bridge process and push each (busy
  errors, overshoot); now one seek per burst. A sideways swipe over the
  progress bar no longer seeks back.
- [x] F8 `x` (speed) never worked: the shell's key catcher takes `x` as
  delete. Speed is `p`; `x`/Delete take the highlighted episode off Up
  Next.
- [x] F9 A list reload asked for while that list was loading was dropped
  (two quick queue changes left the lists wrong for 5 minutes).
- [x] F10 Switching tabs overwrote "Tab to open first" (and rewrote
  shell.json each time); it no longer saves.
- [x] F11 Errors from speed (keybind) and volume changes with the panel
  closed now reach the OSD.
- [x] F12 The scrolling title froze mid-scroll when paused; it goes back
  to the start.
- [x] F13 The sleep guard backs off when it can't stay up (6 s doubling,
  gives up after five and says so), and polls only after a real sleep.
- Not taken (lower value, noted for later): concurrent token refreshes
  could sign you out if Pocket Casts rotates refresh tokens (unconfirmed;
  fixed anyway in 1.0.2, R1: refreshes share one); keyboard focus after
  signing in; the hero hidden while signed out with audio playing;
  `cmd_next` removing the current episode before finding nothing next; a
  broken stream's EOF counted as finished (taken 2026-11-23: H1); the wall
  clock for `lastSyncAt`; About's `Qt.openUrlExternally` outside rule 6's
  letter. Cody, 2026-11-23: only the broken stream is worth doing.

### G. Release review (2026-11-22, go-public stage 3)

An independent correctness review of everything changed since fca392b
(phase F's fixes and E11-E14). Each finding reproduced first; each fix has
a test that fails on the old code.

- [x] G1 A resume Pocket Casts never confirmed (network down) still pushed
  on pause when the last push was under 90 s old: the paused rule saw a
  "recent" push. Now an explicit `unconfirmed` flag, set on "unverified"
  and cleared by Pocket Casts' answer; nothing is pushed while it's set.
- [x] G2 A gathered seek (the 300 ms burst) fired after Next or a new
  episode and landed on the new one (and could run it past its end). The
  panel cancels it on Next, Stop, Play and episode changes, and the seek
  names its episode (`seek --episode`), which the bridge checks.
- [x] G3 An Up Next removal that only succeeded on a later retry left
  `atTop` set, so a replay was later switched away. The retry clears it.
- [x] G4 A sleep guard whose D-Bus monitor ended reported success and
  restarted every 3 s while paused. It fails now, so the back-off applies.
- [x] G5 About's privacy text still said the last tab was saved.

Then a "the marketplace reviewer will ask" pass (their human reviewer's
history on other submissions). Fixed, each with a failing-first test:

- [x] G6 mpv's TLS verification was off (mpv's default): `--tls-verify=yes`,
  tested on public podcast CDNs (NPR via Spotify's redirect chain, Podtrac)
  and refusing an expired certificate.
- [x] G7 Covers fell back to the web URL in Qt's Image when the cache
  missed: now only the cached file, and the cache keeps only JPEG, PNG or
  WebP up to 1 MiB.
- [x] G8 The sleep guard accepted any "boolean true" line: now only
  login1's broadcast PrepareForSleep (a unicast signal from another local
  account is ignored).
- [x] G9 No overall deadline on a bridge call: `BRIDGE_DEADLINE` (120 s)
  through SIGALRM, raising an exception the `except Exception` handlers
  can't swallow.
- [x] G10 Sign-out claimed success even if the tokens weren't deleted.
- [x] G11 README: mpv and mpv-mpris come with Omarchy; uninstall stops the
  player first; what auth.json keeps; the stock tools it uses.
- [x] G12 The sign-in fields were Qt TextFields, which this reviewer blocks
  on (clipboard reads; #14630). Cody chose the fix: `SignInField.qml`, a
  FocusScope with a string and plain Text (the pattern accepted in #14705),
  pasting only through `bridge paste` (4 KiB, 2 s, wl-paste's group killed
  after, on overflow, timeout or cancel). Tested with fake wl-pastes;
  Cody's real sign-in still to do.
- [x] G13 Feed URLs could point mpv at the local network (#13789: the
  reviewer cleared that podcast plugin only with checks at connect time).
  Now mpv fetches through `bridge proxy`: public addresses only, the local
  network with the new `localFeeds` setting (off by default; on for Cody's
  Tailscale server), never this computer. Tested on public redirect chains
  (https) and Cody's home server (refused off, plays on).
- [x] G14 Episode and podcast UUIDs in bridge command lines are visible to
  other local accounts in /proc. **Won't fix** (Cody, 2026-11-23): only
  another account on the same computer could see them, for the tenth of a
  second a bridge call lasts, and they're the same for every Pocket Casts
  listener (no account secrets: passwords and tokens never go on a command
  line). The fix, if it's ever wanted: `call()` in Service.qml sends the
  arguments as JSON on stdin, as the password already goes.

### Release prep (go-public)

- [x] CLAUDE.md current: status, rules, platform facts, Credits
- [x] The `go-public` skill: D1 screenshots, README, reviews (phase G),
  1.0.0 public and released 2026-11-22; the install test from the public
  URL passes; the marketplace baseline has no findings.
- [x] 1.0.1 released with G12 and G13 (Cody tested sign-in and his
  home-server episodes); submitted to the marketplace, issue #15655.
- [x] The marketplace review: listed 2026-11-23 (approved-and-verified at
  ce22e65, after one finding, R1).
  - [x] R1 (Medium, 2026-11-22): a token refresh in flight could undo a
    sign-out (it saved the old session again). Fixed in 1.0.2 (ce22e65): one
    auth lock for sign-in, sign-out and token writes; writes re-read the
    session first; concurrent refreshes share one; the panel drops lists
    from an earlier session. Three tests fail on 49b51fa. Replied on the issue.
- [ ] After the listing: tag the video window `skip-taskbar` (a Hyprland
  tag), and have Transom and Latch skip windows with it (Cody's call,
  2026-11-22: not during the review). Now H5.

### H. After the listing (2026-11-23, toward 1.0.3)

- [x] H1 **A stream that broke off part way was marked played.** mpv
  (keep-open) retries a dead stream, gives up, and sits with `eof-reached`
  on where it got to, exactly as at a real end; the poll marked the episode
  played, took it off Up Next and autoplayed the next one. Reproduced with
  the fake server cutting the stream at a fifth. Now `stream_broke`: an end
  over 10 s (or 1%) before the episode's end, the show's skip-outro
  included (read back from mpv's `file-local-options/end`, so a player
  started by an older Legato is judged right too), without nearly all of
  the file read (mpv forgets the size once the stream fails, so a long
  duration estimate on a complete file still ends). Then `stream_stopped`:
  the position is pushed (it was playing here), the player closed, the
  panel and OSD say so, and Play loads it again from Pocket Casts'
  position. A Play that gets there before any poll is caught too (it used
  to replay from the top, pushing 0). Four tests fail on the old bridge.
- [x] H2 The resume check waits 5 s per request (`RESUME_CHECK_TIMEOUT`),
  not 15: unanswered, the episode plays anyway and nothing is pushed until
  Pocket Casts answers. Two hanging requests used to keep Play silent for
  up to 30 s. (Nine Point Labs' review of the same check upstream, PR #7.)
- [x] H3 A test for a stream host that accepts the connection and never
  answers (Nine Point Labs' review of PR #9; the behavior was already right).
- [ ] H4 Listening stats (B5; Cody, 2026-11-23: local only, "amusing"):
  listened time and time saved by speed, Trim Silence, skipping and the
  shows' intro/outro skips, kept in the state folder (survives disabling
  the plugin, which deletes its bar entry and with it the widget settings).
- [ ] H5 The video window tagged `skip-taskbar`; Transom and Latch skip
  tagged windows (each its own release).
- [ ] H6 Ship 1.0.3 with the `ship-update` skill (marketplace verification
  request, Cody approves the filing).

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
- 2026-11-21 (second session): Cody's lid-close test passed (D2). E6
  (drag) decided not for v1, E7 dropped. E8 fixed (right-click opens mpv's
  context_menu script). E11 transparency built: a rule can't do it on a
  floating workspace (Omarchy's tag rule forces opacity 1 and wins), the
  window's own property can; a window.open hook covers windows mpv opens
  later. The menu's check mark draws as a box, its submenu arrow draws.
  Then a fresh-eyes review (two independent reviewers, findings checked
  against the code): phase F, all fixed with tests (79 Python, 26 node).
  The worst: an episode finished here was set back to in progress, and a
  skip while paused could rewind the phone.
