# Mutation checks

A green suite proves little unless it would go red with a bug put back.
`tests/mutate.py` plants one-line regressions in the 1.1 code, one at a
time, in a temporary copy of the repo (the working copy is never touched),
and runs the tests meant to catch each. A mutation that passes them is a
**survivor**: behaviour the suite doesn't really check.

```bash
tests/run                          # first: a green baseline (a red one "kills" everything)
python3 -B tests/mutate.py .       # all of them, about 2 hours
python3 -B tests/mutate.py . "broke: no time check"   # one, by name
```

Each mutation runs its own tests, not the whole suite (526 x 5 minutes is
too long); when a mutation survives, run `tests/run` on it before believing
it. A mutation whose pattern no longer matches the code is reported STALE
and fails the run (fix its pattern), as does one whose tests fail
unmutated (SKIP).

## The set (526; strict review rounds 1 to 18, 2026-11-25)

The full list, with each mutation's pattern and tests, is in
`tests/mutate.py`. The runner first checks each test set passes unmutated
(a red baseline would count everything as killed) and names the test that
caught each mutant. By area:

- **Broken stream vs the end**: the watcher's evidence (reconnect lines,
  its warn level, its cut, a
  reconnect that read on, a size without a cut, the load's size, players
  without the watcher, the property read at an end, the script loaded at
  all) and the watcher's own Lua (unknown sizes, other components' lines,
  the reset per file); the no-size margin, its outro and which durations
  count; polls filling in the record; Play's own check and its reload.
- **Where it starts and the floor**: at the listed end never "from the
  top"; the skip-outro only when mpv's duration agrees; the floor from a
  load and from the resume check's seek, lifted by a seek only from an
  honoured start; nothing-more only just after an unseeked start.
- **The broken stream's push and the resume after it**: after a long gap,
  while unconfirmed, before the check; Pocket Casts further on winning
  after the player closed, and a further unsent local position kept.
- **Play's quick check and sign-in**: short only on Play, never cutting a
  refresh short, no refresh before sleep and no wait for its lock, the
  guard's own deadline, the deadline held while a refresh is stored, a
  stale call never flagging a new session, the 5 s value.
- **Hosts without ranges**: judged by reading to the size, with mpv's
  `seekable` read at the end; an end far from the size, or past it.
- **Stalls and resumes**: a stall is an interruption (no push by a pause,
  stop or the break; a check once it heals; the watcher's timing), no
  push while buffering, keepalive on feed connections, a media-key resume then Stop pushing nothing unchecked, a
  finished episode never restarted.
- **Listening stats**: the seek flag and its bound, the speed and Trim
  matches, the bounds, the gap, buffering, another file, a pause, errors,
  skips counted as gone (not as asked), the counts around pause, speed,
  switch and stop, the lock cap, off, clear and its lock, intro and outro.
- **skip-taskbar and the video rule**: the untag rule, the pin match, the
  rules sent before the pin, o.window only once (run against Omarchy's
  real helpers.lua).
- **QML**: the round 2 fit reviewer's ten (keys behind the Stats page, its
  stats, height, visibility, the date, plain-text errors, the broken-stream
  report, the seek flag, the stats read, BarWidget's IPC) and the page
  counts, against the real Panel and Service (`tests/qml/panel.qml`); round
  4's: Delete and the keys behind a page (now signed in, with a control),
  a stale poll's messages, late switch and Clear answers, the switch's
  default, message lengths, the off-and-empty text.
- **Round 13**: the one local place kept being a failed push's (any
  unpushed place, what played since it, its record, its age, recorded
  from a call that slept, kept after a push went through, taken for
  unasked-for motion); a suspend as a gap (ignored; a call's own sleep
  recorded as now); a play across a suspend (starting, a sleep during the
  load, Play and Play again unpausing); an end nobody watched (told at
  once; overtaken elsewhere yet kept ended); the retry's record (a
  restart elsewhere, a lost reply's mark, an empty lookup); a replay
  keeping its pending finish; "what's next" skipping ended episodes (the
  rule and each caller, the resume check's top); a followed show read as
  unfollowed; an unsafe verdict file; the HLS margin; a refused seek back;
  a malformed playback.json; hyprctl's timeout and the rule before a
  load; and the QML ones (the guard's restart, mpv's events, the IPC
  status, re-sign-in, the idle unload, ticks while buffering, Esc, Tab,
  closing's password and show page, the chip's click and IPC, ShellIpc,
  the sliders' wheel, rows through the fade, animations off).
- **Round 15**: places left unsent by a switch (dropped, ignored by a
  reload, sent over another device's move or a played episode, kept past
  the hour, never sent by the switch or a poll) and a kept reload's own
  record (its unsent place, its comparison with Pocket Casts' place); an
  end Pocket Casts couldn't confirm (kept "ended here", skipped or
  replayed by Play, confirmed never said, a watched end unconfirmed, a
  carried retry leaving it ended or the player at its end, Play at a
  pending end unasked, the poll or a seek reopening it, an empty lookup
  never settling one with no record, or settling one with a record); played episodes picked by Next (sync
  data, record) and the switch; Mark played's failed removal forgotten;
  queueing again or Mark unplayed keeping a retry; the proxy reaching this
  computer by another address; NaN and negative positions; an empty HOME;
  and the QML ones (errors under the restart note, a cancelled paste
  reported, a stopped guard waiting, dormant with no screen, Up Next
  fetched for no panel, Alt+letter, the menu's marks, Enter and Esc with
  the menu open, `4`, ←, the password kept, the wheel's absolute seek, a
  failed poll after an mpv event never retried, the self-check in /tmp).
- **Round 16**: an unsent place outliving a resume that took the phone's
  place, or carried from its old base; marks (played, unplayed) not a say;
  a mark keeping the places left unsent; an end gone from its feed never
  settled; `kept_elsewhere` without its "where left" or its hour; an empty
  lookup answering for a show you follow; the deadline on the sleep guard,
  the proxy, or nothing; 1.0's values past the range dropped; and the QML
  ones (writes racing, a copy left asleep when
  the screens go, or awake for good after; signed out, a poll all the
  same).
- **Round 17**: the switch following Up Next to an episode its record says
  is played, or staying when another device finished this one; Play at a
  told end playing it again unasked, or taking no answer for "played";
  Play with nothing loaded skipping a told end whatever its record says;
  a load's unpushed start taken for Pocket Casts' place, or its landed push
  never recorded; "unplayed from the start" read as a mark; a landed push
  not a record seen; an ended episode stashed; a record without a place
  taken for one by the unsent retry; the adoption not taking the phone's
  place; a relative XDG value stopping the call (the spec ignores it); and
  the QML ones (the last episode's row resuming with nothing loaded; a
  waiting write never replaced).
- **Round 18**: an empty HOME left out for the bridge (node); and the QML
  ones (the loaded row at its end resuming; a toggle shown only on its
  answer, or a superseded answer shown; the idle unload waiting while
  playing; a drag's seek sent as relative, its release skipping, a skip
  after it not folded in; the volume drag doing nothing; a dormant answer
  retried). Safety: a skip back from a told end then Play, a media key, a
  drag back while it plays, each into the end unasked; no answer for a
  pending end taken for one; the check taking a place mpv was never sent
  to; from the start, the base 0; a played episode replayed read as
  finished elsewhere; the sleep guard's mark left out, or a load ignoring
  it; a self-check under way trusted. (Three older ones retired: the one
  guard, end_still_stands, replaced the paths they planted.)

## Results

- Round 1 (the reviewers' own mutants, before the fixes): 8 of 20 killed
  (safety), 24 of 44 (fit). After round 1's fixes: 57 of 57 of this set.
- Round 2 (the reviewers' own): 6 of 12 (safety; 3 equivalent), 2 of 21
  (fit). After round 2's fixes, this set: 78 of 86, then the 8 survivors
  resolved: four real gaps tested (a poll filling in the record, Pocket
  Casts further on winning after a close, the fresh count after a speed
  change, Play at a real end keeping its player), one test hole the new
  tag rules had opened (`pin = false` now appears in every rule's text),
  one test pointed at the right check, and two equivalent mutants removed
  with the redundant code they hit (a guard against learning at an end,
  and an `&& opened` closing already covers). Final: 84 of 84 killed, on a
  green suite (157 Python tests, 36 node).
- Round 3 (the reviewers' own): 6 of 11 (safety; 2 equivalent), 21 of 29
  (fit; 12 by behaviour, the rest by pattern). Their shapes are in this set
  now, as behaviour tests: the start floor (hosts without ranges), the
  M4A index and skip-outro ends, the unsent position's hour, rule 2 when
  Pocket Casts is behind, and the QML (the Stats button, `a`, About over
  Stats, the switch before a read, stale reads, error clearing, the seek
  flag's reset, rows and Episodes finished).
- After round 3's fixes: 113 of 113 killed, on a green suite (171 Python
  tests, 36 node; the first run's baseline check caught a stale node
  pattern, which skipped its five mutants until fixed).
- Round 4 (the reviewers' own): 18 of 31 real (fit; the QML 7 of 16), 8
  of 12 (safety). Their survivors are in this set now as behaviour tests.
  After round 4's fixes, this set's first run: 134 of 137, on a suite red
  only from a test asserting the old start position; the three survivors
  (the watcher's record unread or the watcher not loaded, caught only by a
  break early enough for the length rule to agree; an outro longer than
  the misread duration, which mpv refuses anyway) got a break near the end
  and a 10 s outro. Final: 137 of 137 killed, on a green suite (188 Python
  tests, 36 node).
- Round 5 (the reviewers' own): 12 of 20 behaviour mutants (fit), 9 of 13
  (safety); their survivors are tests now. This set after round 5's fixes:
  149 of 151 on a green suite; one survivor was a redundant check (the
  refresh guard repeated inside refresh_tokens, removed with its mutant),
  the other a date test whose times fell on the same day in UTC (late and
  early local times added, run against the node suite). Final: 150 of 150
  killed (204 Python tests, 36 node).
- Round 6 (the reviewers' own): 27 of 41 (fit; 8 real survivors), and the
  safety reviewer's 2 of 8 that survived. Their gaps are tests now. This
  set after round 6's fixes: 160 of 163; the survivors were an end-only
  read made redundant by the stall work (Play now takes the full
  snapshot), `seekable` caught only by an M4A whose index is at the back
  (pointed there), and a stall-then-break test that polled during the
  stall (now it doesn't). Final: 162 of 162 killed (218 Python tests, 36
  node); then one more for the fallback service made before the bar's
  handover (found live after the commit): 163 of 163.
- Round 7 (the reviewers' own): 12 of 29 (fit), 6 of 8 (safety); their
  gaps are tests now. This set after round 7's fixes, first run: 158 of
  179 on a suite red in two tests (an old assertion; a skip-outro end the
  new "far short" rule caught until it counted the outro), so 13 skipped;
  of 8 survivors, 6 were masked by that rule (test breaks at a fifth of
  the file are also "far short": the evidence tests now break past half),
  one needed numbers outside the drift slack, one a media-key pause after
  a healed stall. Final: 179 of 179 killed (230 Python tests, 36 node).
- Round 8 (the reviewers' own): 28 of 38 (fit), 12 of 14 (safety); their
  gaps are tests now. This set after round 8's fixes and the FFmpeg
  self-check: 193 of 200; six survivors masked by the new catch-all
  (`failed`: any network error since a seek is a break, so tests of the
  older evidence passed without it) now have tests where only their own
  evidence can tell (an HLS segment that comes back empty, a host without
  ranges that goes silent, the self-check's warn-level reconnect line), and
  one had numbers that moved nothing. Final: 200 of 200 killed.
- Round 9: this set after round 9's fixes: 211 of 215. Two survivors were
  the older `recordSeen` guard masked by round 9's followed-show rule (the
  tests used a followed show), one a seek clearing the cut that FFmpeg's
  continuing reconnects logged again (the test now waits until FFmpeg has
  given up, at 1x so the cut is still ahead), one notification text never
  given markup. The round's reviewer's own `recordSeen` mutant is listed
  now. All killed.
- Round 10 (the reviewers' own): 16 of 23 survived (fit; 12 of 13 in QML:
  BarWidget was never loaded, the Settings page had no rows, nothing could
  fail to start), and the claim path Omarchy takes (safety). All listed
  now, with tests: tests/qml/chip.qml loads the real BarWidget, the
  stand-ins read real files and can fail starts, and a script error in
  Legato's QML fails the run. Twelve older patterns had gone stale with
  the round's changes and would have been skipped quietly: the runner
  fails on them now. Survivors on the way, each fixed in the test: the
  test's own steps moving on after a timeout without failing, `recordSeen`
  masked again by the new list check (Up Next's sync data hides it too
  now), positions within the one-second rule, a page's visibility set
  twice (the Flickable alone now), an import over a file made by a script.
- Round 10's full run: 293 of 294; the survivor was a flag made redundant by
  round 10's own fix (`stalledPlace`, always set with `unconfirmed`):
  removed. Round 11 (the reviewers' own): the safety reviewer's paths had
  no mutants (Play and a drag back on another file, a stale finish, a
  record without a position); 11 of 14 QML mutants (fit) survived: two
  screens' claims, a dormant copy's socket, notices said once, the chip's
  shapes and its marquee. All listed now, with tests. On the way: two
  more masked by tiny numbers (a push at 1 hid a push at 0; a phone 2 s on
  sat inside the 3 s drift), and a fix of round 11's own that a test
  caught (Stop paused first counted an unchecked stretch as paused).
- Round 11's full run: 320 of 322; both survivors were made equivalent by
  round 11's own fixes (Play's path checks after the stray-file check; the
  idle copy after the "had a shared service" latch): the redundant code
  removed with them. Round 12 (the reviewers' own): 14 of 25 QML (fit)
  survived, 2 of 10 (safety: a redundant second guard, now tested on its
  own, and a near-equivalent). All listed now. On the way: a dormant
  copy's reportError guard proved redundant (a notification is a call,
  and a dormant copy's calls never start): removed; Play's full snapshot
  needed a cut past nine tenths, where length alone says "the end".
- Round 12's full run: 350 of 352. "Service: a dormant copy keeps mpv's
  socket" survived because the test's player had stopped before the copy
  went dormant (the test now holds a live socket there); "poll: a stretch
  nobody asked about pushed" was a guard the first poll's marking made
  redundant except for retrying a failed pause push: the guard was
  removed and the retry is tested. Round 13 (the reviewers' own): 5 of 17
  safety and 16 of 21 fit survived; all planted now, with tests.
- Round 13's set, its 65 new or changed: 62 killed at first. Two survived
  (a suspend before the push stopped it being tried at all, so "not
  recorded from a call that slept" was never reached: a test with the
  sleep during the push; the event socket's reconnection brought a poll
  that hid whether a pause event brings one: steps split) and one test's
  premise was off (Play pressed before mpv had paused itself at the end).
  All three killed after.
- Round 13's full run: 403 of 403. Round 14 (the reviewers' own): safety
  3 of 18 survived (the https suspend check twice, the seek flag), fit 47
  of 106 QML/JS (about 14 equivalent or doubly guarded): the real ones
  planted now with tests (real keys through Omarchy's own key catcher,
  the import from the bar entry, the debounce, a late show page, sign-out,
  `legato stop`, the live position at speed). Round 14's set, its 45 new or
  changed: 43 killed at first; "the reload falls to Up Next" was hidden by
  Play now skipping the last episode itself (its test list now includes
  the failed-lookup test), and "keys fire while typing" needed a key the
  field leaves alone (an arrow: printable keys never reach the catcher).
- Round 14's full run: 432 of 434, the other two skipped (their tests had
  been renamed in round 14; pointed at the current ones in round 15).
  Round 15 (the reviewers' own): safety 2 of 6 survived (a kept reload's
  unsent place and its comparison, now killed), fit 35 of 75 QML/JS (7
  equivalent; the real ones planted with tests: the menu's marks, keys
  with the menu open, `4`, ←, the password, modifiers). Round 15's set,
  its 64 new or changed: 61 killed at first; "the reload's unsent place
  not carried" was hidden by later failed pushes recording it again (the
  test now checks right after the reload); a late confirmation's "ended
  here" was a third guard over the pending entry and the record's played
  status (removed from the code, which made "Play with nothing loaded
  replays an end still pending" killable).
- Round 16 (the reviewers' own): safety R1 and R22 (`kept_elsewhere`'s
  gates, never reached: every test polled first) survived and are planted
  now with tests that reload before any retry; R3, R10 (two redundant
  guards, removed from the code) and R9a (tested now); fit P1 and P17 (the
  deadline's exemptions) and Q3, Q4, Q8, Q15 planted with tests. Round
  16's set, its 31 new or changed: 28 killed at first; two were a second
  layer over one rule (an unsent place's base checked both by its gate and
  by `kept_place`; a copy started with no screen woken both at creation
  and by the change handler, which QML runs for the first value): one
  layer each removed from the code; the third needed its test to check
  the carried place is still valid, not just present.
- Round 17 (the reviewers' own): safety 6 of 19 survived (the stash's
  "ended here", the unsent retry's positionless record, the adoption's
  `lastSyncPos`, the switch's "finished" arm: planted now with tests; the
  stash's own hour, removed from the code; a Mark-played entry as an
  unanswered end, minor), fit 3 of 25 (the write watchdog, removed; the
  de-duplication and the last episode's row, planted with tests). Round
  17's set, its 28 new or changed: 26 killed at first; two tests never
  reached the line (Pocket Casts unreachable raised before the empty
  record's check; a positionless record crashed the mutant to the same
  outcome): tightened, both killed.
- Round 18 (the reviewers' own): safety 2 of 15 survived (the adoption's
  `lastSyncStatus`, the check's forced pending retry: both reached now by
  the told-end tests), fit 11 of 44 QML (the drag, the idle unload, the
  dormant answer: planted with tests; the rest equivalent). Round 18's
  set, its 30 new or changed: 19 killed at first, 11 QML ones skipped by a
  baseline that failed once (a timing flake in a new test: a skip folded
  into a drag reads the live place, a few milliseconds on: now compared
  rounded); rerun, 9 killed, 2 survived: a toggle's "shown at once" was
  checked against the value it already had (now on, then off), and the
  volume slider set the volume both as it moved and on release (Omarchy's
  slider releases at the last place it moved to: the second set removed).
- Equivalent and left out (round 14): `keep_local` and its rules (the
  loaded player's keep is gone: its check seeks only on another device's
  write); the Stats/About keys while typing (the field takes printable
  keys before the panel's key catcher sees them).
- Equivalent and left out (round 13): the resume check's and
  reopen_ended's drops of an unsent push (a place the answer replaced, or
  an episode played again, is never within the 3 s the keep needs; the
  next push drops it), and the slider overlay's sideways check (a zero
  vertical delta adds no step), all three removed from the code;
  resume_last skipping ended episodes at the top (it retries them first,
  and the next pick skips them anyway).
- Equivalent and left out: "a stall's place confirmed meanwhile" (the
  poll's paused push needs no "ask first" after a pause since round 11,
  and `sync_now` checks the stall itself); the dormancy timer ignoring
  claims, or a claim not stopping it, each alone (one covers the other;
  both together are planted).
- Equivalent and left out: dropping `after > before` from the skip count
  (`add_stats` ignores values that aren't positive).

## Not covered by mutation

- The QML runs with stand-ins for Omarchy's Commons and Ui and for
  Quickshell's processes (`tests/qml/imports`): sizes read about 20 px
  short of the real shell's, clicks are signals emitted by the test (wheel
  turns over the panel's sliders are real events, QtTest's), and the
  bridge never runs (the test answers its calls). ShellIpc's registry
  can't show (its stand-in is a plain handler).
- The resume check's seek is skipped for a file other than the recorded
  one (round 10); only `sync_now`'s check of the same is planted.
- Autoplay that can't find out what's next (a lookup error after an end)
  stops there; not planted (a failure path with no rule to break).
- The Hyprland rules are checked as text; that Hyprland applies them as
  intended was tested live (docs/PLAN.md SR10, CLAUDE.md).
