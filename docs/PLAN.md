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
  network with the new `localFeeds` setting (off by default), never this
  computer. Tested on public redirect chains (https) and a server on the
  local network (refused off, plays on).
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
  tag), and have Transom and the window switcher skip windows with it (Cody's call,
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
  (cd5ee47, plus a refresh on Hyprland's `pin` event) and the window switcher
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
  A media server on the local network, checked live, sends Content-Range
  with the full size and serves MP4; one of its episodes ended with all but 178 bytes read (its
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
Round 1's reports (kept outside the repo). Verdict:
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

Fresh reviewers again (round 2's reports are kept outside the repo).
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

Round 3's reports (kept outside the repo). Breaks no
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

Round 4's reports (kept outside the repo). Rules 2
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

Round 5's reports (kept outside the repo). Both
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
- [x] SR46 (low; moved: open under "Before round 10") media/stats.png predates the Stats page's On/Off and Clear:
  re-shoot on an empty workspace (Cody approved 2026-11-24, with
  representative numbers staged; Bitwarden on workspace 1 blacks out
  captures). Tracked again under "Before round 10".
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

Round 6's reports (kept outside the repo). Both found
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

Round 7's reports (kept outside the repo). The fit
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
- [x] SR63 (medium, since 1.0; fit; done before round 10) On a bar that replaces Omarchy's, the
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

Round 8's reports (kept outside the repo). Fit found
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

Round 9's reports (kept outside the repo). Safety:
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
- [x] SR86 (medium, since 1.0) Widget settings live only in the bar entry,
  which Omarchy deletes when the plugin is disabled or its chip dragged
  off. Folded into 1.1.0 (below).

### Before round 10 (2026-11-24, Cody's calls)

Cody: front-load every code change, then re-review; the loop runs past
round 10 while rounds keep finding critical or high issues. Decided:
errors as desktop notifications stay (no `omarchy-osd`); Nine Point Labs'
PRs #7-9 stay offered, nothing more is ported back; the stats screenshot
is re-shot with representative numbers (SR46); the marketplace
verification request is the very last step.

- [x] SR86 Settings in Legato's own file: `settings.json` in the state
  folder, written only by the bridge (`settings set`, checked against
  manifest.json's schema, re-read under `settings.lock`, unknown keys kept;
  `settings import` copies a 1.0 bar entry once, when there's no file yet,
  only after the bar has handed the panel its entry). A file that can't be
  read whole is never saved over: the Settings page says so (one
  notification with the panel closed), and autoplay and the idle unload
  stay off until it's fixed or deleted (also until the settings are first
  read). The chip, the panel and the service read the service's copy;
  nothing writes shell.json. Only the settings half of the omarchy-plugin
  skill applies (the widget is the product, Cody). Tests: SettingsFile
  (bridge), tests/qml/service.qml (import once, after the hand-over;
  changes, a stale read, a failed save rolled back; a broken file said
  once), node (no bare `setting(` reads of the bar entry).
- [x] SR63 One live service on any bar: the shell's copy starts dormant
  and wakes when a panel claims it; a replacement bar's panel (which can't
  see it) runs its own, and the shell's stays dormant. The `legato` IPC
  handler sits in a Loader, made only by the live copy (a disabled
  handler still registers). Left, in README Known limits: a replacement
  bar with the chip on two screens runs a copy per screen. Tests:
  tests/qml/service.qml (dormant, claimed, the replacement bar's own copy,
  IPC only on the live one).

### SR, round 10 (2026-11-24)

Round 10's reports (kept outside the repo) (the fit
report saved by the coordinating session: its reviewer couldn't write
files). Safety: one high and five mediums, each verified by running; fit:
nothing critical or high, one medium that hits every updating user. Each
confirmed against the code before fixing.

- [x] SR87 (high, since 1.0) A position from another file was pushed as the
  loaded episode's: `sync_now` (pause, stop, next, seeks, the sleep guard,
  the idle unload) never checked that mpv played the file playback.json
  names. A play cut off after `loadfile` (the deadline, a slow cover) or
  another program opening a file through mpv-mpris rewound every device.
  Fixed: only the recorded file's position is pushed (and seeked, in the
  resume check); the cover is fetched after the new episode is recorded.
  Tests (another file loaded into mpv; a play cut off at the cover).
- [x] SR88 (medium) After a resume Pocket Casts couldn't confirm, its later
  answer lost to the unconfirmed stretch (`keep_local` took it for an
  unsent push): a rewind on the phone was undone. Fixed: never kept while
  `unconfirmed`. Test.
- [x] SR89 (medium) Next and autoplay took the start from Up Next's sync
  data, so a reply without it started at 0 and pushed 0. Fixed: the record
  decides when the sync entry is missing (and refuses an empty lookup).
  The fake can leave sync data out now (`noSync`). Test.
- [x] SR90 (medium) An episode of a show you don't follow has a record once
  anyone played it (Legato's own push makes one): one empty lookup started
  it at 0 and pushed 0. Fixed: an empty lookup is no answer when Up Next's
  sync data or In Progress lists a place (`position_known_elsewhere`, in
  `resolve_episode` and the resume check; can't tell: no answer). The fake
  creates records on a push and lists only episodes in progress. Tests.
- [x] SR91 (medium) Switching to a replacement bar at run time left the
  shell's copy awake beside the bar's own, each on its own settings.
  Fixed: panels claim and release the shell's copy; the last one gone
  leaves it dormant (after 3 s), and waking it reads the player. And the
  bridge acts on settings.json itself for autoplay, the idle unload's
  "never" and the sleep guard's pause (`setting_now`), so no copy (two
  screens on a replacement bar, a hand edit) acts against the file; the
  rest drift until a status read (README). Tests (QML and bridge).
- [x] SR92 (medium, tests) The claim path Omarchy really takes (the bar
  handed over after the panel loads, `onSharedServiceChanged`) was
  untested; its removal left Legato dead and survived. Tests: chip.qml
  (the real BarWidget, the bar handed over after loading) and service.qml.
- [x] SR93 (low; fit M3) A deleted settings.json was filled again from the
  1.0 bar entry. Fixed: the import is remembered (prefs.json
  `settingsImported`) and tried once per service. Tests.
- [x] SR94 (low) A mistyped `autoplay` or `unloadAfterMinutes` turned them
  on, silently; an unknown key was silent. Fixed: off (`SETTINGS_SAFE`),
  any problem said (notification while closed), again if it comes back,
  unknown keys named and kept. Tests.
- [x] SR95 (low) A bridge call that failed to start (Quickshell sends no
  `exited`) left the poll stuck for the shell's life. Fixed: a start
  watchdog per call. The stand-in can fail starts now. Test.
- [x] SR96 (medium; fit M1) `keepLoaded` (from the original) kept the old
  service through `omarchy plugin update` under the new panel: Settings
  and Stats threw until a shell restart. Dropped; and since Omarchy
  decides what to keep from the manifest it had (`reloadPlugins`), the
  1.0 to 1.1 update still keeps 1.0's service once (the side agent's
  catch, confirmed in shell.qml): the panel checks `apiVersion`, says
  "restart the shell to finish", feeds it the bar entry the 1.0 way and
  leaves Settings and Stats alone. Tests against 1.0.2's real Service.qml
  (tests/qml/v1_0). Release notes and README say to restart once; the
  release test updates from 1.0.2 without a restart (H6).
- [x] SR97 (low-medium; fit M2) The Settings page overflowed with its path
  and a problem. Fixed: the pages scroll (`PageFlick`; the small-screen
  limit is gone too). Test.
- [x] SR98 (low; fit L2) The sleep guard's sender match was untested. Test.
- [x] SR99 (low; fit L3) Cost claims were 1.0 figures. Reworded (0.1 to
  0.2 s of CPU per call, helpers about 40 MB). Left for later: a small
  launcher importing the bridge as a module (cached bytecode) would
  roughly halve the per-call CPU.
- [x] SR100 (low; fit L4) The chip taken off (or the plugin disabled)
  mid-episode leaves mpv playing, unsynced (since 1.0): README Known limits
  (claims now make plugins[] installs behave the same before and after a
  restart).
- [x] SR101 (low; fit L5) A problem that came back wasn't said again (fixed);
  a symlinked settings.json is refused like every state file (README).
- [x] SR102 (claims) install.sh "hot-reloads", "QML stays cached", "runs
  nothing on a timer" while paused, "80 ms", "two small helpers", the
  760 px limit, the self-check's "both lines", stale comments (Service,
  Panel, About.js, a node test's name), notify-send and the runtime files
  in the README; `lexists_at` (dead) removed.
- [x] SR103 (tests) The reviewers' survivors: the fit reviewer's 16 (chip
  clicks, wheel and title; the idle unload's minutes; pauseOnSleep; skip
  lengths; the guard's back-off; socket retries; stale status reads; Esc
  on Settings; the swipe guard, static; the Settings rows; status
  `running`; the buffer; the show-list cache; the sender) and the safety
  reviewer's claim path; round 9's four survivors (followed-show guards
  masking `recordSeen`, a seek clearing the cut, unescaped notifications)
  and its reviewer's `recordSeen` mutant; the drag-back test's race with
  mpv's end pause. The FileView stand-in reads files; a script error in
  Legato's QML fails the run; mutate.py counts a stale pattern as a
  failure (twelve were).

### SR, round 11 (2026-11-24)

Round 11's reports (kept outside the repo). Safety:
one high, three mediums, each verified against the fake server.

- [x] SR104 (high) Play at the end of a file playback.json doesn't name
  (another program's OpenUri; a play cut off by the deadline inside the
  load) pushed the recorded episode at 0; a drag back on it reopened the
  recorded episode at the other file's place. SR87 had covered only
  `sync_now`. Fixed: Play on a stray file starts over through Pocket Casts
  (`resume_last`), a drag back reopens only the recorded file, and a play
  holds the deadline from `loadfile` until the new episode is recorded.
  Tests (the end of another file; a drag back on one; the deadline mid-load).
- [x] SR105 (medium) A drag back while paused after an end here was pushed
  as in progress by the poll mpv's seek brings (the test stopped one step
  short). Fixed: the poll's paused push skips an episode that ended here.
  Test (with that poll).
- [x] SR106 (medium) A "played" mark retried within six hours overrode a
  phone that carried on meanwhile, and took it off Up Next. Fixed: the
  retry reads the record first; moved from where this machine left it
  (`left`), the entry is dropped; no answer, it waits. Test.
- [x] SR107 (medium) A record without `playedUpTo` read as 0 (seek to 0, then
  pushed). Checked live: every record has one; Up Next's sync data leaves
  it out for episodes not started. Fixed: a record without one is no
  answer; a sync entry without one starts from the record. The fake now
  leaves it out as the real reply does. Tests.
- [x] SR108 (low) The import dropped 1.0 values set with `omarchy bar set`
  (text): "0", "15", "false" are read as 1.0 read them. Test.
- [x] SR109 (low) Pause (and Stop) waited 10 s for the state lock behind a
  slow poll and failed "busy" with the episode playing on. Fixed: mpv is
  paused first (`pause_first`; `sync_now(was_playing=)` keeps the playing
  rule, which a first try broke and a test caught). Test.
- [x] SR110 (low) The poll's paused push sent a stretch that played without
  anyone asking (a media key's resume no poll saw). Fixed: not after a
  pause that set "ask first", unless a seek moved it. Test.
- [x] SR111 (low; C1, checked) Destroying a Quickshell Process kills its
  child (tested with a throwaway instance), so a plugin reload (any
  plugin's change reloads them all, the fit reviewer found) ends bridge
  calls in flight: safe by SR104's checks; a refresh cut in its last
  moment can sign you out (README, CLAUDE.md). keepLoaded stays dropped:
  with it, every update would leave the old service under the new panel.

Fit (nothing critical or high):

- [x] SR112 (medium, tests) 11 of the reviewer's 14 QML mutants survived:
  two screens' claims (one unplugged: the other's chip still holds the
  service), a re-claim within the delay, a dormant copy's socket, the
  hung-player and failed-load notices, no list reload with the panel
  closed, a vertical bar, an idle chip's wheel, a stopped chip's cover,
  the marquee behind an open panel. Tests for each (service.qml,
  chip.qml); the QML runner now fails a step that throws or times out,
  and on "Unable to assign" from Legato's files (the test bars carry the
  bar's properties).
- [x] SR113 (low-medium) The settings list sat in `barWidget.schema`, where
  settings apps would offer a form that writes the ignored bar entry.
  Moved to `legatoSettings` in manifest.json. Test.
- [x] SR114 (low) The Settings page's video switches sent Hyprland rules
  and the window.open hook with no window: only while it shows now. Test.
- [x] SR115 (low) "About 40 MB" was 75 MB (two Python helpers); "paused,
  nothing repeats" ignored the kernel's keepalive: reworded.
- [x] SR116 (low) Without the chip, the keybinds don't answer (Legato is
  off): said in README.
- [x] SR117 (low) Each plugin reload made a panel spin up its own service
  for a moment: a panel that had the shell's never makes one. Test.
- [x] SR118 (low, since 1.0) "Tab to open first" stopped applying after the
  first tab click: each open starts there now (Cody's choice, 2026-11-24,
  over remembering the last tab picked). Test.
- [x] SR119 (low) `hyprctl clients` on every poll would have passed the
  suite: a test now checks polls without video ask Hyprland nothing.
- [x] SR120 (low; safety nit) Before the 1.0 entry is copied in, autoplay and
  the idle unload stay off (a 1.0 user's "off" may be on its way). Test.
- [x] SR121 (mutations) A redundant flag removed (`stalledPlace`: a stall
  always sets `unconfirmed` too, so its guard could never matter alone; its
  mutant survived the full run); "a stall's place confirmed meanwhile" is
  now equivalent (the poll's paused push needs no "ask first" after a
  pause, round 11) and dropped from the set.

### SR, round 12 (2026-11-24)

Round 12's reports (kept outside the repo).

Safety: one high and four mediums, each a second door into a failure an
earlier round closed at its first.

- [x] SR129 (high) The resume check's seek past the end of this machine's
  copy (ad-stitched copies differ) marked the episode played everywhere:
  the seek never set `begun`, so `end_unproven` didn't apply. Fixed: the
  check's seek is a new start. Test.
- [x] SR130 (medium) A real end cut off mid-finish (the deadline, a reload)
  was handled but never told nor retried: the pending entry is saved with
  `handledEnd` now. Test (the deadline inside the push).
- [x] SR131 (medium) Play with nothing loaded, after an end whose removal
  failed, played the finished episode again from Up Next and pushed it in
  progress: Play retries what's pending first and never picks an episode
  that ended here. Test.
- [x] SR132 (medium) A media-key stretch nobody asked about (Legato off),
  paused again, was kept over a phone that went back, then pushed: the
  first poll marks it `unconfirmed`. Test.
- [x] SR133 (medium, reading) A push or check a poll had in flight when the
  sleep guard released the suspend could complete after the wake: every
  connection checks the boot clock against the monotonic one once
  connected (`SleepAwareHTTP(S)Connection`), and the resume check drops an
  answer read across a suspend. Tests (a whole call across a sleep, a
  sleep during the connection itself, an answer read after one).
- [x] SR134 (lows) Another episode's record is no answer (`user_episode`);
  an empty show list isn't cached; the bridge refuses to mark or move the
  loaded episode (only the panel did); a snapshot reads the position
  before the path. Left as designed: Play at an end plays it again from
  the top without asking (L3). The sleep guard's own "ask first" (a second
  guard behind the poll's) now has a test of its own. Tests.

Fit (nothing critical or high):

- [x] SR122 (medium, cost; measured by the reviewer) A panel never opened
  held its rows and covers on every screen (+21 to +79 MB), covers decoded
  at 320 px for 36 px rows. Fixed: rows exist only while the panel is open
  (and are let go when it closes); covers decode at twice the size shown.
  Test. Left: the panel's fixed parts are still built at load (Omarchy's
  own panels use KeyboardPanel's lazy `content:`; moving there means
  reaching the page and list items through the loaded content: later).
- [x] SR123 (medium, tests) 14 of the reviewer's 25 QML mutants survived:
  a dormant spell longer than the settle, the dormancy delay's default, a
  guard that gave up coming back for the next episode, WAYLAND_DISPLAY in
  the bridge's environment, the marquee while paused, the list cache, the
  slider's tick, the IPC status's live position, a signed-out refresh
  with mpv running, two panels' and Stats pages' counts, a service swapped
  under a panel. Tests for each.
- [x] SR124 (low-medium) A touchpad scroll on the chip moved the volume per
  event (one swipe: 50 to 90): deltas add up to notches now
  (`Model.wheelSteps`, as Omarchy's Util.wheelSteps). Test.
- [x] SR125 (low) A dormant copy dropped its callers' callbacks, so a late
  list load across a bar swap left "Loading…" for good: a dormant call
  answers "dormant" (and a dormant copy notifies nothing). Test.
- [x] SR126 (low; L4, a round 11 regression) After an update from 1.0, the
  kept 1.0 service never imports, and "safe until imported" kept autoplay
  off and the player never unloading until a restart: before the import
  the bridge leaves the choice to the caller (`setting_now` None). Test.
- [x] SR127 (low; L5) "A disabled IpcHandler still registers its target":
  false (checked with a throwaway instance); CLAUDE.md corrected (the
  Loader makes it moot either way).
- [x] SR128 (low) README: "take effect at once" narrowed to what does;
  the keybind example's SUPER+ALT+L is Omarchy's (now SUPER+ALT+O);
  uninstall stops mpv through the bridge (the keybind target needs the
  chip); About's privacy text says when the position is sent. Two stale
  Service comments. The resume check's path tests after the stray check
  were redundant: removed, with their mutants; "an idle copy of the
  service" is equivalent since round 11's latch.

### SR, round 13 (2026-11-24)

Round 13's reports (kept outside the repo; each finding with its scenario,
`file:line`, verification and a test). The first round in which neither
reviewer found anything critical or high. Each finding checked against
the code first: the safety reviewer's probes moved the phone 2 s from the
last push, inside the 3 s drift slack, so they partly measured the slack;
with places well outside it the findings held, and the tests use those.

Safety (three mediums, each a way to rewind a phone):

- [x] SR135 (medium) What played during a gap (Legato off, a sleep it
  missed, a guard that paused behind a slow poll) was kept over a phone
  that went back, then pushed. Fixed by evidence rather than position: the
  one local place kept over Pocket Casts' answer is where a push of a
  confirmed stretch failed (`unsentPush`, recorded by the failure, within
  the hour, the place unmoved since: `keep_local`). The first poll's
  marking (SR132) now compares with that failed push too (`moved_unasked`),
  so a pause whose push failed is still kept (it wasn't, in the real flow:
  the poll its pause brings marked it), and retried by that poll (the
  paused push's own `was_checking` guard, redundant with the marking but
  for that retry, removed). An end reached during a gap or unconfirmed
  reads the record first, as a retry does: another device's place stands
  (not marked played, the player closes, the next Play follows Pocket
  Casts), and nothing autoplays (`finish_current`). Tests: a stretch
  through a gap (Play; Stop), still playing after a gap, a failed push
  then a gap, a failed pause push kept and retried, an unconfirmed resume
  after one, the guard behind a lock then a long sleep, an end through a
  gap (the phone went back; nobody else).
- [x] SR136 (medium) A Play across a suspend loaded after the wake with
  `pause=no` and recorded a fresh sync. Fixed: a call that slept loads
  paused (and a sleep during the load pauses once loaded); Play's resume,
  and Play again, don't unpause after one; and every sync records the
  call's own suspend clock at its start (`synced`, `lastSyncSleep`), so a
  later call sees any suspend since as a gap (`sync_age`: also L3 below,
  and every "recent" check: the poll, sync_now, a break's push). Tests.
- [x] SR137 (medium) A finished episode whose removal was pending was
  replayed from 0 by Next, autoplay, Play at an end and the resume check's
  switch. Fixed: one rule (`ended_or_pending`) in `next_in_up_next` and
  the resume check's top (`up_next_top(skip=)`), which retries pending
  finishes first (one restarted elsewhere is followed again). The fake's
  Up Next can carry playingStatus (`syncStatus`). Tests (the switch,
  Next, autoplay and Play at an end, a replay from a list).
- [x] SR138 (lows) A host without ranges refusing the seek back: loaded
  again at Pocket Casts' place (mpv's `time-pos` doesn't move on a
  refused seek; probed). An HLS break in its last tenth: the playlist's
  own length, within BROKE_SLACK. The guard's unpushed pause after a
  short sleep: `sync_age`. A malformed playback.json: fields of the wrong
  shape dropped as it's read (`clean_playback`). A removal-only retry
  reads the record first (played, then restarted elsewhere: left alone).
  An unsent break or push isn't recorded from a call that slept. The
  reviewer's survivors R1, R3, R16, R32, R33: tests (the fake can lose a
  reply after applying a write, `lostReply`).

Fit (three mediums, nothing critical or high):

- [x] SR139 (medium, tests) The stand-in Process keeps `running`'s binding
  through an exit, as Quickshell does (`alive`); the guard's restart after
  a sleep is tested, and the restart timer now starts first in `onExited`
  (a failure count change re-evaluated the binding and started a guard at
  once). mpv's events tested: the five observed properties, a pause
  change and a seek each bringing a poll, the IPC status while paused.
- [x] SR140 (low-medium) Both panel sliders add a touchpad's deltas up to
  notches (`WheelNotches`, Model.wheelSteps) and the slider underneath
  sees none. Tested with real wheel events offscreen (QtTest's
  `mouseWheel`; the stand-in slider steps per event as Omarchy's does).
- [ ] SR141 (design, deferred past 1.1.0) Four hand-kept counters (claims,
  open panels, Stats pages, pages): each has tests now; deriving them
  from a list of registered panels is the cleaner design. A launcher with
  cached bytecode would save about 40% of each call's CPU. CLAUDE.md is
  long (a reorganisation with the next feature work).
- [x] SR142 (lows) The panel keybind goes through Omarchy's `panel` route
  (the focused screen's chip; README, node check); both IPC targets are
  `ShellIpc` (no qs ipc client per key); the dead header rows removed;
  rows kept through the close's fade; the cover's fade and the marquee
  follow Omarchy's animations switch (`Style.duration`, `reduceMotion`);
  private paths and details of the maintainer's setup out of the docs; TempHome drops the
  compositor and bus variables; claims corrected (32 s polls and hyprctl
  with video, the plugin-id IPC list, two stale comments, the suite's
  length). Left: `hyprctl`'s replies aren't read (a refused rule shows as
  an unplaced window; nothing that syncs). The reviewer's 16 surviving
  mutants: tests for each (chip clicks and IPC toggle/isOpen, Esc, a
  typed password and a show page closed with the panel, Tab to the next
  panel, re-sign-in, the idle unload's `--if-paused`, ticks while
  buffering, the hyprctl timeout, the rule before the next load).
- [x] Round 12's full run, 350 of 352: "a dormant copy keeps mpv's
  socket" survived because the test's player had stopped before the
  copy went dormant (test fixed: it holds a live socket then); "a stretch
  nobody asked about pushed" was the paused push's guard, now removed
  (above).

### SR, round 14 (2026-11-25)

Round 14's reports (kept outside the repo). Neither found anything
critical; the safety reviewer found one high. Each finding checked against
the code first.

Before the reports came back (from tonight's own events):

- [x] SR143 (an incident) A reviewer pointed HOME/XDG at a scratch folder
  through a path with `..`; the bridge dropped it as not normalized and
  fell back to the account's real home, acting on Cody's real state and
  Pocket Casts account (an episode taken off Up Next, a clip played aloud,
  settings changed; restored with his OK). Fixed: directory variables are
  normalized absolute paths, and one set but unusable stops the call
  (`bad_env`). Tested in process, with the account's own home faked too.
  The strict-review skill's reviewer prompts now forbid running a
  project's program outside its test harness.
- [x] SR144 A feed that keeps only its newest episodes drops older ones,
  and Pocket Casts forgets them (an empty record): Play said "Pocket Casts
  didn't answer" for good, and Next could stick the same way. Now an
  episode the show's own list no longer has (`left_its_feed`; a list that
  won't load or comes back empty proves nothing) is `gone`: Play moves on
  to Up Next, Next and autoplay skip it. Tests.

Safety (one high, two mediums, two lows):

- [x] SR145 (high) A place this machine played and couldn't send was lost
  once the player closed (Stop, the idle unload): only a loaded player kept
  it, and a transient lookup error fell through to Up Next at Pocket Casts'
  older place. Fixed, and simpler: the keep moved to reloads of the same
  episode (`play_item`'s `kept_place`: Play after the player closed, a
  break's reload, Play from a list), with one rule: within the hour, while
  Pocket Casts still holds this machine's last push (nobody else wrote
  since). A loaded player needs none (it seeks only on another device's
  write), so `keep_local` is gone, and so is the old trade-off (a phone
  rewound on purpose within the hour was undone). The break's own unsent
  place is the same record now (`unsentBreak` gone). Play with nothing
  loaded raises "try again" on any lookup error but "gone" or "no audio".
  Tests (Stop, the idle unload, an hour on, a write elsewhere, a failed
  lookup, a replay of an episode finished elsewhere).
- [x] SR146 (medium) An end reached on a resume nobody checked yet (a media
  key, no poll before the end) was marked played over a phone that went
  back: `unwatched` now counts `checkServer`. Test.
- [x] SR147 (medium, tests) Pocket Casts' https transport never ran the
  suspend check in a test: one now goes through the production opener to
  a TLS host (both reviewer mutants killed).
- [x] SR148 (lows) A media widget's seek while paused, reported as a seek,
  is sent (and one nothing explains isn't): tests. A Play in flight as the
  lid closes: the guard waits for it (`pause_after_play`, up to 6 s) and
  pauses what it started. Test.
- [x] SR149 (nits) cmd_seek's dead `checkServer` guard removed; CLAUDE.md's
  "5 s per request" narrowed.

Fit (nothing critical or high):

- [x] SR150 (medium) An update runs the QML the shell already compiled
  (Quickshell 0.3.2 can't clear its component cache; measured): from
  1.0.2, 1.0's panel and service run against 1.1's bridge until the shell
  restarts (Settings empty meanwhile; playback and sync under 1.1's rules,
  the bridge parsing every call 1.0 makes). README, CLAUDE.md, install.sh
  and H6 corrected. From 1.1 on, `status` says the files' version and the
  service compares it with its own (`Model.qmlVersion`, kept equal to
  manifest.json's): "restart the shell to finish" on a mismatch. The
  1.1-panel-over-1.0-service handling stays, for a shell that clears its
  cache. Tests.
- [x] SR151 (medium, tests) Stand-ins closer to the platform: Omarchy's own
  PanelKeyCatcher (a copy, checked against the installed one) and
  KeyboardPanel's required properties. Tests with real keys: Enter on a
  row plays once; typing in the sign-in fields types; Ctrl+key isn't
  text; the length cap; a paste cancelled by focus moving. And: the 1.0
  bar entry imported through the real chip; a late show page's answer;
  the volume debounce; covers decoded small; `legato stop`; the live
  position at speed; sign-out forgetting the lists.
- [x] SR152 (low) Maintainer details in CLAUDE.md made neutral (dotfiles
  paths, the old fork's working copy, Hyprland focus, the laptop's GPUs).
- [ ] SR153 (lows, left) No i18n (not a regression); the chip's `refresh`
  IPC reloads per screen on two screens; guards stacked two deep in a few
  places; settings defaults listed twice in manifest.json; notifications
  without an icon. The verification request should list what 1.1 adds:
  notify-send, the self-check's 127.0.0.1 server and its detached process.

- [ ] SR46 (see round 5) Re-shoot media/stats.png with representative
  numbers, on an empty workspace, after the code is final.
- [ ] H6 Ship 1.1.0 (a minor version: the stats are a feature) with the
  `ship-update` skill: push (Cody), plugin update and install test (from
  1.0.2 without a shell restart: 1.0's panel keeps running against the
  1.1 bridge, Settings empty, playback, sync and its keys still working,
  SR150; then after the restart, Settings and Stats work, and a later
  1.1.x update says "restart the shell to finish"),
  marketplace scan, release notes and `gh release` (each on his go), and
  last of all the marketplace verification request (Cody approves the
  filing).

### SR, round 15 (2026-11-25)

Two reviewers again (safety; fit), the safety one writing its own report
this time. Fit found nothing critical or high; safety found two highs, both
second doors into outcomes earlier rounds closed at one door.

- [x] SR154 (high, H1) A place this machine played and couldn't send was
  lost the moment Legato moved to another episode (Next, which also took
  it off Up Next; Play from a list after the idle unload; the resume check
  following the phone to another episode): `unsentPush` lived in the one
  episode record each switch rebuilds. Now the outgoing episode's unsent
  place goes along (`stash_unsent` into `unsentPlaces`, with `left`, where
  Pocket Casts had it from here): `retry_unsent` sends it on the switch, a
  later poll or Play with nothing loaded, only while Pocket Casts still has
  it at `left`, and a reload of it starts there meanwhile (`kept_elsewhere`).
  Within the hour, as on a reload. Tests: Next, Next with pushes still
  failing then a poll, Play another then this one from a list, following
  the phone, a phone that moved or finished it since, the hour.
- [x] SR155 (high; a rewind to 0, H2) An end reached unwatched whose record
  read failed (the outage that left it unwatched, often) stayed "ended
  here": Play played it again from 0 and pushed 0 over the phone. Now
  `finish_current` treats no answer like "carried on": not ended here, the
  player closes, the pending entry waits (`unanswered_end`; entries say
  `confirmed`); Play with nothing loaded fails "try again" until Pocket
  Casts answers, then follows the phone or marks it played and moves on.
  Play at an end whose finish is pending asks first (a call cut off while
  asking left it ended here with the player loaded); the poll and a drag
  back push nothing while it's unanswered. Found while fixing: an end with
  no record anywhere (a show you don't follow, every push failed) could
  never be confirmed, and Play would say "try again" for six hours: an
  empty lookup now answers by check_server's rule (`empty_lookup_answers`).
- [x] SR156 (medium, M1) Next, autoplay and the resume check's switch
  replayed an episode Pocket Casts says is played from 0 and pushed it in
  progress: Mark played whose Up Next removal failed (swallowed), or one
  finished on another device whose removal wasn't in yet. Now every
  next-picker skips played episodes (sync data's status or the record's),
  and a failed removal after Mark played is a pending finish.
- [x] SR157 (medium, security, M2) The feed proxy reached this computer
  through its own Wi-Fi, docker and tailnet addresses (verified; local
  feeds on), and by reading through a global one with the setting off:
  "never this computer" was false. Now a connection whose two ends show
  one address is refused (`same_address`); tested against every
  non-loopback IPv4 address of the machine running the suite.
- [x] SR158 (low-medium, L1) A later retry that found the phone carried on
  dropped the entry but left `handledEnd`: Play skipped the phone's
  episode. Now it clears `handledEnd`, and the poll closes a player left
  at that end.
- [x] SR159 (low, L2) The progress bar's wheel sent an absolute place from
  the last poll's position (after a resume check moved it, pushed behind
  it): now relative, as the skip buttons.
- [x] SR160 (low, L3) A poll that failed (busy) after a media key's pause
  was never retried, so the pause went unread: the service now retries a
  failed poll while an mpv event is unread (three times, 2/4/8 s).
- [-] SR161 (low, L4, declined) "Every load pushes where it starts": that
  push marks the episode in progress at once, as the apps do; the source
  this round found wrong (a played episode on Up Next, SR156) is filtered
  where it's picked.
- [x] SR162 (nits) An empty HOME fell back to the account's (now refused,
  like any unusable one); NaN, infinite and negative positions passed as
  numbers and read as "at 0" (now no answer: `a_place`); queueing again or
  Mark as unplayed after an end here kept its retry, which took it off Up
  Next again (`forget_pending`).
- [x] SR163 (tests) The reviewer's two surviving mutants (a kept reload's
  `unsentPush` and `lastSyncPos`) now killed by a reload whose push fails
  too; tests for every path above.
- [x] SR164 (medium, fit F1) After an update, until a restart, the panel
  showed the restart note over every error ("Stream ends here: mark it
  played" never seen); the test had pinned it through a stale error. Now
  errors first, then the note.
- [ ] SR165 (medium, release, F2) media/pages.png still shows 1.0's
  Settings page ("Saved to ~/.config/omarchy/shell.json") and Cody's own
  subscriptions and episode titles: re-shoot with stats.png (Cody's call
  on the content).
- [x] SR166 (low, F3) A cancelled paste flashed "returned nothing":
  Quickshell sends `exited` for a stopped Process (probed). The paste
  drops its callback first; the Process stand-in now sends `exited` on a
  stop, as Quickshell does.
- [x] SR167 (low, F4) That same `exited` delayed the next episode's sleep
  guard by the retry wait: `onExited` restarts nothing when no guard is
  wanted.
- [x] SR168 (low, F5) The self-check's folder moved from /tmp into Legato's
  private runtime folder.
- [x] SR169 (low, F6) Every plugin reload (any plugin) fetched Up Next for a
  panel nobody opened: now only status and the player; README's "no process
  starts" said of timers now, with the reload named.
- [x] SR170 (low, F7) With no screen at all (lid shut, monitor off) every bar
  went and the service went dormant: no syncing, no pause before sleep. It
  stays awake while `Quickshell.screens` is empty.
- [x] SR171 (nits) Dead `shell` property; unused glyphs; the chip's stale
  header comment; Alt/Ctrl/Super + a letter acted as the panel's key (Alt+N
  was Next); CLAUDE.md rule 6 now names About's browser link.
- [x] SR172 (tests) The menu's Played/Unplayed marks, Esc and Enter with the
  menu open, `4`, ← on a show's page, the password cleared after sign-in,
  modifiers. Left untested (low value or layered): the cover fade with
  animations off, the chip's IPC on two screens, the hero click, volume-icon
  mute, the signed-out colour, cursor scrolling into view.
- [ ] SR173 (left) Stand-ins: no first-wins IpcHandler, per-screen test bars
  where Omarchy shares one; the panel built on every screen.

### SR, round 16 (2026-11-25)

- [x] SR174 (critical, C1) A place whose push failed outlived a resume check
  that took the phone's place: the check set `lastSyncPos` to the phone's
  place and kept `unsentPush`, so the keep rules (comparing with
  `lastSyncPos`) read "nobody wrote since", and a reload (Stop, Play) or a
  switch (Next) pushed the old place over the phone (verified by four
  paths: a media-key pause at once, a stall, a gap). The unsent place now
  carries `left`, where Pocket Casts had it when the push failed, and holds
  only while `lastSyncPos` is still that (`unsent_push`): one gate for
  every reader, whatever writes `lastSyncPos` next. Tests for the four
  paths.
- [x] SR175 (low-medium, M1) A Mark as unplayed (here or on the phone) of an
  episode left unsent near 0 was undone by the retry: a mark is a say now
  (`where_left`: played or unplayed is another device speaking), and a mark
  here drops the episode's unsent places (`forget_unsent`).
- [x] SR176 (tests, T1) `kept_elsewhere`'s "still where it was left" and the
  hour were never reached (every test polled first): tests reload before
  any retry.
- [x] SR177 (low, L1) An unwatched end that later left its feed (Pocket Casts
  forgot it) made Play say "try again" for six hours: the retry drops such
  an end (`left_its_feed`), and Play moves on.
- [x] SR178 (nit, N1) Play on the loaded episode's row reloaded it from
  Pocket Casts' place, up to a poll behind: it resumes it now (from the
  start still plays it again from the top). Round 17 (fit) showed that
  fix unreachable (the row and its menu handle the loaded episode before
  `playItem`; removed) and the row's real flaw: it took the last episode,
  with nothing loaded, for the loaded one and sent "resume", which skips
  an episode that ended here. It asks `isLoaded` now.
- [x] SR180 (medium, fit M1) The sleep guard's and the feed proxy's exemption
  from the 120 s call deadline was untested (both mutants survived; under
  it the guard restarted every two minutes and gave up, the proxy died
  mid-episode): `Deadlines` runs each past a 1 s deadline.
- [-] SR181 (low, fit L1, left for after 1.1.0) The whole panel is built on
  every screen at start and at every plugin reload (about 330 objects a
  chip); Omarchy's KeyboardPanel offers lazy `content:`. A restructure of
  Panel.qml (its functions reach into the tree by id) and of the test
  stand-in; not a correctness issue.
- [x] SR182 (low, fit L2) Two quick Settings or Stats changes raced for the
  file's lock: the page could show one value and the file hold the other
  (the bridge acts on the file). Writes now go one at a time, in order
  (`write`; its watchdog went in round 17, so a write waits at most on
  the bridge's own deadline), and an answer a later change supersedes
  never shows.
- [x] SR183 (low, fit L3) Other ways to "no screen, nothing syncs": a shell
  started with no screen, a replacement bar's panels gone with the screens
  (the shell's copy wakes whenever there's no screen: `noScreens`), and the
  chip left in the tray's drawer after the tray is removed (README).
- [x] SR184 (low, fit L4-L5, N2-N5) README's mpv memory figure (80-150 MB,
  measured), "which disables it" (not with Legato in `plugins`), the
  Hyprland hook and Lua functions left after uninstall; 1.0's out-of-range
  values clamped at the import, not dropped; an unreleased project's name
  out of the public files; Model.js comments by their functions.
- [x] SR185 (tests, fit L6-L7) The event retry's bound and back-off; signed
  out with no player, no poll; a copy gone dormant with a player keeps no
  sleep guard (was a source regex only).
- [ ] SR186 (left) Light themes: `Qt.darker` dims the wrong way (platform-
  wide: Omarchy's own panels do the same); no i18n; CLAUDE.md's length.
- [x] SR179 (redundant guards) `retry_unsent`'s ended-episode filter (the
  record's status covers it) and `resume_last`'s forced send (the switch
  sends it) removed; `empty_lookup_answers`'s "a show you follow" tested
  (its failure would mark an unfinished episode played).

### SR, round 17 (2026-11-25)

Fit: no critical or high. Safety: none rated above medium, but F2 rewinds
another device (the worst outcome), so another round follows.

- [x] SR187 (medium, F1) The resume check's switch followed Up Next to an
  episode played on another device when Up Next's reply had no sync entry
  for it, and pushed it in progress at 0 (SR156's second door: the record
  says played, and the switch never read it). It reads it now.
- [x] SR188 (medium, rewinds another device, F2) Play at an end told here
  played it again from 0 without asking, over a phone that had gone back
  into it; with the player closed, Play skipped that episode for the next.
  Play asks first (`reopened_elsewhere`): reopened, it follows the phone;
  no answer, "try again". Play with nothing loaded lets the record decide.
- [x] SR189 (medium, loses a place, F3) `play_item` took the start it chose
  for Pocket Casts' place before the load's push landed: with a skip-intro
  and that push failing, the next check read Pocket Casts' own 0 as
  another write and sent the player back; started from the top with every
  push failing, the place was read as marked unplayed and dropped. Now
  `lastSyncPos`/`lastSyncStatus` are Pocket Casts' until a push lands, and
  "unplayed" is a mark only if Pocket Casts had it otherwise (`leftStatus`).
- [x] SR190 (low, F4) Play judged an end handled here again (break or end):
  a verdict changed since (the self-check finishing "failed") pushed the
  finished episode in progress. An end handled here isn't judged again.
- [x] SR191 (low, F5) `recordSeen` ignored this machine's own pushes (a push
  creates the record): a landed push counts now.
- [x] SR192 (nit) Sign-out drops playback.json under the state lock.
- [x] SR193 (tests) The reviewer's surviving mutants: the stash's "not an
  episode that ended here" (N1), the unsent retry's "a record without a
  place is no answer" (N22), the adoption's `lastSyncPos` (N8), the
  switch's "finished" arm (N2) tested; the stash's own hour (N18) removed
  (retry_unsent's and kept_elsewhere's are the rule).
- [x] SR194 (low-medium, fit 1) The last episode's row, with nothing loaded,
  was taken for the loaded one and sent "resume", which skips an episode
  that ended here (a play you chose replays it): the row asks `isLoaded`.
  SR178's `playItem` branch was unreachable and is gone.
- [x] SR195 (low, fit 2) The write watchdog repeated call()'s start watchdog
  and, on a slow write, ran two writes at once: removed; the de-duplication
  of a waiting write tested.
- [x] SR196 (fit nits) README: Legato in `plugins` wakes with no screen;
  CLAUDE.md's status and the suite's 23 minutes.
- [x] SR198 (Cody, 2026-11-25, from a side agent's note) Round 14's refusal
  of an unusable directory variable also stopped Legato for an XDG typo
  (`XDG_STATE_HOME=~/.local/state`), where the XDG spec says to ignore a
  relative path: only an unusable HOME stops a call now; an XDG variable
  that isn't absolute is ignored and its default under HOME applies.
- [ ] SR197 (left) The video window's saved position is global but replayed
  as a monitor-relative rule on a second monitor not at 0,0 (since 1.0,
  by reading: needs a live check on two monitors); `wheelSteps` copies
  Omarchy's; `{ipc=}` can't reach the chip's dotted target (the `legato`
  target and `{panel=}` can); `media/preview.png` shows Cody's real Up
  Next (his call with the other screenshots).

### SR, round 18 (2026-11-25)

Fit: no critical or high.

- [x] SR199 (medium, fit M1) No test reached the progress bar's drag or
  click (the PanelSlider stand-in had no drag): sent as relative, a drag
  would jump to the end and the poll mark the episode played. The stand-in
  drags now (`dragTo`, `releaseDrag`); tests for the absolute seek, a skip
  folded into it, and the volume drag.
- [x] SR200 (medium, fit M2) The idle unload's "only while paused" was
  untested (its timer unnamed): named and tested.
- [x] SR201 (low, fit L1) An empty HOME still reached the account's home on
  the plugin's own path: `closedEnvironment` dropped it, so the bridge saw
  none. It goes on empty now, and the bridge refuses it.
- [x] SR202 (low, fit L2) Since round 17, the loaded episode's row at its
  end sent "resume", which with autoplay on starts Up Next's next: at its
  end it's a play you chose, played again.
- [x] SR203 (low, fit L3-L4) The poll retry's "not for a dormant answer"
  tested; the Settings page's always-on-top, local feeds and transparency
  show at once and write in order (a quick second click acted on the old
  value), an answer a later click supersedes never showing (`write` tells
  its callback `latest`).
- [x] SR204 (fit nits) The service's dead `Component.onCompleted` refresh
  (onActiveChanged runs for the first value) removed; `call()` answers
  when its Process can't be made; a stale comment.

Safety: two criticals, both more doors into "play again".

- [x] SR205 (critical, F1) After an end told here, a skip or drag back and
  then Play, or a media key, pushed this machine's place without asking
  (only Play at the very end asked, round 17). Every way back in asks now
  (`end_still_stands`); another device back in it, Play follows it and a
  media key's resume is asked; no answer, nothing pushed.
- [x] SR206 (critical, F2) Play at a watched end whose mark failed played
  it again from 0 when Pocket Casts couldn't be asked (only an unconfirmed
  end said "try again"; a test pinned it as intended): a pending finish
  must get an answer (`retry_pending_finish(answered=)`) before playing it
  again.
- [x] SR207 (medium, F3) The resume check took Pocket Casts' place though
  mpv was never sent there (a stalled `path` read, no connection): the
  next push sent mpv's old place over a phone that went back. It adopts
  only after the seek; otherwise "unverified".
- [x] SR208 (low, F4) `lastSyncPos` was 0 for a load from the start or a
  played episode replayed: it's Pocket Casts' place; a played episode
  replayed here with its push failing isn't "finished elsewhere".
- [-] SR209 (medium for harness safety, F5) A scratch HOME doesn't isolate
  the player (mpv's socket is in the runtime folder). Refusing a HOME
  other than the account's would refuse real setups: documented (rule 6),
  and the harness pins every XDG folder.
- [x] SR210 (lows) L1: a self-check under way isn't trusted; L2: a mark
  drops the episode's retries and sends, under the state lock; L3: a load
  just as the sleep guard pauses for a suspend loads paused (`mark_sleeping`,
  `sleeping_soon`).

### SR, round 19 (2026-11-25)

Fit: nothing critical, high or medium.

- [x] SR211 (low, fit F1) The menu's Play on the loaded episode at its end
  still sent "resume" (SR202's second door; a node regex pinned the bug):
  played again, as its row.
- [x] SR212 (low, fit F2) A failed settings save (or stats switch) with
  another write waiting was swallowed, the page flipping back silently:
  an error is said whatever came after.
- [x] SR213 (low, fit F3) The sleep guard's mark wasn't tied to a sleep (a
  Play right after a short suspend loaded paused): it records the suspend
  clock, and is spent once the suspend happened.
- [x] SR214 (tests, fit T2-T4) Transparency and always on top's superseded
  answers; a dormant copy re-reading the player when it wakes; the Process
  stand-in sends `exited` a moment after a stop, as Quickshell does
  (probed: even after a restart in the same tick), which showed the
  guard's `onExited` counting a stale exit against the next guard: a
  signal-15 exit is a stop now (the separate "not wanted" check, its
  duplicate, removed). README: the idle unload starts two processes.
Safety: no critical or high; three mediums in the worst-outcome classes,
fixed before release.

- [x] SR215 (medium, loses a place) A played episode replayed here whose
  pushes all failed lost its place: "played" read as a new mark
  (`where_left`), Play with nothing loaded skipping a played last episode,
  a play-again's failed push not kept, and the check reading its own
  "played" as finished elsewhere. "Played" is a mark only if Pocket Casts
  had it otherwise from here; a kept place keeps a played last episode;
  a play-again's failed push is kept; a landed mark is Pocket Casts'
  place (`told_played`).
- [x] SR216 (medium, a finished episode pushed in progress) Next and
  autoplay took an Up Next entry with a place but no status for in
  progress (the bridge asks for statuses, but the reply's shape is
  unverified): such an entry reads its record first.
- [x] SR217 (medium, rare, loses a place) A push whose reply was lost,
  then failures while it played on: the next Play took the lost push's
  place for another device's and went back to it. The unsent place
  remembers the pushes tried since its base (`triedPushes`). Withdrawn in
  round 20 (SR221): it let a phone that stopped near a tried place be
  overwritten.
- [x] SR218 (low) A Play in flight longer than the guard's 6 s wait played
  on behind the lock screen: the guard marks the sleep first thing, and
  Play and play again don't unpause under it.
- [-] SR219 (low, left) An empty show list reads as "you follow nothing"
  (`record_expected`), and a 200 that isn't JSON as an empty answer: one
  layer of three; reading an empty list as "can't tell" would make Play
  say "try again" for good for someone who follows no show.
- [x] SR220 (tests) Play with nothing loaded after marking the closed last
  episode played (its removal failing) moves on: the reviewer's surviving
  mutant (a told pending end counted as unanswered).
- Cody's call before pushing: every commit carries his personal address
  as author (1.0.x's are already public); `media/preview.png` and
  `media/pages.png` show his own Up Next and subscriptions.

### SR, round 20 (2026-11-25)

The verification round of round 19's fixes. Safety: one critical, from
round 19's own `triedPushes`.

- [x] SR221 (critical, F1) `triedPushes` took Pocket Casts showing any of
  up to 30 places this machine had tried to push for its own (a lost
  reply), with no age limit and for pushes that couldn't have landed: a
  phone that stopped within 3 s of one was overwritten at Play, and by the
  retry after Next (verified). Withdrawn: a lost reply's place is taken
  for another device's (a known limit, README: what played here since is
  lost, never another device's place); old state files drop the field.
- [x] SR222 (medium, F2) A played episode replayed here, played to its end
  here, kept its old unsent place (`told_played` made it valid again):
  Play reopened it at 104 in progress. An end handled here drops it.
- [-] SR223 (medium, F3) The load's own push whose reply was lost: the same
  known limit as SR221 (withdrawn with it).
- [x] SR224 (lows F4-F5) The adoption's status and a malformed tried list:
  gone with SR221.
- [x] SR226 (fit, lows) After a failed save, its re-read ran beside the
  next write (it could land first and show the old value): queued now
  (`rereadSettings`), and a later save that lands clears the message; the
  sleep guard has a start watchdog (one that never started went
  unnoticed: `processId`); a guard killed by another signal tested; a HOME
  with a control character refused, not left out; the stats switch's
  error with a Clear waiting tested; a README note on `hyprctl
  configerrors`; dead code; `mutate.py` refuses an unknown name (it ran
  nothing and passed); Omarchy's MIT notice on the copied
  `PanelKeyCatcher.qml`.
- [ ] SR227 (left) The stand-in drags by function call (no press reaches
  the real pointer path); `isOpen` across several screens; the stepper's
  clamp; `tests/qml/panel.qml` has no per-step deadline.
- [ ] SR225 (nits, left) `load_into_mpv`'s `pause=` ignores the guard's mark
  (a moment of audio as the lid closes; it's paused right after the load).
  (`refuse_loaded` outside the state lock: fixed in round 25, SR268.)

### SR, round 21 (2026-11-25)

Safety: two criticals and a medium, each a second door into an older rule.
Fit: one medium (a round 20 claim false on the real shell), lows.

- [x] SR228 (critical, F2) A pause whose push failed was sent again blind,
  within the 90 s, by Stop, Next, a switch, Pause again, a seek while
  paused or the poll any mpv event brings, over a phone that had carried
  on from Pocket Casts' older place (verified: 40 to 6). After a failed
  push, a paused push reads the episode's record first and goes only
  while Pocket Casts still has it where this machine left it
  (`paused_push_stands`, `where_left`), the keeps' own check; no answer
  or moved, nothing is sent, and the keeps carry the place. The test that
  pinned the blind resend now asserts the ask before it. Considered and
  left out (Cody had agreed to both halves): a failed push no longer
  refreshing the "recent" clock. With the record check, it would be a
  second guard on the same rule (its mutant equivalent), and it would
  only hold back a place that's safe to send.
- [x] SR229 (critical, F1) Play from a list ignored `recordSeen`: a show
  you don't follow, an empty lookup, listed nowhere, started at 0 over the
  phone's 25. `record_lost`, asked by both ways to play the last episode
  again (`cmd_play`, `resume_last`).
- [x] SR230 (medium, F3) A landed "played" mark didn't note a record, so
  one empty lookup replayed a told end from 0, in progress, over "played";
  Mark played or unplayed on the closed last episode the same. Both note
  `recordSeen` now (`told_played`, `cmd_mark`). Assumed, as the fake
  does: a mark (the same `/sync/update_episode` as a push) creates a
  record for a show you don't follow, as a push was checked live to.
- [x] SR231 (lows, L1-L3) A push that sent nothing (no show id) recorded
  as landed by four callers; a 3xx from the API taken for success (a push
  "landed", Up Next read as empty; the episode lookup still reads it as
  empty); a wall clock stepped back read as fresh (a time in the future
  is a gap now). The watcher's own stall clock (`os.time()`) is left.
- [x] SR232 (medium, fit F1) Round 20's guard start watchdog never ran on
  Quickshell 0.3.2: a Process that can't start reads `running` false
  (one change, binding kept) and never true, and the watchdog was armed
  on true. Armed and judged from `guardWanted` now; `RealQuickshell`
  runs the guard block, sliced from Service.qml, on the real Quickshell
  offscreen (0 failures counted on the old code, 5 and one notice on the
  new); the stand-in's note says what it can't model, and a node check
  keeps `running` out of the guard's judgment.
- [x] SR233 (lows, fit F2-F4) A failed save's message wiped by another
  setting's save (each setting's failure is kept until it saves:
  `settingFailed`); Play at an end kept `ended` until the answer (a
  second press loaded it twice); tests for what only mutants had shown:
  the chip's wheel down, the volume clamp, a poll begun between a seek's
  step and its send, a hybrid laptop whose NVIDIA GPU wires an empty
  port. Nits: Service.qml's "no process" comment, tests/qml/v1_0's
  README, Omarchy's MIT credit on `wheelSteps`, install.sh reads the
  plugin list as JSON. README: the phone's late save (a known limit).
- [x] SR234 The video window's named rules re-sent at each show and load
  pile up on Hyprland 0.56 (re-made named rules append, Tracery's finding);
  whether the newest `pin`, `size` and `move` still win was last checked
  live on 2026-11-23. Checked live with Cody on 2026-11-26 (Hyprland
  0.56.2, his own episode, its video window): six closes and reopens, each
  re-sending the rules, came back pinned, floating, tagged skip-taskbar, at
  the saved size and place; after he dragged and resized it, the close
  learned the new place and both reopens used it, over five older copies
  carrying the old one. The newest wins: the pile-up is untidy, not
  harmful. (Sending once per Hyprland config load would tidy it: left.)
  i18n (SR186) stays left.

### SR, round 22 (2026-11-25)

Safety: one high, one medium; round 21's changes opened no new door the
reviewer found. Fit: one high (test safety), lows.
The reviewers' reports are kept outside the repo.

- [x] SR235 (high, safety H1) Signing in to another account (the sign-in
  page shows whenever a session expires, so nobody signs out first) kept
  the first account's playback.json and player: the next poll and the
  retries pushed its places into the new account (verified). A sign-in
  that isn't to the same account (`same_account`: uuid, else address; no
  earlier session counts as another) ends the player and drops
  playback.json under the state lock, as a sign-out does; the same
  account keeps everything.
- [x] SR236 (medium, safety M1) A list of your shows that came back empty
  (an odd reply) made a followed show's empty lookup an answer: Play
  pushed 0 over the phone's 25 (verified; round 19's SR219 had left it).
  An empty list falls back to the last one that loaded
  (`cached_subscriptions`): a show on it still counts as followed, while
  someone who never had one follows nothing, so nobody is told "try
  again" for good.
- [x] SR237 (lows, safety L1-L2) A "played" mark that sent nothing (no
  show id) was recorded as told; FFmpeg's lines were trusted while mpv's
  version couldn't be read (no verdict can match: by length now).
  `retry_unsent` dropping a place it can't ever send (no show id) is
  right as it is. Nit left: Next takes the episode off Up Next before it
  knows there's a next one.
- [x] SR238 (high, fit F1, test safety) `Validation` ran the sleep guard
  in-process with the real HOME and XDG folders, safe only while the
  guard stopped at "no sleep": one broken line and a run would pause the
  real player and push to the real account (round 14's class). The whole
  test file now runs in a throwaway home set before the bridge loads,
  with no display or session bus, and `run_bridge` refuses the real
  account's folders (tested). Temp homes use /tmp when TMPDIR is long
  (mpv's socket path limit).
- [x] SR239 (low, fit F2) A guard sent SIGTERM by anyone else was taken
  for Legato's own stop: never counted or restarted. Each stop Legato
  makes while a guard runs is owed one signal-15 exit (`_guardStops`,
  `_guardsRunning`); any other is a failure. RealQuickshell kills a
  running guard and expects it counted and back.
- [x] SR240 (lows, fit F3-F5) The Socket stand-in refuses as the real one
  does (`error` inside the write, `connected` left false; the retry a
  second later now tested); tests for the Settings steppers' ends and the
  choice wrapping, Enter and Space behind a page, Ctrl/Super+letter, the
  poll's `--no-autoplay`, an unknown video-window key; `mutate.py
  --confirm` re-runs each kill's tests unmutated (a flake is FLAKY, not a
  kill). README: "Nothing polls while paused or idle" (four helpers stay
  resident: Resources says so); SR182's watchdog note; Panel.qml's
  header comment.
- [ ] SR241 (left, fit F4/F6) Untested still: the Python probe accepting a
  candidate that exited non-zero, a status read in flight started again,
  the paused cover's dimming, `x` on an episode not queued, Next's
  availability and Up Next's reload after Next; six behaviours only
  source regexes check. Stacked guards (F6): where one side is the panel
  and the other the bridge (the steppers and the schema check, the
  transparency clamp and its range check, `next()`'s cancelled seek and
  the bridge refusing another episode's seek), each defends its own
  input and stays; the panel's halves are now tested where cheap. The
  dormant pairs (`pollTimer`'s `active` and `refreshPlayer`'s, the unload
  timer's and `call()`'s dormant answer) and the menu's loaded filter
  over `isLoaded` stay as they are.

### SR, round 23 (2026-11-26)

Safety: one critical, one high, two mediums; fit: one medium (latent test
safety), lows. The reviewers' reports are kept outside the repo.

- [x] SR242 (critical, safety F1) An episode left with an unsent place
  (`unsentPlaces`), of a show you don't follow, whose lookup comes back
  empty and that In Progress omits: Play from a list starts it from the
  public list at 0 (pushed over Pocket Casts' 20) and drops the place
  (verified). An unsent or pending entry is a record seen, as `recordSeen`
  is for the last episode; also Next/autoplay and the resume check's
  switch (read).
- [x] SR243 (high, safety F2) Autoplay past an Up Next entry that left its
  feed records the wrong top (`at_top=removed`): every later resume check
  reads the gone entry as "another device moved on", can't follow it, and
  says unverified for good; nothing is pushed for the rest of the episode,
  and after Stop, Play says Up Next is empty (verified).
- [x] SR244 (medium, safety F3) `cmd_login` stores the new tokens before
  ending the player and dropping playback.json: a call cut off between
  leaves the other account's playback under the new session (simulated).
- [x] SR245 (medium, safety F4) "Unverified" is silent however long it
  lasts: no push is tried, so `syncFailed` never says so.
- [x] SR246 (lows, safety F5-F6) `retry_unsent` drops a place it can't send
  (no show id) silently; right after a sign-in (cache dropped) an empty show
  list reopens round 22's M1.
- [x] SR247 (tests, safety) The reviewer's surviving mutants M4 (the
  adoption forcing "in progress") and M14 (`paused_push_stands` ignoring a
  mark made since the failure); the fake's `/user/token` answers the first
  account whatever signed in; Up Next sync data without `playingStatus`
  unless `syncStatus`.
  Fixed: one rule in `resolve_episode` (`record_held`: a record seen, or
  any place Pocket Casts had, the last episode's, an unsent place's or a
  pending end's), replacing round 21's two call-site checks; autoplay
  queues what it plays at the top, and the resume check passes over a top
  gone from its feed; the sign-in compares and drops before storing the
  new tokens, and the same account keeps its show list; an unverified
  check counts toward "not synced", and Play's asks again at the next
  poll; a place that can't be sent stays stashed; the fake's token
  refresh answers the account that signed in; tests kill M4 and M14.
  Left: the fake's Up Next sync data omits `playingStatus` unless
  `syncStatus` (five tests cover the real shape).
- [x] SR248 (medium, fit M1) `assert_sandboxed` checked the environment's
  strings, but a relative HOME or runtime folder falls back to the real
  ones in the bridge (`scrub_environment` off in `run_bridge`): it now asks
  the bridge's own resolvers (tested with relative values).
- [x] SR249 (lows, fit L1, L2, L5) A replacement bar's own copy went to
  sleep for good when a screen came back after none (held by its panel
  now: `claims: 1`); a failed one-time import was silent (said once now;
  still not retried in the shell, by design); mpv going away bringing a
  read, tested. The node check for the poll interval now needs it just
  over the bridge's SYNC_INTERVAL. The private path in round 22's notes
  removed; tests/mutations.md's count.
- [ ] SR250 (left, fit L3-L4 and test gaps) Lazy panel content (SR181);
  SR234; the panel opening without `refreshIfStale`, Up Next on another
  tab, Settings clearing an old save error, Enter on a show row, a broken
  cover; the stand-ins' PanelSlider `liveValue`, Button `enabled`,
  `Quickshell.env` "".

### SR, round 24 (2026-11-26)

Safety: one critical by outcome (two faults), one medium, two lows; fit: no
critical, high or medium, five lows. The reviewers' reports are kept
outside the repo.

- [x] SR251 (critical, safety F1) `check_server` decides the loaded
  episode's empty record with its own older rule (`recordSeen`, followed,
  listed elsewhere), not `record_held`: an episode started from Up Next's
  sync data (no `fromRecord`) whose pushes all failed, finished on the
  phone, then a 404: Play said "same" and the next push sent 0:13 in
  progress over "played" (verified; also through Next).
  `empty_lookup_answers` has the same narrow rule. Fix: `record_held` in
  both (or `recordSeen` for a place from sync data).
  Fixed: one rule, `record_must_exist` (record_held, a followed show, a
  place listed elsewhere), asked by `resolve_episode`, `check_server` and
  `empty_lookup_answers` (which keeps its loaded-episode condition);
  `record_held` takes the caller's state. Tests: both of the reviewer's
  paths, plus a pending end from Up Next's place retried on an empty
  lookup (it was marked played over the phone's 60); all three fail on
  the unfixed code. Every other empty-lookup site refuses already
  (`paused_push_stands`, `retry_unsent`, `reopened_elsewhere`).
- [x] SR252 (medium, safety F2) A place played in an episode Pocket Casts
  has no record of is never sent after a failed push (`paused_push_stands`
  and `retry_unsent` wait for a record that never comes; dropped after the
  hour). Fix: an empty lookup is "no place anywhere" for an entry left at
  0 unplayed when nothing else knows a record (`empty_lookup_answers`'
  rule), so `where_left` stands.
  Cody, 2026-11-26: documented, not fixed (README Known limits). It loses
  only what played here, and the fix treats an empty lookup as an answer,
  the move behind every recent critical.
- [x] SR253 (low, safety F3) `record_held`'s refusal never ends for the last
  episode Pocket Casts truly forgot: Play says "try again" for good. Say
  which and how to move on.
  Fixed: "Pocket Casts sent no record of “<episode>”: try again, or play
  another episode" (Next still moves on: tested); resolve_episode's own
  refusal says "sent no record of that episode", not "didn't answer".
- [x] SR254 (low, safety F4) `pushFailures` mixes unverified checks with
  failed pushes; an answered check doesn't reset it. Reset on any answered
  check and any landed push.
  Fixed: `pushed()` (every landed push) and the resume check's "same"
  reset it ("finished" and "switched" start a fresh state anyway).
- [x] SR255 (tests, safety T3-T4) Mutants: `record_held` without its
  pendingFinish clause survives everything (the reviewer's
  `test_r24_a_pending_ends_place_makes_an_empty_lookup_no_answer` kills
  it); Play's unverified check not setting `checkServer` survives (test:
  one poll within 90 s asks). README Known limits: the remaining
  empty-lookup case for an unfollowed show another device played, listed
  nowhere (starts from the public list at 0).
  Fixed: both mutants killed (the T4 test pauses by a media key no poll
  saw, so nothing else had set `checkServer`); the Known limit added,
  with SR252's. Nine mutations re-pointed at the one rule, five added; one
  re-pointed survived (the rule without "a show you follow": its test's
  episode is now held by its Up Next place), killed by a new test with
  the followed show alone.
- [x] SR256 (fit, lows) The sandbox test replaces the bridge while it checks
  the refusal (with the check mutated away, `status` had run read-only
  against the real state folder and player socket; nothing was written:
  checked by the files' times); the 1.0 import's message says to restart
  the shell; a leftover owed guard stop cleared once no guard runs (tested);
  stale statements (About's "10-minute list", four processes, the 1.0
  import's reading of "false", the rule docstring vs SR234); README: the
  sign-in fields take keys and pastes only; tests for the fit reviewer's
  surviving mutants (buffering place, skip clamp, the chip IPC's
  "unhandled", an "unknown" DRM port, the bridge's control-character check).
- [ ] SR257 (left, fit) `hyprctl repl`'s reply ignored (SR234); the stand-ins'
  Socket (the real one also emits `error` on a hang-up) and Process (keeps
  `running`/`processId` until `exited` after a stop).

### SR, round 25 (2026-11-26)

The first round since 19 with no critical or high from either reviewer.
Fit: six lows, nits, test gaps. Safety: four lows, a nit, three
surviving mutants. The reviewers' reports are kept outside the repo.

- [x] SR264 (low, safety F1; verified by fault injection) Two paths rested
  on a player stop nothing checks (`quit_mpv` returns after 3 s either
  way): the resume check's "finished elsewhere" set `handledEnd`, so a
  player that outlived the quit took the phone's "played" for its own end
  and play again pushed in progress over it; the poll's carried retry left
  an ordinary paused episode whose next poll pushed its place over the
  phone's. Fixed: "finished elsewhere" never sets `handledEnd`; both
  leave the episode unconfirmed (`checkServer`, `unconfirmed`) before the
  quit. Tests: both, with the quit failing.
- [x] SR265 (low, safety F2) Next took the loaded episode off Up Next
  before it knew what was next; an entry without an answer stopped it, the
  episode stayed "at the top", and every resume check after read the entry
  as another device's move: unverified, nothing pushed. Fixed: Next
  resolves first, and names the entry that stopped it. A top whose lookup
  refuses is still no answer for the resume check (unverified, said): the
  safe direction, left.
- [x] SR266 (low, safety F3) Play with nothing loaded took a top gone from
  its feed for another device's move ("Up Next is empty" over the episode
  in progress): passed over now, as the resume check does.
- [x] SR267 (low, safety F4) The Known limits and "one rule" were narrower
  than the code: the odd-empty-answer case also sends this machine's place
  on a resume or a reload, not only 0 on a start (README restated); a list
  that comes back as nothing at all (a 200 not JSON or empty, read as {})
  is "can't tell" now, not "listed nowhere" (tested with the fake's new
  `oddReply`); the no-record limit says a reload sends the place (pinned
  by a test); CLAUDE.md names the three sites with a stricter rule.
- [x] SR268 (nit, safety F5) Mark and queue checked "the loaded episode"
  outside the state lock (a Play of the same episode could load it in
  between): both under it now; `forget_pending` folded into `cmd_queue`.
- [x] SR269 (tests, safety) The reviewer's survivors: `had_place`'s status
  leg (a place in progress at 0), `same_account`'s "no earlier session"
  (a sign-in after a half-done sign-out), a load from the record as a
  record seen: each has a test that kills it.

- [x] SR258 (low, fit L1) A setting changed before the one-time import
  landed (it failed, or was still on its way) made settings.json with that
  key alone: the 1.0 entry (autoplay off) was never brought in, and the
  failure's "restart the shell to try again" imported nothing. Fixed: the
  change carries the entry (`settings set --entry`), and the bridge brings
  it in first, in the same save, while no file is there and none was
  imported; the message says a change or a restart tries again. Tests:
  the bridge's two cases, the service passing the entry until stored.
- [x] SR259 (low, fit L2, L4, L5, N4; test gaps) A stop owed with no guard
  running (chip.qml: a guard's SIGTERM from outside after a retry wait);
  dbus-monitor's `--pdeathsig` (the argv pinned); a list answer from before
  a sign-out, and the loaded episode's menu, by behaviour (only source
  patterns had them); the volume debounce across two ticks; a talking
  socket resets its retry count; a failed paste said; closing the panel
  closes the Settings page; the arrows don't move the list behind a menu;
  Legato's own stop of a guard on the real Quickshell (RealQuickshell).
- [x] SR260 (low, fit L6) The Omarchy stand-ins were hand-written copies
  nothing compared: a node check now fails when a stand-in declares a
  property, signal or function Omarchy's own component doesn't (four
  test helpers named).
- [x] SR261 (nits, fit N1-N3) Play (the transport, space) at an end showed
  "Finished" under a pause glyph while the resume asked (round 21's fix
  was in playItem only): it clears `ended` too. The chip's IPC refresh,
  broadcast to every screen's chip, forced every panel's lists on the one
  service: open panels reload what they show, and with none open the
  service reads its status once. The import's unreachable
  `settingsWritable` check gone (folded into `entryToImport`).
- [x] SR262 (claims, fit) "The 1.1 bridge parses every call 1.0 makes"
  tested (`OldServiceCalls`: every argv shape of tests/qml/v1_0, checked
  against the file); README: dimmed text on a light theme reads darker,
  and a panel opened five minutes after the last status read applies
  settings too.
- [ ] SR263 (left, fit L3, N5, N6) The Settings and Stats pages take the
  mouse only (README says so; keyboard use of the pages is a design change
  for after 1.1.0); the bridge compiled at every call (SR141); comments
  that narrate review history.

### SR, round 26 (2026-11-26)

Verifying round 25's fixes. Safety: no critical or high; one medium (a
second door into round 25's F1 class), three lows, nits. Fit: no
critical, high or medium; three lows, five test gaps (one medium,
security-relevant), nits. The reviewers' reports are kept outside the
repo.

- [x] SR275 (low, fit L1) One Next loaded Up Next twice with the panel
  open (its callback's reload on top of the new episode's) and once for
  nobody with it closed: stale now, loaded only for an open panel and
  only if not already loading.
- [x] SR276 (low, fit L2) An mpv emptied by something else (an MPRIS Stop:
  `playerctl stop`) stayed resident with its feed proxy for good: the next
  event's poll closes it (close_player).
- [x] SR277 (low, fit L3) A session that expired mid-episode read as
  "Pocket Casts not reached" (a refused periodic push counted as a failed
  one), the chip carrying on signed in: the poll says `sessionExpired`,
  and the service shows the sign-in card and says so once.
- [x] SR278 (tests, fit T1-T3, T5) Rule 6's `--no-config`, `--ytdl=no` and
  `--clipboard-backends-clr` asserted on the main player (without
  `--ytdl=no`, a load the feed proxy refused went to yt-dlp, which fetched
  it directly); the owed-stop rule on the real Quickshell (a stop and a
  restart in one tick: the round 25 test passed without it); NVIDIA hidden
  only when another GPU is seen driving; CLAUDE.md says what the timer
  check covers. The start watchdog's second guard (`began`, unreachable)
  removed.
- [x] SR279 (nits, fit N1-N4) BarWidget's comment (the panel is built at
  load, on every screen); SR225's note; README's keys (`h` `j` `k` `l`);
  stale `/tmp/pc-bridge-*` homes removed.
- [ ] SR280 (left, fit T4, N5 and older items) `isOpen` across screens
  (SR227); a resident Python sleep guard per loaded episode (~40 MB; QML
  could start the bridge only on PrepareForSleep); SR181, SR141, SR263,
  SR153/SR186, SR234/SR257, SR197/SR165 as before.

- [x] SR270 (medium, safety F1; verified by fault injection) Round 25
  made two closes leave the episode unconfirmed before the unchecked
  `quit_mpv`; three more didn't: finish_current's unwatched close (a
  surviving player still at its end had that end judged again as one
  watched here, fresh from its `synced`, and marked played over the
  phone's 50, or, after an unanswered read, without asking), resume_loaded's
  close when the end was reopened elsewhere (the same, when resume_last
  failed), and stream_stopped's (by reading). Fixed as a class: every close
  of an episode playback.json still names goes through `close_player`
  (unconfirmed first, then the quit): those five, Stop, the stray file's
  and a failed load's; only the sign-in and sign-out, which drop the state,
  quit directly, and a static test pins the callers. Tests: the three new
  doors with the quit failing. (`synced` at an unwatched end left as it
  was: with the flags it's moot, and moving it was a second layer.)
- [x] SR271 (low, safety F2) Next took the episode off Up Next before the
  next one's load, which can still fail (a local feed with local feeds
  off, the proxy, mpv): every Play and poll after failed the same, nothing
  pushed. The removal follows the load now.
- [x] SR272 (low, safety F3) The resume check passed over a gone top only
  for shows you follow (an unfollowed show's says "not found"): every
  check said unverified, and "not synced" was said though Pocket Casts
  answered. "Not found" plus `left_its_feed` is gone too.
- [x] SR273 (low, safety F4) The feed proxy's "public" included global
  IPv6 addresses in this machine's own network (a home router, a NAS): a
  feed's redirect reached them with local feeds off. Those count as the
  local network now (`interface_prefixes`, /proc/net/if_inet6); README:
  a router's own public IPv4 can still be reached, as from any web page.
- [x] SR274 (nits, safety N1-N3) README's odd-empty-answer limit names
  which episodes this machine remembers; N2 (a non-empty odd list reply,
  `{"episodes": null}`) left: the real empty lists' shape was never
  checked live, and guessing it wrong refuses every unfollowed episode
  while Up Next is empty; N3 moot (above).

### SR, round 27 (2026-11-26)

Verifying round 26's fixes; the third round running with no critical
or high from either reviewer. Fit: test gaps and nits. Safety: two
mediums, three lows. The reviewers' reports are kept outside the repo.

- [x] SR284 (medium, safety M1) A session that expired while paused (a
  password changed on the phone): Play's resume check took the refusal for
  "unverified", played on unsynced, said "Pocket Casts not reached", and
  what played was lost at the next close. The check lets `reauth` and
  `signed_out` through: Play fails with it (nothing plays), the poll's
  check too, and the service asks for the sign-in, said once whichever
  call found it.
- [x] SR285 (medium, safety tests) close_player's `unconfirmed` was pinned
  by no test (the poll's paused push checks it, not checkServer: a drag
  back on a player that outlived its quit pushed 29 over the phone's 50):
  tested. The two closes of a hung player went around close_player (one
  set checkServer only, Stop's nothing): through it now (`hung=True`); the
  static test pins `end_hung_player`'s callers too and that no quit is
  sent another way.
- [x] SR286 (low, safety L1) An end reached right after a stall no poll had
  handled was judged "watched" and marked played over the phone: the poll
  leaves it unconfirmed first, so the record is read.
- [x] SR287 (low, safety L2) "Finished elsewhere" with a gone entry on top
  said "Up Next is empty" over valid entries: Play goes on as with nothing
  loaded (past a gone top).
- [x] SR288 (low, safety L3) Next with nothing loaded took the last episode
  off Up Next wherever it sat (the phone had moved on): it skips it only
  while it's Up Next's top.
- [x] SR289 (nit, safety) README: an odd answer with a record but no place
  counts as an empty one.
- [ ] SR290 (observation, left) A stop judged a break isn't remembered: a
  player that outlived its quit is judged again by the next poll; the
  evidence model makes the second verdict the better-informed one.

- [x] SR281 (low, fit L1-L3: test gaps) The decoder moved off a hidden
  NVIDIA GPU (`--hwdec=vulkan,vaapi`), asserted on a new player's command
  line; Up Next loaded when the panel opens on another tab after the
  status went stale; a signed-out opening reads the status again; the
  service's IPC refresh reads it; the cursor stops at the list's ends.
- [x] SR282 (nits, fit N3) README: a plugin reload with an episode loaded
  starts the pause-before-sleep helpers again; the sleep guard's 4 s is per
  request (10 s in all); tools/sample-bridge.py's CPU figure matches.
- [ ] SR283 (left, fit N1, N2) Layered guards that hide each other (the
  unload timer's `active` and refreshPlayer's, behind call()'s "dormant";
  the QML "never" check behind the bridge's, which saves a process per
  pause): kept, not in the mutation set; notifications with no icon
  (Omarchy's own sender takes a glyph); README's How it works and Known
  limits read as review notes (a rewrite for users before the release).

## Testing

- `tests/run` before every commit: all suites, about 23 minutes, nothing on
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
  against every shape the safety reviewer built. 258 Python + 37 node
  tests.
- 2026-11-24 (evening): Cody's calls before round 10 (no round cap; front-
  load the code): SR86 settings in settings.json (bridge-written, the bar
  entry copied in once, a broken file never saved over) and SR63 the
  shell's service dormant until a panel claims it (a replacement bar's
  panel runs its own; the IPC target only on the live copy). 266 Python +
  38 node tests and the new offscreen tests/qml/service.qml; 249 mutations
  listed. Round 10 next.
- 2026-11-24 (night): round 10 (SR87-SR103): only the recorded file's
  position is pushed (a high since 1.0); Pocket Casts' answer wins over an
  unconfirmed stretch; empty lookups and missing sync data never start at
  0; the shell's service released when its panel goes, and the bridge acts
  on settings.json itself; keepLoaded dropped and a 1.0 service under the
  1.1 panel handled (the update keeps it once); the pages scroll. The
  reviewers' 17 surviving mutants and round 9's 4 caught (the real
  BarWidget loaded, stand-ins that read files and fail starts). 285 Python
  + 40 node tests; 294 mutations, the 59 new or changed all killed (the
  full run with round 11). Round 11 next.
- 2026-11-24 (late night): round 11 (SR104-SR121): Play and a drag back on a
  file Legato didn't record never act on the recorded episode (a high);
  a drag back after an end stays played; a stale finish never overrides
  the phone; a record without a position is no answer (live: records
  always carry one, Up Next's sync data doesn't for episodes not
  started); pause before the lock; the settings list out of
  barWidget.schema; the fit reviewer's QML survivors tested. The full run
  of round 10's set: 293 of 294 (a redundant flag, removed). 296 Python +
  41 node tests; 322 mutations, the 39 new or changed all killed (the full
  run with round 12). Round 12 next.
- 2026-11-24 (late night): round 12 (SR122-SR134): the resume check's seek
  counts as a new start (a high); pending finishes saved with the end and
  retried by Play; an unchecked media-key stretch never kept; nothing sent
  across a suspend; panels hold no rows while closed; touchpad scrolls;
  1.0's kept service no longer forces autoplay off. 309 Python + 43 node
  tests; 352 mutations, the new and changed all killed (the full run with
  round 13). Round 13 next.
- 2026-11-24 (night, last of the session): round 13 reviewed (SR135-SR142,
  not yet fixed): no critical or high from either reviewer for the first
  time; three safety mediums (a gap's stretch over a phone that went back,
  a Play across a suspend, a pending-removal episode replayed from 0) and
  three fit mediums. Round 12's full run: 350 of 352. Next: fix round 13,
  then round 14.
- 2026-11-24 (night, after the handoff): round 13 fixed (SR135-SR142): the
  one local place kept over Pocket Casts' answer is a failed push's; any
  suspend is a gap, and a Play across one loads paused; nothing that picks
  "what's next" replays an episode that ended here; an end nobody watched
  asks first and starts nothing; hosts without ranges reload on a refused
  seek back; the panel's sliders add touchpad deltas up (tested with real
  wheel events); ShellIpc and Omarchy's panel route; the Process stand-in
  keeps `running`'s binding as Quickshell does. 340 Python + 45 node
  tests; 403 mutations, the 65 new or changed all killed (three only
  after their tests were fixed: two that never reached the rule, one
  whose premise was off). Round 14 next.
- 2026-11-25 (night): round 14 (SR143-SR153): one high (a place this
  machine couldn't send was lost once the player closed): the keep moved
  to reloads of the same episode, kept only while nobody else has written
  since (simpler, and a write elsewhere now always wins). An end on an
  unchecked resume asks first; Pocket Casts' https suspend check tested;
  the sleep guard waits out a Play in flight. A reviewer's sandbox fell
  back to the real home and acted on Cody's account (restored with his
  OK): the bridge now refuses an unusable home instead. Episodes gone from
  a rolling feed no longer stop Play. Updates run the old QML until a
  restart (measured): docs corrected, and from 1.1 on the panel says so.
  Real keys through Omarchy's own key catcher in the QML tests. 357
  Python + 47 node tests; 434 mutations. Round 15 next.
- 2026-11-25 (overnight): round 15 (SR154-SR173): two highs, both second
  doors: a place this machine couldn't send was lost on a switch to
  another episode (now carried along, sent once Pocket Casts can be told,
  and a reload of it starts there), and an unwatched end whose record read
  failed was played again from 0 over the phone (now not "ended here":
  the player closes, Play asks). Next/autoplay/the switch skip episodes
  Pocket Casts says are played; the feed proxy refuses this computer's own
  other addresses; errors show over the restart note; a failed poll after
  an mpv event is retried; the wheel seeks relative; Alt+letter isn't a
  panel key. The Process stand-in sends `exited` on a stop, as Quickshell
  does (probed by the fit reviewer). Round 14's full mutation run: 432 of
  434 (2 skipped: renamed tests, re-pointed). 382 Python + 47 node tests;
  480 mutations, round 15's 63 new or changed all killed (one after its
  test was tightened, one after a redundant guard was removed). Round 16
  next (round 15 had highs).
- 2026-11-25 (morning): round 16 (SR174-SR186): one critical, the second
  door into round 15's fix: a place whose push failed outlived a resume
  check that took the phone's place, and a reload or a switch pushed it
  over the phone (four paths verified). The unsent place now carries its
  base (`left`) and holds only while `lastSyncPos` is still that: one gate
  for every reader. Marks are a say over a place left unsent; an end gone
  from its feed no longer blocks Play; Play on the loaded row resumes it.
  Fit (no crit/high): the deadline's exemptions tested; settings and stats
  writes in order; awake whenever there's no screen; 1.0's out-of-range
  values clamped; README figures; an unreleased project's name out of the
  public files. 396 Python + 47 node tests; 498 mutations, round 16's 31
  new or changed all killed (two after a redundant layer was removed, one
  after its test was tightened). Round 17 next (round 16 had a critical).
- 2026-11-25 (day): round 17 (SR187-SR198): fit no crit/high; safety none
  above medium but F2 rewinds the phone (Play at a told end, the phone
  back in it): Play asks first now. The switch reads a played record;
  `lastSyncPos`/`lastSyncStatus` stay Pocket Casts' until the load's push
  lands, and "unplayed" is a mark only if Pocket Casts had it otherwise;
  a handled end isn't judged again; a landed push counts as a record
  seen. Fit: the last episode's row plays it (it sent "resume"); the
  write watchdog removed. Cody: a relative XDG variable is ignored as the
  spec says (only a bad HOME stops a call). A run was stopped once by the
  machine running low on memory (not the suite's doing). 409 Python + 47
  node tests; 510 mutations, round 17's 28 new or changed all killed (two
  after their tests were tightened). Round 18 next (round 17 had a rewind).
- 2026-11-25 (afternoon): round 18 (SR199-SR210): fit no crit/high (drag
  and idle-unload tests, an empty HOME refused on the plugin's own path,
  the ended row, Settings toggles at once and in order); safety two
  criticals, both more doors into "play again": every way back into an end
  handled here asks first now (`end_still_stands`), a pending finish must
  get an answer; the check adopts only after its seek; lastSyncPos is
  Pocket Casts' place whatever the start; lows (a self-check under way, a
  mark under the lock, the sleep guard's mark). A scratch HOME's limits
  documented, not enforced (refusing would refuse real setups). 418 Python
  + 47 node tests; 526 mutations, round 18's 30 new or changed all killed.
  Round 19 next (round 18 had criticals).
- 2026-11-25 (evening): round 19 (SR211-SR220): the first round with no
  critical or high from either reviewer. Fixed before release all the
  same: a played episode replayed here keeps a place it couldn't send
  ("played" is a mark only if it wasn't already), an Up Next entry without
  a status reads its record, a push whose reply was lost isn't another
  device's write (`triedPushes`), the guard marks the sleep first; fit: the
  menu's Play at an end, failed saves said, the sleep mark spent by its
  suspend, the Process stand-in's `exited` as Quickshell sends it (probed:
  later, even after a restart) and the guard's `onExited` taking signal 15
  for a stop. 427 Python + 47 node tests; 541 mutations, round 19's 35 new
  or changed all killed. Round 20 to verify these (four rounds of fixes in
  the sync engine each opened a door the next round found).
- 2026-11-25 (night): round 20 (SR221-SR227), the verification round: it
  found a critical in round 19's own `triedPushes` (a phone that stopped
  near a place tried here was overwritten): withdrawn, the lost reply a
  documented limit (README); a replay played to its end drops its old
  unsent place. Fit no crit/high: the guard's start watchdog, the queued
  re-read, a control-character HOME refused, Omarchy's MIT notice on the
  copied key catcher. 431 Python + 47 node tests; 546 mutations, round
  20's 17 new or changed all killed. Round 21 next (round 20 had a
  critical).
- 2026-11-25 (late night): round 21 (SR228-SR234): two safety criticals,
  both second doors: a failed pause's place re-sent blind by Stop, Next,
  a switch, Pause again, a seek or any event's poll (now only after the
  record says Pocket Casts still has it where this machine left it), and
  Play from a list ignoring `recordSeen` (`record_lost`, on both ways
  back in); a landed mark notes a record; a push that sent nothing, a
  redirect and a clock stepped back no longer read as landed or fresh.
  Fit: round 20's guard watchdog never ran on the real Quickshell (keyed
  on `guardWanted` now; `RealQuickshell` runs the block there); per-setting
  save errors; Play at an end not ended meanwhile; tests for the
  reviewer's surviving mutants. Cody: the commit author's address is
  accepted. 444 Python + 47 node tests; 565 mutations, round 21's 24 new
  or changed all killed. Round 22 next (round 21 had criticals).
- 2026-11-25 (late night): round 22 (SR235-SR241): safety: another
  account's sign-in inherited the last one's places (dropped now unless
  it's the same account), an empty show list read as "follows nothing"
  (the last list that loaded decides); fit: the bridge tests ran with the
  real HOME (the whole file is sandboxed now), a guard killed by someone
  else never came back, the Socket stand-in, test gaps, `mutate.py
  --confirm`. 450 Python + 47 node tests; 581 mutations, round 22's 22
  new or changed all killed (with --confirm; one re-anchored after it
  survived in a harmless form). Round 23 next (round 22 had highs).
- 2026-11-26: round 23 (SR242-SR250): safety: an episode left with its
  place unsent restarted from the public list at 0 (one rule now,
  `record_held` in `resolve_episode`); autoplay past an entry gone from its
  feed stopped every later push (queued at the top; the check passes over
  a gone top); the sign-in's order; unverified said. Fit: the tests'
  sandbox check asks the bridge's resolvers; a replacement bar's own copy
  held by its panel; a failed import said. 458 Python + 47 node tests;
  592 mutations, round 23's 19 new or changed all killed (--confirm; one
  needed its test list completed). Round 24 next (round 23 had a
  critical).
- 2026-11-26 (night): round 24 (SR251-SR257): safety: the resume check
  and a pending end's retry kept their own older rule for an empty
  lookup, so an episode started from Up Next's place, its pushes failing,
  confirmed "same" and pushed over the phone's "played" (one rule now,
  `record_must_exist`, asked by every path); "try again" for good on a
  last episode Pocket Casts forgot (said as it is, naming it); the
  failure count ends with any answer; two cases documented, not fixed
  (Cody). Fit: lows (the sandbox test, stale statements, the 1.0
  import's message, a leftover owed guard stop). 467 Python + 47 node
  tests; 598 mutations, round 24's 15 new or changed all killed
  (--confirm; one re-pointed needed a test with the followed show
  alone). Round 25 next (round 24 had a critical).
- 2026-11-26 (small hours): round 25 (SR258-SR269): no critical or high
  from either reviewer, the first such round since 19. Safety lows: a
  player that outlived its quit after "finished elsewhere" or a carried
  retry could push over the phone (both unconfirmed first now; "finished
  elsewhere" no longer "ended here"); a half-done Next stopped syncing
  (resolves first); Play passed over no gone top; odd list replies read
  as "listed nowhere"; the Known limits restated; Mark and queue under the
  state lock. Fit lows: a change before the one-time import loses it
  (carried now); the IPC refresh forced every screen's lists; Play at an
  end showed "Finished"; stand-ins checked against Omarchy's components;
  1.0's calls parsed; a dozen test gaps. 481 Python + 48 node tests; 625
  mutations, round 25's 40 new or changed all killed (--confirm). Round 26
  next, to verify round 25's fixes (round 20 found a critical in round
  19's).
- 2026-11-26 (early morning): round 26 (SR270-SR280): no critical or high
  from either reviewer, the second round running. Safety: a medium, three
  more closes trusting the unchecked quit (one marked an episode played
  over the phone): every close of a named episode goes through
  `close_player` now, a static test pinning the callers; Next removes
  after the load; an unfollowed show's gone top; global IPv6 in this
  machine's own prefixes is the local network. Fit: Next loaded Up Next
  twice; an mpv stopped from outside stayed resident; an expired session
  read as "not reached"; rule 6's flags, the owed stop on real Quickshell
  and the GPU choice now tested. 491 Python + 48 node tests; 639
  mutations, round 26's 21 new or changed all killed (--confirm). Round 27
  next, verifying round 26's fixes.
- 2026-11-26 (morning): round 27 (SR281-SR290): no critical or high from
  either reviewer, the third round running. Safety: two mediums (an
  expired session found at Play played on unsynced under "not reached":
  Play now fails with it and the sign-in is asked; close_player's
  `unconfirmed` untested, and a hung player's two closes went around it),
  three lows (an end right after an unhandled stall marked played
  unasked; "finished elsewhere" over a gone top said Up Next was empty;
  Next with nothing loaded took the last episode off Up Next anywhere).
  Fit: test gaps (the decoder on a hidden NVIDIA GPU, Up Next on another
  first tab, a signed-out opening, the IPC refresh, the cursor's ends),
  wording. 498 Python + 48 node tests; 650 mutations, round 27's 16 new or
  changed all killed (--confirm; one re-pointed survived, Next ignoring an
  end here hidden by Pocket Casts' "played", until a test with the mark
  failing too). The loop stops here (Cody's rule: a
  round with no critical or high, and the author comfortable; three
  running). Next: SR234's live check with Cody, then H6.
- 2026-11-26 (morning, with Cody): SR234 checked live (the newest of the
  piled-up video rules wins: six re-sends and a drag). Next: H6.

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
