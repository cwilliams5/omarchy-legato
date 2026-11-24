"""Plant one-line regressions in a scratch copy of Legato, one at a time, and
run the tests meant to catch each. A mutation the tests miss is a survivor:
behaviour the suite doesn't really check. See tests/mutations.md.

usage: python3 -B tests/mutate.py . [name ...]      (from the repo root; about 15 minutes)

The working copy is never changed: the repo is copied to a temporary folder
first, and each mutation is undone before the next.
"""
import os, shutil, subprocess, sys, tempfile

B = "bin/legato-bridge"
S = "Service.qml"
SV = "SettingsView.qml"
T = "tests.test_bridge."

# (name, file, old, new, tests): `old` must occur exactly once.
MUTATIONS = [
    # --- broken stream vs the end (SR1, SR3)
    ("broke: no time check", B,
     "    if position >= end - max(BROKE_SLACK, duration / 100):\n        return False\n", "",
     [T + "BrokenStream.test_how_a_break_is_told_from_the_end", T + "BrokenStream.test_a_real_end_is_still_the_end"]),
    ("broke: 1% slack dropped", B,
     "    if position >= end - max(BROKE_SLACK, duration / 100):", "    if position >= end - BROKE_SLACK:",
     [T + "BrokenStream.test_how_a_break_is_told_from_the_end"]),
    ("broke: unread bytes ignored", B,
     "        return not isinstance(read, int) or size - read > max(BROKE_UNREAD_BYTES, size // 100)",
     "        return False", [T + "BrokenStream.test_how_a_break_is_told_from_the_end"]),
    ("broke: a lost size isn't a break", B,
     "    if isinstance(loaded.get(\"size\"), int) and loaded[\"size\"] > 0:\n        return True",
     "    if isinstance(loaded.get(\"size\"), int) and loaded[\"size\"] > 0:\n        return False",
     [T + "BrokenStream.test_how_a_break_is_told_from_the_end", T + "BrokenStream.test_a_stream_that_breaks_part_way_is_not_finished"]),
    ("broke: no-size host with a duration isn't a break", B,
     "    return known is not None\n", "    return False\n", [T + "BrokenStream.test_how_a_break_is_told_from_the_end"]),
    ("broke: unknown counts as broken", B,
     "    return known is not None\n", "    return True\n", [T + "BrokenStream.test_how_a_break_is_told_from_the_end"]),
    ("broke: the eof duration wins", B,
     "    duration = known if known is not None else snap.get(\"duration\")", "    duration = snap.get(\"duration\")",
     [T + "BrokenStream.test_how_a_break_is_told_from_the_end"]),
    ("broke: another file's load record", B,
     "loaded.get(\"url\") == snap.get(\"path\") else {}", "True else {}",
     [T + "BrokenStream.test_how_a_break_is_told_from_the_end"]),
    ("load: nothing recorded", B,
     "    state[\"stream\"] = stream\n", "",
     [T + "BrokenStream.test_a_load_records_what_mpv_knew_of_the_file", T + "BrokenStream.test_a_stream_that_breaks_part_way_is_not_finished"]),
    ("end properties: no file size", B,
     "END_PROPERTIES = (\"stream-pos\", \"stream-end\", \"file-local-options/end\")",
     "END_PROPERTIES = (\"file-local-options/end\",)", [T + "BrokenStream.test_how_a_break_is_told_from_the_end"]),
    ("poll: break taken for the end", B,
     "    if state.get(\"handledEnd\") != episode.get(\"uuid\") and stream_broke(snap, state):", "    if False:",
     [T + "BrokenStream.test_a_stream_that_breaks_part_way_is_not_finished"]),
    ("resume: no broken-stream guard", B,
     "        if stream_broke(snap, state):\n            # Its stream broke off before a poll saw it",
     "        if False:\n            # Its stream broke off before a poll saw it",
     [T + "BrokenStream.test_play_pressed_before_a_poll_saw_the_break_carries_on_too"]),
    ("resume: snapshot without the path", B,
     "(\"eof-reached\", \"path\", \"time-pos\", \"duration\") + END_PROPERTIES", "(\"eof-reached\", \"time-pos\", \"duration\") + END_PROPERTIES",
     [T + "BrokenStream.test_play_pressed_before_a_poll_saw_the_break_carries_on_too"]),
    ("resume: broken branch doesn't reload", B,
     "            stream_stopped(state, prefs, snap.get(\"time-pos\"))\n            resume_last(prefs)",
     "            stream_stopped(state, prefs, snap.get(\"time-pos\"))",
     [T + "BrokenStream.test_play_pressed_before_a_poll_saw_the_break_carries_on_too"]),
    # --- the broken stream's push (rule 1, 2)
    ("stopped: push after a long gap", B,
     "        recent = time.time() - float(state.get(\"lastSyncAt\") or 0) < RECHECK_AFTER\n        if not recent:",
     "        recent = True\n        if not recent:", [T + "BrokenStream.test_a_break_after_a_long_gap_pushes_nothing"]),
    ("stopped: pushes while unconfirmed", B,
     "        elif episode.get(\"uuid\") and not state.get(\"unconfirmed\") and not state.get(\"checkServer\"):",
     "        elif episode.get(\"uuid\") and not state.get(\"checkServer\"):",
     [T + "BrokenStream.test_a_break_during_an_unconfirmed_resume_pushes_nothing"]),
    ("stopped: pushes before the check", B,
     "        elif episode.get(\"uuid\") and not state.get(\"unconfirmed\") and not state.get(\"checkServer\"):",
     "        elif episode.get(\"uuid\") and not state.get(\"unconfirmed\"):",
     [T + "BrokenStream.test_a_break_before_the_resume_check_pushes_nothing"]),
    ("stopped: never pushes", B,
     "        elif episode.get(\"uuid\") and not state.get(\"unconfirmed\") and not state.get(\"checkServer\"):",
     "        elif False:", [T + "BrokenStream.test_a_stream_that_breaks_part_way_is_not_finished"]),
    # --- the quick check and sign-in (SR4)
    ("check: quick never short", B,
     "        with http_timeout(RESUME_CHECK_TIMEOUT) if quick else contextlib.nullcontext():",
     "        with contextlib.nullcontext():", [T + "ResumeAsksPocketCastsFirst.test_a_hanging_network_holds_up_play_only_briefly"]),
    ("check: always short", B,
     "        with http_timeout(RESUME_CHECK_TIMEOUT) if quick else contextlib.nullcontext():",
     "        with http_timeout(RESUME_CHECK_TIMEOUT):", [T + "ResumeAsksPocketCastsFirst.test_the_check_during_playback_waits_the_full_timeout"]),
    ("resume: not quick", B,
     "    outcome, state = check_server(state, prefs, player, quick=True)", "    outcome, state = check_server(state, prefs, player)",
     [T + "ResumeAsksPocketCastsFirst.test_a_hanging_network_holds_up_play_only_briefly"]),
    ("token: refresh under the short limit", B,
     "                                    timeout=TOKEN_TIMEOUT)", "                                    )",
     [T + "ResumeAsksPocketCastsFirst.test_a_sign_in_refresh_isnt_cut_short_by_the_quick_check",
      T + "ResumeAsksPocketCastsFirst.test_a_rejected_token_inside_the_quick_check_refreshes_at_full_time"]),
    ("sleep guard: refresh not shortened", B,
     "    HTTP_TIMEOUT = TOKEN_TIMEOUT = SLEEP_PUSH_TIMEOUT", "    HTTP_TIMEOUT = SLEEP_PUSH_TIMEOUT",
     [T + "EndToEnd.test_before_sleep_a_playing_episode_is_paused_and_saved"]),
    ("check: 5 s back to 15", B,
     "RESUME_CHECK_TIMEOUT = 5\n", "RESUME_CHECK_TIMEOUT = 15\n",
     [T + "ResumeAsksPocketCastsFirst.test_play_waits_five_seconds_at_most_per_request"]),
    # --- listening stats
    ("count: seek flag ignored", B,
     "        elif seeked:\n", "        elif False:\n",
     [T + "ListeningCount.test_after_a_seek_from_elsewhere_only_the_speed_counts", T + "ListeningStats.test_a_seek_from_a_media_widget_isnt_time_saved"]),
    ("count: seeked stretch unbounded", B,
     "            if (wall <= SEEKED_STRETCH_MAX and snap.get(\"pause\") is False\n                    and snap.get(\"paused-for-cache\") is not True):",
     "            if True:", [T + "ListeningCount.test_after_a_seek_from_elsewhere_only_a_playing_poll_length_counts"]),
    ("count: trim credited with trim off", B,
     "            trimmed = max(0.0, moved - speed * wall) if trim != \"off\" else 0.0", "            trimmed = max(0.0, moved - speed * wall)",
     [T + "ListeningCount.test_without_trim_nothing_is_put_down_to_it"]),
    ("count: no lower bound (stalls count)", B,
     "        elif speed * (wall - 1) <= moved <= furthest:", "        elif moved <= furthest:",
     [T + "ListeningCount.test_a_jump_or_a_stall_isnt_counted"]),
    ("count: no gap limit", B,
     "        if not 0 < wall <= LISTEN_GAP_MAX:", "        if not 0 < wall:",
     [T + "ListeningCount.test_a_long_stretch_isnt_listening_even_at_a_plausible_pace"]),
    ("count: buffering starts a count", B,
     "               and snap.get(\"paused-for-cache\") is not True)\n    state[\"listening\"]", "               )\n    state[\"listening\"]",
     [T + "ListeningCount.test_a_count_that_starts_buffering_or_on_another_file_counts_nothing"]),
    ("count: another file counted", B,
     "    ours = bool(episode.get(\"uuid\")) and snap.get(\"path\") == episode.get(\"url\") and isinstance(position, (int, float))",
     "    ours = bool(episode.get(\"uuid\")) and isinstance(position, (int, float))",
     [T + "ListeningCount.test_a_count_that_starts_buffering_or_on_another_file_counts_nothing"]),
    ("count: trim change not noticed", B,
     "            and last.get(\"trim\") == trim and isinstance(last.get(\"pos\"), (int, float))",
     "            and isinstance(last.get(\"pos\"), (int, float))",
     [T + "ListeningCount.test_a_trim_change_mid_stretch_drops_that_stretch"]),
    ("count: paused counted as playing", B,
     "    playing = (ours and snap.get(\"pause\") is False and snap.get(\"eof-reached\") is not True",
     "    playing = (ours and snap.get(\"eof-reached\") is not True",
     [T + "ListeningCount.test_paused_time_and_long_gaps_arent_listening", T + "ListeningCount.test_a_pause_ends_the_count",
      T + "ListeningStats.test_paused_time_isnt_listening"]),
    ("count: errors reach the poll", B,
     "    except Exception:  # noqa: BLE001 (a DeadlinePassed isn't an Exception and still ends the call)\n        state[\"listening\"] = {}",
     "    except ImportError:\n        state[\"listening\"] = {}", [T + "ListeningCount.test_stats_never_break_a_poll"]),
    ("seek: count not restarted", B,
     "            state[\"listening\"] = {}  # a new count from here: the jump itself isn't listening\n", "",
     [T + "ListeningStats.test_with_trim_on_a_skip_isnt_counted_as_trimmed_too"]),
    ("seek: the slider counted as skipping", B,
     "            if (args.relative and isinstance(before, (int, float))",
     "            if (isinstance(before, (int, float))",
     [T + "ListeningStats.test_a_jump_forward_on_the_slider_isnt_skipping"]),
    ("pause: no count first", B,
     "                        count_listening(state, listen_snap(player), prefs)\n                        player.set(\"pause\", True)",
     "                        player.set(\"pause\", True)",
     [T + "ListeningStats.test_a_pause_counts_up_to_the_pause_however_late_the_poll"]),
    ("speed: no count around it", B,
     "def cmd_speed(args):\n    with listening_change(), prefs_update() as prefs:", "def cmd_speed(args):\n    with prefs_update() as prefs:",
     [T + "ListeningStats.test_a_speed_or_trim_change_counts_what_came_before"]),
    ("switch: no count", B,
     "        if url and player.get(\"path\") == url:\n            count_listening(state, listen_snap(player), load_prefs())\n",
     "        if url and player.get(\"path\") == url:\n", [T + "ListeningStats.test_next_and_switching_count_up_to_the_change"]),
    ("stop: no count", B,
     "        if player:\n            count_listening(state, listen_snap(player), load_prefs())\n            sync_now(player, state)\n            quit_mpv(player)",
     "        if player:\n            sync_now(player, state)\n            quit_mpv(player)", [T + "ListeningStats.test_stopping_counts_up_to_the_stop"]),
    ("stats: off ignored", B,
     "        if not stats_counting(load_prefs()):\n            return\n", "",
     [T + "ListeningCount.test_counting_can_be_turned_off_and_cleared"]),
    ("stats: clear keeps the file", B,
     "            drop_state(\"stats.json\")", "            pass", [T + "ListeningCount.test_counting_can_be_turned_off_and_cleared"]),
    ("stats: clear without the lock", B,
     "        with StateLock():\n            drop_state(\"stats.json\")", "        if True:\n            drop_state(\"stats.json\")",
     [T + "ListeningCount.test_clear_waits_for_a_poll_counting_at_that_moment"]),
    ("stats: intro not counted", B,
     "    if intro:\n        add_stats(intro=intro)", "    pass", [T + "ShowSkips.test_a_fresh_episode_starts_past_the_intro"]),
    ("stats: outro not counted", B,
     "        if outro:\n            add_stats(outro=outro)", "        pass", [T + "ShowSkips.test_the_outro_is_skipped_and_the_episode_ends_there"]),
    # --- skip-taskbar (SR10)
    ("tag: no untag rule", B,
     "            'pcall(hl.window_rule, { name = \"%(id)s-untag\"", "            '-- (", [T + "Validation.test_video_window_rule_and_geometry"]),
    ("tag: not by the pin state", B,
     "match = { class = \"^%(id)s$\", pin = true }, tag = \"+%(skip)s\"", "match = { class = \"^%(id)s$\" }, tag = \"+%(skip)s\"",
     [T + "Validation.test_video_window_rule_and_geometry"]),
    # --- tests touching the desktop (SR11): the guard is in the test harness itself, not mutated here.
    # --- QML (SR7, SR8, SR12)
    ("stats page: zeros before the first read", "StatsView.qml",
     "  function total(seconds) { return root.known ? Model.fmtTotal(seconds) : \"…\" }",
     "  function total(seconds) { return Model.fmtTotal(seconds) }", [T + "QmlPages"]),
    ("stats page: Clear without confirming", "StatsView.qml",
     "        if (!root.confirmClear) { root.confirmClear = true; return }\n", "", [T + "QmlPages"]),
    ("stats page: leaving keeps Clear armed", "StatsView.qml",
     "  onVisibleChanged: if (!visible) root.confirmClear = false\n", "", [T + "QmlPages"]),
    ("stats page: errors hidden", "StatsView.qml",
     "    visible: root.error !== \"\"", "    visible: false", [T + "QmlPages"]),
    ("stats page: the bridge's counting ignored", "StatsView.qml",
     "    ? root.stats.counting !== false : root.counting", "    ? root.counting : root.counting", [T + "QmlPages"]),
    ("service: playback-restart not flagged", S,
     "    if (message.event === \"playback-restart\") _seekedSincePoll = true\n", "", ["node"]),
    ("service: a failed poll loses the seek flag", S,
     "      if (!result.ok && seeked) root._seekedSincePoll = true  // the next poll still knows\n", "", ["node"]),
    ("service: stats errors dropped", S,
     "    if (!result.ok) { root.statsError = result.error || \"Couldn't read the listening stats\"; return }",
     "    if (!result.ok) return", ["node"]),
    ("service: the open page never refreshes", S,
     "    if (statsPageOpen) loadStats()  // the open Stats page follows what's counted\n", "", ["node"]),
    ("panel: settings and stats both open", "Panel.qml",
     "    if (showSettings) { showAbout = false; showStats = false }", "    if (showSettings) { showAbout = false }", ["node"]),
]


def run_tests(repo, tests):
    ok = True
    py = [t for t in tests if t != "node"]
    if py:
        r = subprocess.run([sys.executable, "-B", "-m", "unittest", *py], cwd=repo, capture_output=True, text=True, timeout=900)
        ok = ok and r.returncode == 0
    if "node" in tests:
        r = subprocess.run(["node", "--test", "tests/model.test.cjs"], cwd=repo, capture_output=True, text=True, timeout=300)
        ok = ok and r.returncode == 0
    return ok


def main():
    src = os.path.abspath(sys.argv[1])
    only = set(sys.argv[2:])
    work = tempfile.mkdtemp(prefix="legato-mut-")
    repo = os.path.join(work, "repo")
    shutil.copytree(src, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", "media", "branding"))
    killed = survived = 0
    for name, path, old, new, tests in MUTATIONS:
        if only and name not in only:
            continue
        full = os.path.join(repo, path)
        original = open(full, encoding="utf-8").read()
        count = original.count(old)
        if count != 1:
            print("SKIP  %-40s (pattern found %d times)" % (name, count)); continue
        open(full, "w", encoding="utf-8").write(original.replace(old, new))
        try:
            caught = not run_tests(repo, tests)
        finally:
            open(full, "w", encoding="utf-8").write(original)
        if caught:
            killed += 1; print("kill  %s" % name)
        else:
            survived += 1; print("SURVIVED  %s" % name)
        sys.stdout.flush()
    print("\n%d killed, %d survived" % (killed, survived))
    shutil.rmtree(work)


main()
