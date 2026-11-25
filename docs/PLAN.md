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
- [x] B5 Optional: "time saved", as the Pocket Casts apps show it. Done as
  H4 (local only).

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
- [x] After the listing: tag the video window `skip-taskbar` (a Hyprland
  tag), and have Transom and Latch skip windows with it (Cody's call,
  2026-11-22: not during the review). Done as H5.

### H. After the listing (2026-11-23; shipped as 1.1.0)

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
- [x] H4 Listening stats (B5; Cody, 2026-11-23: local only, "amusing";
  where: a chart button in the header beside Settings and About, his
  idea). Listened time, time saved by speed, Trim Silence, skipping forward
  and the shows' intro/outro skips, and episodes finished, in `stats.json`
  in the state folder (survives disabling the plugin, which deletes its bar
  entry and with it the widget settings). Counted in the polls that already
  run while playing (rule 4 holds); a seek from a media widget is flagged
  by the service (`--seeked`) so it isn't counted as time saved. The page
  (`StatsView.qml`, `a`, IPC `stats`) reads them when it opens. Checked
  live: the page and the header button render in Cody's theme.
- [x] H5 The video window tagged `skip-taskbar` (its own runtime rule)
  while it's pinned (Always on top; Cody: unpinned, other windows can cover
  it, and without a button or Alt+Tab entry it would be lost); Transom
  (cd5ee47, plus a refresh on Hyprland's `pin` event) and Latch (586a6bb)
  leave tagged windows out unless minimized, each with tests that fail
  without the check. Checked live on a stand-in `legato-video` window.
- [x] H7 The release review (go-public's updates.md: a correctness
  reviewer on the diff since ce22e65, and a "predict the marketplace
  reviewer" pass), each finding checked against the code, each fix with a
  test that fails on the old code: a broken stream after a long gap pushed
  without asking (now the 90 s rule, else `checkServer`); with Trim on, a
  skip was counted as trimmed too (the count restarts after a seek); the
  5 s limit also cut short a poll's check on a slow link (now only a press
  of Play) and could cut a token refresh short (`prime_token` first); a
  real end without a file size and a long duration could replay forever
  (only mpv's duration; a second stop at the same spot is the end); a
  failed poll lost the seek flag; the Stats page waited on the state lock.
  Cody's home server sends Content-Range with the full size and serves MP4;
  one of his episodes, checked live, ended with all but 178 bytes read (its
  index at the front). Since round 3 an index at the back is fine too. The prediction's Low on
  G14 (UUIDs in argv) is left as decided.
- [x] H8 Media for 1.1.0 (Cody: no re-shoot, edit the button in). The
  header's Stats button was composited into media/hero.png, pages.png
  (three headers), themes.gif (six themes), social-preview.png and
  preview.png (the hero at 1400 px): the chart glyph rendered from the
  panel's own font (JetBrainsMono Nerd Font), sized so the rendered gear
  matches each image's gear (best at no offset), one button pitch to its
  left, in each theme's own ink. The GIF was rebuilt on its own palette
  (`+dither -remap`, `-layers OptimizeFrame`; `-layers Optimize` re-quantizes),
  so every pixel outside the icon is unchanged. media/stats.png was shot
  live with illustrative numbers (stats.json swapped in for the shot and
  removed after: 1 d 14 h listened, 1 d 3 h saved, 63 finished), on an
  empty workspace: a window with no_screen_share (Bitwarden) blacks out
  screenshots of its whole workspace, panels on top included. GitHub's
  social card is uploaded by hand from media/social-preview.png.
- [x] H9 Stats can be turned off and cleared (Cody: some privacy-minded
  users won't want them): prefs.json `stats` (a player choice, so "off"
  survives disabling the plugin, unlike a widget setting), the Settings
  page's Listening stats section (On/Off; Clear asks for a second click),
  `bridge stats on|off|clear`; the Stats page says when counting is off.
### SR. Strict review round 1 (2026-11-24, the strict-review skill)

Two fresh reviewers against the 2026-11-21 audit and the skill's checklist:
reports kept outside the repo. Verdict:
the sync rules and idle cost hold; a new path can mark an unfinished
episode played; the new Settings rows don't fit; the tests are weak where
it's new (mutants killed: 8 of 20 and 24 of 44).

- [x] SR1 (high) A second break within 10 s of the first counted as the end
  (`brokeAt`): on a flaky link an unfinished episode is marked played on
  every device, and (nothing to autoplay) Play then restarts it from 0:00
  and pushes 0 (SR2). Fix: drop the second-stop rule; judge a break by the
  file size and duration mpv knew when the episode loaded.
  Fixed: `brokeAt` is gone; `stream_broke` judges by `stream` (url, size,
  duration mpv knew at load). Test: a second break near the first stays a
  break, never pushes 0.
- [x] SR3 (medium) A host that sends no file size, serving an MP3 without a
  duration header: mpv's duration shrinks to what arrived, so a break reads
  as the end. Fix: use the load-time duration; with neither size nor
  duration known at load, it's the end as before 1.1 (a stated limit).
  Not fixed by this (round 2 found it still ends for a no-size MP3): see
  SR15-SR17.
- [x] SR4 (medium) Play's short check still waits a full token refresh
  (hourly), and a 401 inside it refreshes under the 5 s limit. Fix: the
  token request gets its own timeout (lowered only by the sleep guard);
  the claim says "plus a due sign-in refresh".
  Fixed: `TOKEN_TIMEOUT` (15 s; the sleep guard lowers it with
  HTTP_TIMEOUT); `prime_token` removed. Tests: an expired token and a 401
  inside the quick check both refresh in full.
- [x] SR5 (low) `--seeked` skips every plausibility check: a stall or pause
  up to 300 s counts as listening. Fix: bound that stretch.
  Fixed: `SEEKED_STRETCH_MAX` (40 s), and only a stretch that ends playing.
- [x] SR6 (low) An unexpected error in the stats code fails the whole poll.
  Fix: stats code can't raise into the poll.
  Fixed: count_listening and add_stats can't raise into a poll; a
  stats.json that isn't an object starts over.
- [x] SR7 (high) The Settings page no longer fits the panel (848 px of 728):
  the Listening stats rows fall outside the card. Fix: the switch and Clear
  move to the Stats page; a layout test caps the Settings page.
  Fixed: the switch and Clear moved to the Stats page; the Settings page is
  back to 1.0.2's (708 px in the stand-in layout). Test:
  tests/qml/pages.qml caps both pages (it fails on the 1.1.0 page: 848).
- [x] SR8 (medium) Errors from those controls are invisible (the status line
  is hidden behind a page); a failed Clear looks done; an unreadable
  stats.json leaves "…" with no reason. Fix: the Stats page shows them.
  Fixed: the Stats page shows `service.statsError`; a failed read shows its
  reason.
- [x] SR9 (low) Listening dropped around a pause whose poll lands late, and
  around every speed or Trim change. Fix: count before those changes.
  Fixed: Pause from the panel counts first; speed and Trim changes count
  around themselves (`listening_change`, half a second at most for the
  lock).
- [x] SR10 (low) The skip-taskbar tag follows Legato's setting, not the
  window's pin: Omarchy's Super+O unpins and tiles it, still hidden. Fix:
  tag by the real pin state if Hyprland's rules can match it.
  Fixed: two rules match the real pin (`pin = true` adds, `pin = false`
  removes; a pin change only adds tags by itself, tested live).
- [x] SR11 (low) The test suite's mpv joins the real session bus (MPRIS
  players on the desktop while tests run). Fix: tests load no mpv-mpris.
  Fixed: test players load no mpv-mpris (and a test checks their command
  line).
- [x] SR12 (low) The Stats page shows zeros before its first read and goes
  stale while open. Fix: "…" until read; re-read on each poll while open.
  Fixed: "…" until the first read; re-read after each poll while the page
  is open.
- [x] SR13 (round 2: the QML part wasn't really fixed until SR19) Tests that gave false confidence: the broken-stream push's
  guards (unconfirmed, checkServer) untested; "carries on" tests passed
  with nothing playing; the `--seeked` and 300 s gap tests passed without
  their code; next/switch/absolute-seek/clear-lock/trim-change counting
  untested; QML only regex-checked (7 of 10 QML mutants survived). Fix:
  behaviour tests for each, an offscreen QML test, `tests/mutations.md`.
  Fixed: tests for each, the offscreen QML test, tests/mutate.py +
  tests/mutations.md.
- [x] SR14 Stale claims: CLAUDE.md status (1.0.2, skip-taskbar next,
  "private until 1.0.0"), test times (70 s / 20 s; it's ~3 min), PLAN
  "toward 1.0.3", H2's "5 s" without the refresh caveat.
  Fixed in CLAUDE.md and this plan.

### SR, round 2 (2026-11-24)

Fresh reviewers again: reports kept outside the repo.
The push rules, lock order, idle cost and security hold. The break-vs-end
judgment still lands on "played" off the one host shape the tests used,
and the QML wiring's tests are patterns (reviewers' mutants: 6 of 12
safety, 2 of 21 fit).

- [x] SR15 (critical) A load slower than wait_for_load's 20 s stores an
  empty load record; a later break is then the end (marked played). Fix:
  polls fill the record in (and create one for a player an older Legato
  loaded), and a break is judged size first.
  Fixed: `learn_stream` fills the record from every poll (and makes one for
  an older Legato's player); the size decides first. Tests: a slow load
  with and without a poll before the break.
- [x] SR16 (high) mpv misreads an MP3's duration at load (no VBR header, a
  stitched ad: 18.4 s of 60), and the duration was checked before the size
  evidence. Fix: the size decides whenever it's known (now or earlier).
  Fixed: size first (known now, or earlier and gone). Unit cases for an
  18.4-of-60 misread.
- [x] SR17 (medium) A host with no size, serving MP3: mpv's load-time
  duration is what has arrived (1.1 s), so every break was the end. Fix:
  with the size never known, compare with the longest duration given
  (Pocket Casts', mpv's at load or now), with a 10% margin.
  Fixed: `NO_SIZE_MARGIN` against the longest duration (Pocket Casts'
  included). Test: a no-size host breaks and ends properly. README's known
  limit says what's left.
- [x] SR18 (medium) A break while Pocket Casts is unreachable: Play
  resumed from the last successful push (possibly long before). Fix:
  resume_last keeps a further local position Pocket Casts never received,
  as check_server already does.
  Fixed: resume_last keeps a further, unsent local position; Pocket Casts
  further on still wins (both tested).
- [x] SR19 (medium) QML wiring checked only by patterns (Panel, Service,
  BarWidget): e.g. `pageOpen` without the Stats page lets Delete remove a
  hidden Up Next episode. Fix: an offscreen test of the real Panel and
  Service with stand-ins.
  Fixed: tests/qml/panel.qml runs the real Panel and Service with stand-ins
  for Quickshell's processes and Omarchy's components (21 checks); the fit
  reviewer's 10 QML mutants are in tests/mutate.py and killed (BarWidget's
  IPC by pattern).
- [x] SR20 (low) Untested edges: the speed match, skips counted by how far
  playback moved, the 0.5 s lock cap, the fresh count after a change, the
  1% slack's upper side, Play's end check reading the end properties.
  Fixed: a test for each (and a pin assertion the new tag rules had made
  meaningless, found by mutation).
- [x] SR21 (low) `statsPageOpen` is one flag for every panel (two screens);
  playback errors aren't visible while a page is open.
  Fixed: panels count their Stats and other pages on the service
  (`statsPagesOpen`, `pagesOpen`), and errors go to the OSD while a page is
  open.
- [x] SR22 Claims: the README's limit (it isn't only hosts sending
  neither), "Transom, for one" (its tag support isn't released yet), What
  it changes (stats.json, the tag rules), stale "Settings page" comments,
  "5 s per request" (10 at most), the suite's time, PLAN SR3/SR13/H1;
  media/stats.png predates the switch and Clear. tests/mutate.py checks
  no baseline and doesn't name the killing test.
  Fixed, except media/stats.png (needs a re-shot of the Stats page, with
  Cody's OK to use an empty workspace). tests/mutate.py checks a green
  baseline per test set and names the killing test.

### SR, round 3 (2026-11-24)

reports kept outside the repo. Breaks no
longer mark episodes played on any host shape tried, and the sync rules,
locks, cost and security hold. But the judgment now errs the other way on
real files, and an old no-ranges path rewinds other devices.

- [x] SR23 (high) An M4A with its index (moov) after the audio, FFmpeg's
  default, never finished: `stream-pos` stops before the index, so "much
  unread". Play then restarted it at 0:00 and pushed 0. Fix: with the size
  still known (the stream didn't fail), much unread is a break only if
  mpv's own duration also says the stop is short of the end.
  Fixed: still sized, much unread is a break only if mpv's own duration
  agrees. Test: a 10-minute M4A written without faststart, played to its
  end, is marked played.
- [x] SR24 (high) A skip-outro show whose file is a little shorter than
  Pocket Casts lists looped at the end: only durations decided, against
  the listed one. Fix: the same (mpv's own durations when the size is
  known); a no-size host shorter than listed stays a stated limit.
  Fixed the same way. Test: a 120 s file listed as 132 s with a 20 s outro
  skip ends properly.
- [x] SR25 (high) A host without byte ranges: mpv can't start part way, so
  a resume played from 0:00 and the next poll pushed that over Pocket
  Casts' further position, on every device (old code; the break's "press
  play" leads into it). Fix: a load that couldn't start where asked sets a
  floor; nothing below it is pushed until playback passes it.
  Fixed: `stream.asked` and `below_start` guard the poll's push, sync_now
  and the break's push until playback passes the start or you seek; the
  panel says so once. Tests: no push below the start, a seek of yours syncs
  again, the break's own push.
- [x] SR26 (medium) resume_last kept an unsent local position with no age
  limit. Fix: only one a break's failed push left, within an hour.
  Fixed: `unsentBreak`, kept for `UNSENT_BREAK_KEPT` (an hour); Pocket
  Casts further on wins. Tests for both, and for rule 2 when Pocket Casts
  is behind (the phone rewound on purpose).
- [x] SR27 (low) resume_loaded's break check didn't make sure mpv plays the
  recorded episode. Fix: it checks, as the poll does.
  Fixed and tested.
- [x] SR28 (low) A reload that plays nothing (the same stop again) gave the
  same message forever. Fix: it says nothing more arrives, and how to mark
  the episode played; nothing is marked by itself.
  Fixed: `nothingMore` and its message (right-click in Up Next marks it
  played). Test.
- [x] SR29 (low) Stats: a read answering after Off or Clear put the old
  state back; one more fsynced write per poll; the broken-stream message
  cut off in the status line; the README's cost line.
  Fixed: reads issued before a change answer into nothing; stats.json
  written without fsync; the message shortened; the README's cost line.
- [x] SR30 Tests: QML behaviour instead of patterns for the Stats button,
  `a` closing, About over Stats, page counts (a panel going away), error
  clearing, the seek flag's reset, re-reads only for the Stats page, the
  optimistic switch, each row's value, Episodes finished; bridge bounds
  (no-Trim upper, stall slack), `since`, the count before a seek; rule 2
  when Pocket Casts is behind (the phone rewound on purpose); hyprctl
  stubbed for every player test; a duplicate mutant; M4A and skip-outro
  media in the end tests. Claims: CLAUDE.md's stream-pos fact, "Play loads
  from Pocket Casts' position", "durations aren't trusted alone", "10 s at
  most"; README's limits.
  Fixed: tests/qml/panel.qml has 37 checks (the shapes above); bridge tests
  for each; hyprctl stubbed for every player test; the duplicate mutant
  removed. tests/mutate.py now 113 mutations.

### SR, round 4 (2026-11-24)

reports kept outside the repo. Rules 2
and 3, the push guards, the sign-in race, lock order, stats isolation and
security hold. The break-vs-end judgment fails again, on new shapes, and
four rounds have each found critical or high ones there: inferring "the
stream broke" from mpv's numbers (size, position, durations) doesn't
converge: the judgment now needs positive evidence (below).

- [x] SR31 (critical; completed by SR40) A host that answers mpv's reconnect with an error page
  with a Content-Length (503, 403, 416): mpv reports the page's length as
  the size, "read to its end", marked played (the ordinary host shape).
  Fixed by the evidence approach (above): bin/legato-watch.lua and the new
  stream_broke. Tests: 503 and 403 breaks end to end, the watcher's own Lua
  (lua5.1, as mpv's), the judgment's unit cases.
- [x] SR32 (high) A sized host without ranges keeps the size after a break;
  a misread MP3 duration (ad-stitched, no VBR header) then says "end".
  Fixed the same way (FFmpeg logs the short end there too). Test: the
  reviewer's ad-stitched MP3 on a sized host without ranges, trickled, cut
  at 3/4; and the same file played to its end is still the end.
- [x] SR33 (high, also in 1.0.2) Skip-outro against a misread duration:
  mpv stopped at 0:00, marked played; autoplay emptied the show's Up Next.
  Fixed: `outro_applies` sets the outro just after the load only when mpv's
  duration is within NO_SIZE_MARGIN of Pocket Casts' (or longer). Test: the
  misread MP3 on a skip-outro show plays on, outro off; the existing outro
  test still ends at the outro.
- [x] SR34 (high) A break past Pocket Casts' listed length, then Play:
  start_position's "at the end means from the top" pushes 0 everywhere.
  Fixed: start_position no longer turns an in-progress position at or past
  the listed length into 0 (it also fired after Stop or the idle unload,
  since 1.0). An episode at its real end ends at once and is marked played.
  Test: the reviewer's 40 s file listed as 30, broken at 34: Play carries
  on past 30, nothing below 24 pushed.
- [x] SR35 (high, rare) The start floor is lifted by any seek of yours,
  even one a host without ranges can't make: dragging back pushed 0:01.
  (The test asserting that rewind as intended is wrong.)
  Fixed: a seek lifts the floor only if mpv was at or past the start before
  it. The resume check's seek ahead now sets the floor too (the safety
  reviewer's F5). Tests on a trickling host without ranges: a drag and a
  skip, and the resume check's seek; both pushed 0:03 before. A seek back
  from an honoured start still syncs (test).
- [x] SR36 (medium) The three new messages don't fit the OSD (325 px) or
  the status line (about 300 px): the advice is cut off.
  Fixed: the four playback messages cut to 38 characters or fewer ("Stream
  dropped. Press play to resume.", "Nothing more arrives. Mark it played?",
  "Server can't resume: playing from top", "Player stopped responding.
  Press play."); the detail is in the README. Test: panel.qml checks each
  message's length as the service says it.
- [x] SR37 (medium, tests) tests/qml/panel.qml answers `status` with {},
  which signs its service out, so "keys behind the Stats page" can't fail.
  Fixed: settle() answers status signed in and Up Next with an episode, by
  command (a reload started inside an answer got the empty answer); a
  control check that Delete on the main view does remove; n, m and Delete
  behind the page. Removing either page guard now fails it (checked).
- [x] SR38 (low) "Nothing more arrives" after any seek back; a resume
  check's seek does nothing on a host without ranges; stale On/Off and
  Clear answers; several Stats-page and bridge survivors (the reports).
  Fixed: nothing-more only within 0 to 2 s of the load's start and never
  after a seek; the resume check's seek floor (SR35); stale On/Off, Clear
  and poll answers, the switch's default, the off-and-empty text, `since`
  through the stats command, the intro not counted mid-episode, a
  successful break push then a rewind on the phone, Play's second request
  held to the short limit: tests for each (the code was right for most).
  Also the sleep guard no longer refreshes the sign-in (REFRESH_ALLOWED)
  and the call's deadline waits while a refresh is stored (deadline_held;
  per-thread signal blocking didn't hold with the cover threads). The
  tests' encode() uses a private folder.
- [x] SR39 (low, pre-existing) Each o.window call appends a duplicate to
  Omarchy's floating-app list.
  Fixed: the rule goes through o.window only while Omarchy's list lacks the
  class. Test: the rule's Lua run three times against Omarchy's real
  helpers.lua (lua5.4, a stand-in hl): one entry (three before).

Approach (chosen 2026-11-24 on a probe's evidence; Cody can still say
otherwise): judge a break by positive evidence. Probe (mpv 0.41, its log
from start, the suite's fake host): every break on a host that gives a size
logs FFmpeg's `http: Stream ends prematurely at N, should be M` (reconnect
accepted then closed; reconnect answered 503; a sized host without ranges);
real ends (MP3, M4A with its index at the back, an ad-stitched MP3) log
nothing; a host that gives no size logs it at every end with M =
18446744073709551615 (unknown), so there the duration rule stays. A small
mpv script (`bin/legato-watch.lua`) records the line per file in
`user-data/legato`; the bridge reads it at the end. The service's socket
can't do it: the break happens as the cache fills, often before it attaches.
Also: no "at the end means from the top" for an episode in progress (SR34),
the skip-outro only when mpv's duration agrees with Pocket Casts' (SR33),
a seek lifts the floor only if the start was honoured (SR35).

### SR, round 5 (2026-11-24)

reports kept outside the repo. Both
reviewers found the same critical, which round 4's probe missed because it
only ever used the suite's plain-http fake.

- [x] SR40 (critical) An https stream dropped without TLS's close_notify (a
  network, a CDN edge going), or a link gone silent, never logs FFmpeg's
  short-end line, so the watcher saw nothing and the break was the end:
  marked played, the next one started. Fixed: the watcher also records
  "Will reconnect at N", which every break shape tried logs and no real
  end does (probed: five break shapes and seven real ends over http and
  https). Tests: HttpsStreams (the fake host behind TLS, mpv verifying it
  with --tls-ca-file: a drop, a 503, a stall then close, a real end, an
  M4A with its index at the back, Play after a break never pushes 0) and
  StalledStream (http, a read timeout).
- [x] SR41 (high, since 1.0) A stalled stream pushed its stuck position every
  30 s over the phone you carried on with, and kept the last push fresh so
  the gap check never asked; over https mpv's network timeout doesn't
  apply inside the tunnel, so the stall had no limit. Fixed: no periodic
  push while buffering or of an unmoved position; feed connections keep
  TCP keepalive (a dead path fails within about a minute). A server alive
  but silent still stalls, pushing nothing (README). Test: a stalled https
  stream never rewinds the phone; keepalive set on feed sockets.
- [x] SR42 (low) The sleep guard waited up to 40 s for the auth lock before
  learning it may not refresh, with no overall deadline: its push could go
  out after a sleep. Fixed: access_token refuses before the lock;
  SLEEP_GUARD_DEADLINE (10 s) for the whole pause and push. Tests.
- [x] SR43 (low) A group-writable plugin folder silently disables the
  watcher (the length rule then decides): documented in CLAUDE.md, tested.
- [x] SR44 (low) The long-gap break's `checkServer` was dead (Play goes
  through resume_last anyway): removed; the test asserts the behaviour
  (Play follows the phone).
- [x] SR45 (low) Skip-outro off when Pocket Casts lists no duration:
  documented (README) and tested.
- [ ] SR46 (low) media/stats.png predates the Stats page's On/Off and Clear:
  re-shoot on an empty workspace, with Cody's OK (Bitwarden on workspace 1
  blacks out captures).
- [x] SR47 (nits) "Stream ends here. Mark it played?"; the suite's time;
  the README's what's-new list; history out of stream_broke's docstring.
  Left as they are: video_rule_lua's long docstring (it records live-tested
  Hyprland behaviour the code depends on); http_timeout's global and
  listening_change's manual lock (work, tested); the untag rule would
  also untag a user's own tag on Legato's window class (harmless).
- [x] SR48 (tests) The reviewers' surviving mutants: sync_now's not-yet-
  checked guard (a media-key resume then Stop), resume_last's finished
  check, mark_needs_reauth's same-session check, the Stats page's Back,
  Settings giving way to Stats, fmtDay's local day (exact now), the
  watcher's ownership check, the outro without a listed length: tests
  for each.

### SR, round 6 (2026-11-24)

reports kept outside the repo. Both found
the same critical on a host class round 5's TLS host never was: one that
sends a size but no byte ranges.

- [x] SR49 (critical) On a host without ranges, an https drop or a silent
  link (http or https) was the end: FFmpeg never reconnects an unseekable
  stream (no "Will reconnect"), and only a clean close logs the short-end
  line. Fixed: such a stream (mpv's `seekable` false) is read straight
  through, so it's the end only if mpv read to its size (READ_TO_END);
  probed: breaks stop 96 KB short, real ends about 100 bytes short (MP3,
  M4A, ad-stitched), and an M4A with its index at the back can't play
  there at all (now a break, not "played"). TLS error lines rejected as
  evidence: an https host without a size logs them at its real end too.
  Tests: HttpsStreams (no ranges: a drop, a stall, a real end, the M4A),
  StalledStream (plain http, no ranges, silent).
- [x] SR50 (high, since 1.0) A stalled stream's stuck position was still
  pushed by pause, stop, next, a switch, the sleep guard and the break,
  and check_server refreshed the last push during a stall. Fixed: a stall
  of STALL_AFTER (15 s) or more is an interruption (the watcher times
  mpv's buffering): nothing pushed during it or by those, and playing on
  after it asks Pocket Casts first. Tests: pause and stop during a stall,
  a stall that heals (follows the phone), a break after a long stall.
- [x] SR51 (high, since 1.0) Omarchy's shell refuses a third-party plugin's
  OSD summon, so every closed-panel error (rule 8) was dropped. Fixed:
  desktop notifications (`bridge notify`, notify-send, the text one
  argument after `--`); Cody may prefer `omarchy-osd` (a public command,
  but it sidesteps the shell's choice). Tests: the panel test checks the
  notify call (its stand-in shell had accepted any summon).
- [x] SR52 (medium, since 1.0) About with its license open was 113 px taller
  than the panel. Fixed: the license takes the privacy text's place. Test.
- [x] SR53 (low) A reconnect that worked near the end judged a break: the
  end counts when mpv read to the size. Test (and one further in).
- [x] SR54 (low, since 1.0) The sleep guard waited 2 s for the state lock
  before pausing: now it pauses first. Test (the lock held).
- [x] SR55 (low) Each panel's idle fallback Service registered the `legato`
  IPC target too (the shell logged it at every start; first wins): now
  made only without a shared service, and not before the bar has handed
  itself over (BarWidget sets it just after loading the panel: a first
  fix still made the copy in that moment; checked live, the warning is
  gone and the shell's service answers). Tests for both orders.
- [x] SR56 (low) A page opened over an open right-click menu (a, i, g):
  closes it now. The nothing-more message as a statement; "counting
  starts as you listen" after Clear; README and CLAUDE.md (helpers in
  rule 4 and Resources, the tag's wording, the stats switch's page, stale
  comments). Test for the menu.
- [x] SR57 (tests) The reviewers' survivors: keepalive's interval and count,
  the sleep deadline under logind's 15 s, add_stats' guard, off writing
  nothing, the since-date line, stats in the privacy text, a healing
  reconnect. Left: the previous file's late log line can reach the next
  file (errs toward a break, recoverable).

### SR, round 7 (2026-11-24)

reports kept outside the repo. The fit
reviewer found nothing critical or high; the safety reviewer three highs.

- [x] SR58 (high, since 1.0) A forced push (a pause or skip while playing,
  the sleep guard) ignored both "not yet checked" and the 90 s gap: a
  media-key resume then a panel Pause, or a Pause after an unguarded sleep,
  pushed the old place over the phone's. The pause set checkServer before
  its own push. Fixed: forced pushes need a confirmed, recent stretch;
  checkServer is set after the push. Tests (pause, skip).
- [x] SR59 (high) A pause after a stall healed: the poll it brought fell
  through to the paused push (SR50's test never ran that poll). Fixed: a
  long stall marks the position `unconfirmed` until Pocket Casts answers.
  Tests (the pause's poll, a pause after the heal, pushes resuming after
  the check).
- [x] SR60 (high, rare) An HLS episode whose segments stop was marked
  played. Fixed: HLS (mpv's `file-format`) goes by the length rule (its
  playlist is exact). Tests (segments stop; a real end).
- [x] SR61 (medium; SR34 widened it) Pocket Casts' position past the end of
  this machine's copy (ad-stitched copies differ): ended at once, marked
  played. Also a placeholder clip far short of the listed length (low).
  Fixed: `end_unproven` (nothing played since the load, or under half the
  listed length): "Stream ends here: mark it played." Tests.
- [x] SR62 (medium) Pushes failing mid-episode (Pocket Casts down, the
  session expired) were never said. Fixed: two in a row are said once
  ("Pocket Casts not reached: not synced"). Test.
- [ ] SR63 (medium, since 1.0; fit) On a bar that replaces Omarchy's, the
  facade has no service lookup: the panel's fallback and the shell's own
  service both run (polls twice, two sleep guards, two IPC handlers,
  errors notified twice). Documented in README Known limits. Plan: the
  shell's service does nothing until a panel claims it, and the IPC
  handler is made only by the instance in use.
- [x] SR64 (low) The watcher kept only the latest stall: a hiccup after a
  long stall hid it. Fixed: the last eight. Unit test.
- [x] SR65 (low) A host with ranges and no size logged a reconnect at real
  ends: no episode finished. Fixed: no size, the length rule decides.
- [x] SR66 (low) check_server kept an unsent local position for ever: now
  within the hour (UNSENT_BREAK_KEPT). Tests both ways (the "within" side
  was a surviving mutant).
- [x] SR67 (low, left) Signing out doesn't stop a poll already running; a
  panel Pause can answer "busy" behind a slow poll. Both read-only
  findings, recoverable.
- [x] SR68 (low; fit) Keepalive's 20 s probes in README Resources; stale
  Service comments; the keyboard claim narrowed (the pages take the mouse);
  small screens in Known limits; round 6's dates. SR46 (the screenshot)
  still open.
- [x] SR69 (tests) Rule 4 and rule 8 run in the panel test (the timers and
  a closed panel's notification), a healed stall that syncs again, test
  players ended by their socket even when the bridge can't reach them.

### SR, round 8 (2026-11-24)

reports kept outside the repo. Fit found
nothing critical or high again; safety a critical and a high. Plus Cody's
ask (a side note): the watcher keys on FFmpeg's wording, and an update
could silently undo the fix.

- [x] SR70 (Cody) The FFmpeg self-check: once per FFmpeg version
  (`ffmpeg-version`), a detached `bridge watchcheck` serves a short silent
  WAV from 127.0.0.1 and drops it, plays it in a private muted mpv with
  the watcher, and needs both lines (`seen`). Failed: ranged hosts go by
  length for that version, and one notification says so. Tests: passes
  with this FFmpeg (n9.0.2); a reworded watcher (as if FFmpeg reworded)
  fails loudly; the verdict's use; once per version; triggered by a new
  player.
- [x] SR71 (critical) A failed seek was the end: on a ranged host a seek
  outside the cache needs a new request, and when it's refused (offline,
  the host down, an expired link: the proxy answers a failed connect with
  403) FFmpeg logs only "HTTP error 403". Fixed: the watcher records any
  other warning or error from FFmpeg's network layers since the last seek
  (`failed`); with it, a break unless mpv read to the size. Tests (skip
  back after the link expired; the resume check's seek with the host down).
- [x] SR72 (high) An empty episode lookup (404, empty 200, redirect) was
  taken as Pocket Casts' answer: the stale local place confirmed and
  pushed; a reload started from the public list at 0. Fixed: for an
  episode Pocket Casts knew (`recordSeen`), an empty lookup is no answer
  (unverified; a reload refuses with "Pocket Casts didn't answer: try
  again"). Shows never followed keep the old path. Tests for all three.
- [x] SR73 (medium) Skip-outro on a host without ranges never finished: the
  outro's stop counts as the end there. Test.
- [x] SR74 (low) Play at a real end no poll had handled played it again
  from 0 (pushing 0): it finishes it now; the next Play plays it again.
  A drag back after an end pushed it as in progress: sync_now leaves it.
  Tests (the old Play-at-the-end test updated).
- [x] SR75 (low) "Stream ends here: mark it played" after a link that went a
  second after a resume: now only at the same spot twice in a row
  (`breakStrike`). Test.
- [x] SR76 (low-medium, fit) "Pocket Casts not reached" was said on every
  poll between pushes, not once: now in the poll whose push made it two.
  Test (polls that don't push in between; the count reset by a push that
  works).
- [x] SR77 (tests, fit) A failed stats switch or Clear on the page;
  duration boundaries; the privacy check's wording; notify through the
  argument parser (the text after `--`); resume_last's atTop check.
- [x] SR78 (low, left) Tag rules gone after a Hyprland config reload until
  Legato sends them again (README says the rules live until a reload);
  plain IpcHandler, not Omarchy's ShellIpc (a keybind's call goes through
  `qs ipc`, ~45 ms); an unreadable prefs.json counts stats again; the
  Stats page's own switch and confirm instead of Omarchy's components.

### SR, round 9 (2026-11-24)

reports kept outside the repo. Safety:
about 15 host shapes built against real mpv and FFmpeg, none taken for the
end; the break judgment holds. A high in empty lookups (SR72 was partial)
and a high in the self-check's player.

- [x] SR79 (high) An empty episode lookup still rewound devices on paths SR72
  missed (Play from a list, following the phone to another episode, an
  episode started by autoplay or Next): `recordSeen` was set only for
  episodes loaded from a record. Fixed: for a show you follow, Pocket
  Casts has a record of every episode (checked live on Cody's account:
  unplayed and the oldest of 1906 alike), so an empty lookup is no answer
  everywhere (`record_expected`; `resolve_episode` refuses, check_server
  says unverified). Shows not followed keep the public list (now tested).
- [x] SR80 (high, fit) The self-check's mpv lacked the player's hardening:
  it could read the clipboard at start-up through Wayland (the README says
  nothing does). Fixed: `--ytdl=no --clipboard-backends-clr`, no
  `WAYLAND_DISPLAY`; the test suite's homes drop the display too.
- [x] SR81 (medium) The self-check needed the exact two lines, so a harmless
  rewording would have switched every ranged host to the length rule for
  that version, and it didn't test the `failed` channel at all. Fixed:
  the probe's reconnects get a 403 (the third channel); any channel
  passes; nothing heard fails. Keyed on mpv's and FFmpeg's versions; a
  check that never finished counts as failed after ten minutes; a failure
  is retried a day later. Tests (two lines reworded pass, no log events
  fail, two players check once).
- [x] SR82 (medium) A drop that recovered left `failed` set until a seek: an
  M4A with its index at the back never finished. Fixed: a reconnect or
  short-end line takes over from it. Lua test; an end-to-end guard.
- [x] SR83 (low-medium) A self-check stopped by a signal left its player
  and folder: its mpv now dies with it, and SIGTERM cleans up.
- [x] SR84 (low) The periodic push ignored `unconfirmed`; a stall's stuck
  place beat a rewind on the phone (`stalledPlace`); notification text is
  escaped (bodies are markup, links clickable); systemd-inhibit ends with
  the shell (the guard survived restarts, since 1.0); the default About
  page's height (the privacy sentence shortened, a layout check); `a` and
  `g` close an open menu (tested); keepalive bounded both ways; install
  ships every QML and JS file (checked from its list); the QML tests don't
  need the desktop's theme.
- [x] SR85 (low, left) A host without ranges can't seek back to where the
  phone rewound past mpv's buffer (README); on two screens the plugin-id
  IPC handler registers per bar (first wins, works); a replacement bar
  runs a copy per panel (README).
- [ ] SR86 (medium, since 1.0; after 1.1.0) Widget settings live only in the
  bar entry, which Omarchy deletes when the plugin is disabled or its chip
  dragged off: move them to the plugin's own file (the omarchy-plugin
  skill's pattern). README says so meanwhile.

- [ ] H6 Ship 1.1.0 (a minor version: the stats are a feature) with the `ship-update` skill (marketplace verification
  request, Cody approves the filing).

## Testing

- `tests/run` before every commit: all suites, about 13 minutes, nothing on
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

- 2026-11-24: strict review rounds 1 and 2 (phase SR). Round 2's critical
  (a slow load left no record, and a break was marked played) and high (a
  misread MP3 duration checked before the size) fixed with the break
  judged size first and towards a break when unsure; QML now tested with
  the real Panel and Service offscreen. 157 Python + 36 node tests; the
  mutation set (tests/mutate.py) 84 of 84 killed. Round 3 next.
- 2026-11-24 (later): round 3 (SR23-SR30): an M4A with its index at the
  back and a skip-outro show listed longer than its file now end properly
  (a still-sized stream judged by mpv's own duration); a host without byte
  ranges no longer rewinds other devices (the start floor); the unsent
  position kept an hour only. 171 Python + 36 node tests; 113 of 113
  mutants killed. Round 4 next.
- 2026-11-24 (evening): round 4 (SR31-SR39) found the break-vs-end
  judgment fooled again (an error page's length, a host without ranges, a
  misread MP3 with a skip-outro) and a rewind to 0 after a break past the
  listed length. A probe of mpv's log showed FFmpeg reports every break of
  a sized stream and nothing at real ends, so the judgment now rests on
  that (bin/legato-watch.lua). Messages fit the OSD; the panel test runs
  signed in; the sleep guard never refreshes the sign-in. 188 Python + 36
  node tests; 137 of 137 mutants killed. Round 5 next.
- 2026-11-24 (night): round 5 (SR40-SR48): https drops and silent links
  logged no short-end line, so were taken for the end; the watcher now
  also records FFmpeg's reconnects. A stalled stream no longer pushes its
  stall; feed connections keep TCP keepalive; the sleep guard has a
  deadline and never waits for the auth lock. The fake host now serves
  over TLS and can stall. 204 Python + 36 node tests; 150 of 150 mutants
  killed. Round 6 next.
- 2026-11-24 (night): round 6 (SR49-SR57): hosts without ranges judged
  by reading to the size; a stall of 15 s is an interruption, like a
  pause; errors go out as notifications (Omarchy's OSD never took them);
  About fits with its license open; one service per shell answers IPC.
  218 Python + 36 node tests; 163 of 163 mutants killed. Round 7 next.
- 2026-11-24 (late): round 7 (SR58-SR69): forced pushes need a confirmed,
  recent stretch; a long stall leaves the position unconfirmed; HLS by
  length; ends that prove nothing aren't marked played; failing pushes
  said. Fit found no critical or high (a replacement bar's two services
  left documented). 230 Python + 36 node tests; 179 of 179 mutants
  killed. Round 8 next.
- 2026-11-24 (late): round 8 (SR70-SR78): the FFmpeg self-check (Cody's
  ask); any network error since a seek is evidence (a failed seek was the
  end); an empty lookup for a known episode is no answer; the outro stop
  on hosts without ranges; Play at an unhandled end finishes it. 247
  Python + 36 node tests; 200 of 200 mutants killed. Round 9 next.
- 2026-11-24 (late): round 9 (SR79-SR86): empty lookups for followed
  shows are no answer on every path; the self-check hardened and checking
  "caught at all"; recovered drops clear `failed`. The break judgment held
  against every shape the safety reviewer built. Round 10 next.

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
