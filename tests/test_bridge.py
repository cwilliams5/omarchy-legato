"""Tests for bin/legato-bridge: private state files, input validation,
bounded and host-checked HTTP, token refresh, and an end-to-end run of the
player against a fake Pocket Casts server with a real mpv — play, pause,
position sync, the end of an episode, mark-played and autoplay.

Run with tests/run, or directly:

    /usr/bin/python3 -I -B -m unittest discover -s tests -v
"""

import argparse
import atexit
import base64
import contextlib
import functools
import gzip
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import pwd
import re
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import urllib.parse
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "bin" / "legato-bridge"

sys.dont_write_bytecode = True


def short_temp_dir():
    """Where the throwaway homes go: mpv's socket path inside one must stay
    under the 107-byte limit, so a long TMPDIR (a sandbox's) gives way to
    /tmp (a test failed there with "False is not true": strict review 22)."""
    default = tempfile.gettempdir()
    return default if len(default) <= 40 else "/tmp"


# Every test in this file runs against a throwaway home, set before the
# bridge loads: nothing reaches the real account's state, player, Pocket
# Casts sign-in or desktop, even from a test outside TempHome whose code
# under test breaks (strict review 22, fit F1: Validation's sleep-guard
# tests ran the guard with the real HOME, safe only while it stopped at
# "no sleep"; round 14's reviewer once acted on the real account that way).
REAL_HOME = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
REAL_RUNTIME = "/run/user/%d" % os.getuid()
_SANDBOX = os.path.realpath(tempfile.mkdtemp(prefix="pc-bridge-module-", dir=short_temp_dir()))
os.chmod(_SANDBOX, 0o700)
os.mkdir(os.path.join(_SANDBOX, "run"), 0o700)
atexit.register(shutil.rmtree, _SANDBOX, True)
os.environ.update({
    "HOME": _SANDBOX,
    "XDG_STATE_HOME": _SANDBOX + "/.local/state",
    "XDG_CACHE_HOME": _SANDBOX + "/.cache",
    "XDG_CONFIG_HOME": _SANDBOX + "/.config",
    "XDG_DATA_HOME": _SANDBOX + "/.local/share",
    "XDG_RUNTIME_DIR": _SANDBOX + "/run",
})
for _name in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DBUS_SESSION_BUS_ADDRESS"):
    os.environ.pop(_name, None)


def assert_sandboxed():
    """No bridge call runs with a folder of the real account's: the folders
    the bridge itself would use, from its own resolvers (a relative HOME or
    runtime folder falls back to the real ones there, with
    scrub_environment off as run_bridge has it: strict review 23, M1)."""
    runtime = bridge.clean_env_value("XDG_RUNTIME_DIR", os.environ.get("XDG_RUNTIME_DIR")) or "/run/user/%d" % os.geteuid()
    folders = {"HOME": bridge.home(), "XDG_RUNTIME_DIR": runtime,
               "XDG_STATE_HOME": bridge.xdg_home("XDG_STATE_HOME", ".local", "state"),
               "XDG_CACHE_HOME": bridge.xdg_home("XDG_CACHE_HOME", ".cache"),
               "XDG_CONFIG_HOME": bridge.xdg_home("XDG_CONFIG_HOME", ".config"),
               "XDG_DATA_HOME": bridge.xdg_home("XDG_DATA_HOME", ".local", "share")}
    for name, folder in folders.items():
        value = os.path.realpath(folder or "/")
        if value == REAL_HOME or value.startswith(REAL_HOME + "/") or value.startswith(REAL_RUNTIME) or value == "/":
            raise AssertionError("refusing to run the bridge with %s at %s (the real account's)" % (name, value))


_loader = importlib.machinery.SourceFileLoader("legato_bridge", str(BRIDGE))
_spec = importlib.util.spec_from_loader("legato_bridge", _loader)
bridge = importlib.util.module_from_spec(_spec)
_loader.exec_module(bridge)

PODCAST_A = "11111111-1111-1111-1111-111111111111"
PODCAST_B = "22222222-2222-2222-2222-222222222222"
OMARCHY_HELPERS = "/usr/share/omarchy/default/hypr/helpers.lua"
EP_1 = "aaaaaaaa-0000-0000-0000-000000000001"
EP_2 = "aaaaaaaa-0000-0000-0000-000000000002"
EP_3 = "bbbbbbbb-0000-0000-0000-000000000003"
GONE = "aaaaaaaa-0000-0000-0000-0000000000ff"  # on Up Next, gone from its feed (strict review 23)
PASSWORD = "correct horse battery staple"


def mode_of(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


class TempHome(unittest.TestCase):
    """A private throwaway $HOME with every XDG directory pointed inside it."""

    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="pc-bridge-", dir=short_temp_dir()))
        os.chmod(self.home, 0o700)
        self.addCleanup(shutil.rmtree, self.home, True)
        runtime = os.path.join(self.home, "run")
        os.mkdir(runtime, 0o700)
        env = {
            "HOME": self.home,
            "XDG_STATE_HOME": self.home + "/.local/state",
            "XDG_CACHE_HOME": self.home + "/.cache",
            "XDG_CONFIG_HOME": self.home + "/.config",
            "XDG_DATA_HOME": self.home + "/.local/share",
            "XDG_RUNTIME_DIR": runtime,
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        # No desktop: a test player never reaches the real compositor (or its
        # clipboard), nor a test the session bus (notifications); patch.dict
        # puts these back afterwards.
        for name in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DBUS_SESSION_BUS_ADDRESS"):
            os.environ.pop(name, None)
        self.reset_globals()
        self.addCleanup(self.reset_globals)

    def reset_globals(self):
        if bridge._ART_DIR is not None:
            bridge._ART_DIR.close()
        bridge._ART_DIR = None
        bridge._AUTH = None

    @property
    def state(self):
        return os.path.join(self.home, ".local", "state", "omarchy-legato")


def run_bridge(*argv, stdin=""):
    """Run one subcommand in-process and return its JSON envelope."""
    assert_sandboxed()
    out = io.StringIO()
    fake_stdin = io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8")), encoding="utf-8")
    with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stdin", fake_stdin), \
            mock.patch.object(bridge, "scrub_environment", lambda: None):
        bridge._AUTH = None
        bridge.main(list(argv))
    return json.loads(out.getvalue())


# --------------------------------------------------------------- unit tests

class Validation(unittest.TestCase):
    def test_status_says_the_files_version(self):
        # Strict review 14 (fit F1): the shell keeps the QML it compiled
        # through an update; the bridge (new) tells the service which version
        # the files are, so it can ask for a restart.
        manifest = json.load(open(os.path.join(os.path.dirname(str(BRIDGE)), "..", "manifest.json")))
        self.assertEqual(bridge.files_version(), manifest["version"])
        with mock.patch.object(bridge, "manifest", lambda: {"version": "1.1.0; rm -rf"}):
            self.assertEqual(bridge.files_version(), "")
        with mock.patch.object(bridge, "manifest", side_effect=OSError("gone")):
            self.assertEqual(bridge.files_version(), "")

    def test_hyprctl_never_waits_long(self):
        # Strict review 13 (fit B1): a hung compositor can't hold a bridge
        # call (and its state lock) for the whole deadline.
        with mock.patch.object(bridge, "trusted_tool", lambda name: "/usr/bin/hyprctl"), \
                mock.patch.object(bridge.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="[]")
            self.assertEqual(bridge.hyprctl("clients", "-j"), "[]")
            self.assertEqual(run.call_args.kwargs.get("timeout"), 3)
            run.side_effect = bridge.subprocess.TimeoutExpired("hyprctl", 3)
            self.assertEqual(bridge.hyprctl("clients", "-j"), "")

    def test_uuid_must_be_a_uuid(self):
        self.assertEqual(bridge.safe_uuid(EP_1.upper()), EP_1)
        for bad in ["", "../etc", EP_1 + "/x", "x" * 36, None]:
            with self.assertRaises(bridge.ApiError):
                bridge.safe_uuid(bad)

    def test_only_http_media_urls_reach_mpv(self):
        self.assertTrue(bridge.safe_media_url("https://example.com/a.mp3"))
        self.assertTrue(bridge.safe_media_url("http://example.com/a.mp3?x=1"))
        for bad in ["file:///etc/passwd", "/etc/passwd", "lavfi://sine", "av://x", "edl://a",
                    "https://example.com/a\n.mp3", "ytdl://x", "https:///nohost", "", None]:
            self.assertEqual(bridge.safe_media_url(bad), "", bad)

    def test_mpv_quote_keeps_commas_inside_one_value(self):
        self.assertEqual(bridge.mpv_quote("a,b=c"), "%5%a,b=c")
        self.assertEqual(bridge.mpv_quote("é"), "%2%é")

    def test_norm_episode_shape_and_status(self):
        item = bridge.norm_episode({"uuid": EP_1.upper(), "podcastUuid": PODCAST_A, "title": "  Hello\nworld ",
                                    "url": "https://x.test/a.mp3", "duration": "120", "playedUpTo": 30,
                                    "published": "2026-09-30T10:00:00Z"})
        self.assertEqual(item["uuid"], EP_1)
        self.assertEqual(item["name"], "Hello world")
        self.assertEqual(item["status"], bridge.STATUS_IN_PROGRESS)
        self.assertEqual(item["duration"], 120)
        self.assertTrue(item["art"].startswith("https://static.pocketcasts.com/"))
        self.assertIsNone(bridge.norm_episode({"uuid": "nope"}))
        bad_url = bridge.norm_episode({"uuid": EP_1, "url": "file:///etc/shadow"})
        self.assertEqual(bad_url["url"], "")

    def test_start_position(self):
        self.assertEqual(bridge.start_position({"playedUpTo": 50, "duration": 100, "status": 2}), 50)
        self.assertEqual(bridge.start_position({"playedUpTo": 50, "duration": 100, "status": 3}), 0)
        # At or past the listed length, still in progress: from there (files
        # run longer than listed; from the top would push 0 everywhere).
        self.assertEqual(bridge.start_position({"playedUpTo": 99, "duration": 100, "status": 2}), 99)
        self.assertEqual(bridge.start_position({"playedUpTo": 120, "duration": 100, "status": 2}), 120)
        self.assertEqual(bridge.start_position({"playedUpTo": 50, "duration": 100}, from_start=True), 0)

    def test_trim_levels_use_pocket_casts_values(self):
        self.assertEqual(bridge.trim_filter("off"), "")
        self.assertEqual(bridge.trim_filter("bogus"), "")
        self.assertEqual(bridge.trim_level("MadMax"), "madmax")
        mild = bridge.trim_filter("mild")
        self.assertIn("stop_duration=0.416:stop_silence=0.291", mild)
        self.assertIn("stop_duration=0.3:stop_silence=0.225", bridge.trim_filter("medium"))
        self.assertIn("stop_duration=0.083:stop_silence=0", bridge.trim_filter("madmax"))
        for level in ("mild", "medium", "madmax"):
            spec = bridge.trim_filter(level)
            # Keep each frame's own time, so positions stay in the episode's time.
            self.assertIn("timestamp=copy", spec)
            self.assertIn("stop_threshold=-42dB:detection=peak", spec)

    def test_mpv_gets_the_display_for_its_video_window(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1", "HYPRLAND_INSTANCE_SIGNATURE": "abc_123",
                                          "LD_PRELOAD": "/tmp/x.so"}):
            env = bridge.child_env()
        self.assertEqual(env.get("WAYLAND_DISPLAY"), "wayland-1")
        self.assertEqual(env.get("HYPRLAND_INSTANCE_SIGNATURE"), "abc_123")
        self.assertNotIn("LD_PRELOAD", env)

    @unittest.skipUnless(os.path.exists("/usr/bin/lua5.4") and os.path.exists(OMARCHY_HELPERS), "needs lua5.4 and Omarchy")
    def test_the_rule_registers_with_omarchy_once(self):
        # Omarchy's o.window adds the app to its floating-app list on every
        # call, with no check for repeats. Run the rule's Lua three times
        # against Omarchy's real helpers (a stand-in `hl` records the rules;
        # nothing reaches Hyprland): one entry, and every call still sends
        # the named rules (the size and place can change).
        with tempfile.TemporaryDirectory() as home:
            rule = os.path.join(home, "rule.lua")
            with open(rule, "w") as fh:
                fh.write(bridge.video_rule_lua({"x": 10, "y": 20, "w": 300, "h": 170}, True, 0))
            harness = (
                'package.path = "/usr/share/omarchy/?.lua;" .. package.path '
                'local sent = {} '
                'hl = setmetatable({ window_rule = function(r) table.insert(sent, r.name) end }, '
                '{ __index = function() return function() end end }) '
                'require("default.hypr.helpers") '
                'local chunk = assert(loadfile(os.getenv("RULE"))) '
                'for i = 1, 3 do assert(chunk() == "ok") end '
                'local names = {} for _, n in ipairs(sent) do if n == "legato-video" then names[#names + 1] = n end end '
                'print(#o.floating_apps.class, #names)')
            done = subprocess.run(["/usr/bin/lua5.4", "-e", harness], capture_output=True, text=True,
                                  env={"HOME": home, "PATH": "/usr/bin", "RULE": rule}, cwd=home, timeout=10)
        self.assertEqual(done.stdout.split(), ["1", "3"], done.stderr)

    def test_video_window_rule_and_geometry(self):
        default = bridge.video_rule_lua(None)
        self.assertIn('o.window("^legato-video$", r)', default)  # Omarchy's floating mode leaves it alone
        self.assertIn('match = { class = "^legato-video$" }', default)  # without Omarchy
        self.assertIn('name = "legato-video", float = true, pin = true, no_initial_focus = true', default)
        self.assertIn('["hyprbars:no_bar"] = true', default)
        # Pinned, taskbars and window switchers that honor the tag leave it
        # out; not pinned, other windows can cover it, so it keeps its button.
        # By the window's real pin state (Omarchy's Super+O unpins it too), so
        # both rules go out whatever Legato's own setting is.
        tag = ('pcall(hl.window_rule, { name = "legato-video-tags", match = { class = "^legato-video$", pin = true }, '
               'tag = "+skip-taskbar" })')
        untag = ('pcall(hl.window_rule, { name = "legato-video-untag", match = { class = "^legato-video$", pin = false }, '
                 'tag = "-skip-taskbar" })')
        for lua in (default, bridge.video_rule_lua(None, pinned=False)):
            self.assertIn(tag, lua)
            self.assertIn(untag, lua)
        self.assertIn("monitor_w*7/25", default)
        # The window rule's own pin (the tag rules match on pin = true/false too).
        self.assertIn('name = "legato-video", float = true, pin = false', bridge.video_rule_lua(None, pinned=False))
        # Opacity is the window's own property (a rule loses to Omarchy's
        # floating workspaces), set now and by a window.open hook added once.
        self.assertIn('legato_video_alpha = "1.00"', default)
        self.assertIn('legato_video_alpha = "0.70"', bridge.video_rule_lua(None, transparency=30))
        self.assertIn('hl.on("window.open"', default)
        self.assertIn("legato_video_hook:is_active()", default)
        self.assertIn('w.class == "legato-video"', default)
        self.assertIn('"opacity_override"', default)
        # Solid while it has focus (its right-click menu is drawn inside it).
        self.assertIn('prop = "opacity", value = "1.0"', default)
        self.assertIn('prop = "opacity_inactive", value = legato_video_alpha', default)
        self.assertTrue(default.endswith('return "ok"'))
        # Only the fixed levels ever reach the Lua text.
        for bad in (35, 90, 100, -10, "30", True, None, 30.0):
            self.assertEqual(bridge.video_transparency({"videoTransparency": bad}), 0, bad)
            self.assertIn('legato_video_alpha = "1.00"', bridge.video_rule_lua(None, transparency=bad))
        self.assertEqual(bridge.video_transparency({"videoTransparency": 80}), 80)
        placed = bridge.video_rule_lua({"x": 800, "y": 500, "w": 400, "h": 225})
        self.assertIn('size = { "400", "225" }, move = { "800", "500" }', placed)
        # Only whole numbers, and a sane size, are ever kept.
        self.assertIsNone(bridge.saved_geometry({"videoGeometry": {"x": "1); os.exit(", "y": 1, "w": 400, "h": 225}}))
        self.assertIsNone(bridge.saved_geometry({"videoGeometry": {"x": 1, "y": 1, "w": 20, "h": 20}}))
        self.assertIsNone(bridge.saved_geometry({}))
        self.assertTrue(bridge.has_video({"track-list": [{"type": "video"}, {"type": "audio"}]}))
        self.assertFalse(bridge.has_video({"track-list": [{"type": "video", "albumart": True}, {"type": "audio"}]}))
        # A cover packed in as a video stream mpv doesn't flag (a PNG in an MP4).
        self.assertFalse(bridge.has_video({"track-list": [{"type": "video", "codec": "png", "albumart": False, "image": False}]}))
        self.assertFalse(bridge.has_video({"track-list": [{"type": "video", "codec": "h264", "image": True}]}))
        self.assertTrue(bridge.has_video({"track-list": [{"type": "video", "codec": "h264", "albumart": False}]}))
        self.assertFalse(bridge.has_video({}))

    def test_the_sleep_guards_short_timeout_reaches_requests(self):
        seen = []

        class Opener:
            def open(self, req, timeout=None):
                seen.append(timeout)
                raise urllib.error.URLError("offline")

        with mock.patch.object(bridge, "opener", lambda: Opener()), mock.patch.object(bridge, "HTTP_TIMEOUT", 4):
            with self.assertRaises(bridge.ApiError):
                bridge.http_raw("POST", "https://api.pocketcasts.com/x")
        self.assertEqual(seen, [4])

    def test_an_mpv_command_may_wait_longer_than_the_socket_timeout(self):
        ours, theirs = socket.socketpair()
        ours.settimeout(0.3)  # as if connected with a short timeout

        def answer():
            line = theirs.makefile("rb").readline()
            time.sleep(0.6)
            theirs.sendall(json.dumps({"request_id": json.loads(line)["request_id"], "error": "success",
                                       "data": "auto"}).encode() + b"\n")

        thread = threading.Thread(target=answer)
        thread.start()
        try:
            self.assertEqual(bridge.Mpv(ours).command("set_property", "vid", "auto", timeout=3), "auto")
        finally:
            thread.join()
            ours.close()
            theirs.close()

    def test_volume_boost_is_ten_db_into_a_limiter_after_trim(self):
        self.assertIn("level_in=3.1623", bridge.BOOST_FILTER)  # +10 dB, Pocket Casts' 1000 mB
        self.assertIn("level=false", bridge.BOOST_FILTER)       # auto-level would undo it
        self.assertEqual(bridge.audio_filters({}), "")
        chain = bridge.audio_filters({"trim": "mild", "boost": True})
        self.assertTrue(chain.startswith("@trim:") and ",@boost:" in chain)
        self.assertEqual(bridge.audio_filters({"boost": True}), "@boost:" + bridge.BOOST_FILTER)

    def test_environment_values_with_control_characters_are_dropped(self):
        # Strict review 24 (fit): the bridge's own check (the QML side's was
        # the only one tested).
        for name in ("HOME", "XDG_STATE_HOME", "DBUS_SESSION_BUS_ADDRESS"):
            self.assertEqual(bridge.clean_env_value(name, "/tmp/a\nb"), "", name)
            self.assertEqual(bridge.clean_env_value(name, "/tmp/a\x1bb"), "", name)
        self.assertEqual(bridge.clean_env_value("HOME", "/tmp/fine"), "/tmp/fine")

    def test_no_bridge_call_runs_with_the_real_accounts_folders(self):
        # Strict review 22 (fit F1): the whole file runs in a throwaway home,
        # and run_bridge refuses the real one, whatever a test sets.
        self.assertNotEqual(os.path.realpath(os.environ["HOME"]), REAL_HOME)
        # (A relative HOME or runtime folder too: the bridge falls back to the
        # real ones then, strict review 23, M1.)
        for name, value in (("HOME", REAL_HOME), ("XDG_STATE_HOME", REAL_HOME + "/.local/state"),
                            ("XDG_RUNTIME_DIR", REAL_RUNTIME), ("HOME", "relative/home"),
                            ("XDG_RUNTIME_DIR", "relative/run")):
            # The bridge itself is replaced while the refusal is tried: with
            # the check broken (a planted mutant), nothing may run against
            # the real account (strict review 24: `status` did, read-only).
            ran = []
            with mock.patch.dict(os.environ, {name: value}), \
                    mock.patch.object(bridge, "main", lambda argv: ran.append(argv)):
                with self.assertRaises(AssertionError):
                    run_bridge("status")
            self.assertEqual(ran, [], name + "=" + value)

    def test_a_sleep_guard_whose_monitor_dies_reports_a_failure(self):
        real = bridge.trusted_tool
        before = signal.getsignal(signal.SIGTERM)
        try:
            with mock.patch.object(bridge, "trusted_tool",
                                   lambda name: "/usr/bin/false" if name == "dbus-monitor" else real(name)):
                result = run_bridge("sleepguard")
        finally:
            signal.signal(signal.SIGTERM, before)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "sleepguard")

    def test_the_sleep_guard_listens_to_logind_only(self):
        # The system bus lets any process send PrepareForSleep; only the
        # match rule's sender keeps others from pausing and pushing.
        argvs = []
        class Proc:
            stdout = iter(())
            def terminate(self): pass
        with mock.patch.object(bridge, "trusted_tool", lambda name: "/usr/bin/" + name), \
                mock.patch.object(bridge.subprocess, "Popen", lambda argv, **kw: argvs.append(argv) or Proc()):
            before = signal.getsignal(signal.SIGTERM)
            try:
                result = run_bridge("sleepguard")
            finally:
                signal.signal(signal.SIGTERM, before)
        self.assertFalse(result["ok"])  # the monitor ended without a sleep
        self.assertIn("sender='org.freedesktop.login1'", argvs[0][-1])
        self.assertIn("member='PrepareForSleep'", argvs[0][-1])

    def test_sleep_is_read_from_dbus_monitor(self):
        header = ("signal time=1 sender=:1.2 -> destination=(null destination) serial=9 path=/org/freedesktop/login1; "
                  "interface=org.freedesktop.login1.Manager; member=PrepareForSleep\n")
        lines = [header, "   boolean false\n", header, "   boolean true\n", "never read\n"]
        self.assertTrue(bridge.wait_for_sleep(iter(lines)))
        # Review finding: a signal another local account sends straight to
        # the monitor (it has a destination) must not pause anything.
        unicast = header.replace("destination=(null destination)", "destination=:1.77")
        self.assertFalse(bridge.wait_for_sleep(iter([unicast, "   boolean true\n"])))
        other = header.replace("member=PrepareForSleep", "member=PrepareForShutdown")
        self.assertFalse(bridge.wait_for_sleep(iter([other, "   boolean true\n"])))
        self.assertFalse(bridge.wait_for_sleep(iter(["   boolean false\n"])))
        self.assertFalse(bridge.wait_for_sleep(iter([])))

    def test_mpv_renders_on_the_gpu_that_drives_the_display(self):
        def sysfs(cards):
            root = tempfile.mkdtemp(prefix="drm-")
            self.addCleanup(shutil.rmtree, root, True)
            for card, vendor, connectors in cards:
                os.makedirs(os.path.join(root, card, "device"))
                with open(os.path.join(root, card, "device", "vendor"), "w") as fh:
                    fh.write(vendor + "\n")
                for connector, status in connectors:
                    os.makedirs(os.path.join(root, "%s-%s" % (card, connector)))
                    with open(os.path.join(root, "%s-%s" % (card, connector), "status"), "w") as fh:
                        fh.write(status + "\n")
            return root
        laptop = sysfs([("card0", "0x10de", []), ("card1", "0x8086", [("eDP-1", "connected"), ("DP-1", "disconnected")])])
        self.assertEqual(bridge.mpv_gpu_env(laptop), {"VK_LOADER_DRIVERS_DISABLE": "*nvidia*"})
        # A hybrid laptop whose NVIDIA GPU wires the HDMI port, nothing in it
        # (strict review 21, fit F4: untested; under a mutant it got NVIDIA).
        wired = sysfs([("card0", "0x10de", [("HDMI-A-1", "disconnected"), ("DP-1", "unknown")]),
                       ("card1", "0x8086", [("eDP-1", "connected")])])  # ("unknown": not driving; round 24)
        self.assertEqual(bridge.mpv_gpu_env(wired), {"VK_LOADER_DRIVERS_DISABLE": "*nvidia*"})
        desktop = sysfs([("card0", "0x10de", [("DP-1", "connected")]), ("card1", "0x8086", [])])
        self.assertEqual(bridge.mpv_gpu_env(desktop), {})
        intel_only = sysfs([("card0", "0x8086", [("eDP-1", "connected")])])
        self.assertEqual(bridge.mpv_gpu_env(intel_only), {})
        self.assertEqual(bridge.mpv_gpu_env("/nonexistent"), {})

    def test_speed_is_clamped(self):
        self.assertEqual(bridge.clamp_speed("9"), 3.0)
        self.assertEqual(bridge.clamp_speed("0.1"), 0.5)
        self.assertEqual(bridge.clamp_speed("junk"), 1.0)

    def test_gzip_bomb_is_refused(self):
        bomb = gzip.compress(b"\0" * (bridge.SHOW_MAX_BYTES + 10))
        with self.assertRaises(bridge.ResponseTooLarge):
            bridge.gunzip_bounded(bomb, bridge.SHOW_MAX_BYTES)
        self.assertEqual(bridge.gunzip_bounded(gzip.compress(b"{}"), 100), b"{}")

    def test_show_redirect_to_a_foreign_host_is_refused(self):
        responses = [(302, b"", {"Location": "https://evil.example/x.json"})]
        with mock.patch.object(bridge, "http_raw", side_effect=lambda *a, **k: responses.pop(0)):
            with self.assertRaises(bridge.ApiError) as ctx:
                bridge.fetch_show(PODCAST_A)
        self.assertIn("unexpected", ctx.exception.message)

    def test_show_fetch_never_sends_the_token(self):
        seen = []

        def fake(method, url, headers=None, data=None, timeout=0, limit=0):
            seen.append(headers or {})
            if len(seen) == 1:
                return 302, b"", {"Location": "https://podcasts.pocketcasts.com/x/episodes_full_1.json"}
            return 200, gzip.compress(b'{"podcast": {"title": "T", "episodes": []}}'), {"Content-Encoding": "gzip"}

        with mock.patch.object(bridge, "http_raw", side_effect=fake):
            self.assertEqual(bridge.fetch_show(PODCAST_A)["title"], "T")
        for headers in seen:
            self.assertNotIn("Authorization", headers)

    def test_child_environment_is_closed(self):
        with mock.patch.dict(os.environ, {"LD_PRELOAD": "/tmp/evil.so", "BASH_ENV": "/tmp/x", "HOME": "/home/u",
                                          "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1/bus"}):
            env = bridge.child_env()
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("BASH_ENV", env)
        self.assertEqual(env["PATH"], bridge.TRUSTED_PATH)
        self.assertIn("DBUS_SESSION_BUS_ADDRESS", env)


class StateFiles(TempHome):
    def test_a_home_given_through_dots_is_that_folder_and_an_unusable_one_stops_the_call(self):
        # Strict review 14 (an incident): HOME=<clone>/../th was dropped as not
        # normalized, and the bridge fell back to the account's real home,
        # acting on the real state and Pocket Casts account. In process, with
        # the account's own home faked too: a regression here must not reach
        # the real one.
        fallback = os.path.join(self.home, "the-accounts-own-home")
        dotted = os.path.join(self.home, "sub", "..", "th")
        with mock.patch.object(bridge.pwd, "getpwuid", lambda uid: mock.Mock(pw_dir=fallback)):
            with mock.patch.dict(os.environ, {"HOME": dotted, "XDG_STATE_HOME": dotted + "/state"}):
                bridge.scrub_environment()
                self.assertEqual(bridge.home(), os.path.join(self.home, "th"))
                self.assertEqual(bridge.xdg_home("XDG_STATE_HOME", ".local", "state"), os.path.join(self.home, "th", "state"))
            # (Strict review 15, N1: an empty HOME fell back to the account's.)
            for name, value in (("HOME", "th"), ("HOME", "")):
                with mock.patch.dict(os.environ, {name: value}):
                    with self.assertRaises(bridge.ApiError) as ctx:
                        bridge.scrub_environment()
                    self.assertEqual(ctx.exception.code, "bad_env")
                    out = io.StringIO()
                    with mock.patch.object(sys, "stdout", out):
                        self.assertEqual(bridge.main(["status"]), 0)
                    self.assertEqual(json.loads(out.getvalue())["code"], "bad_env")
            # An XDG variable that isn't an absolute path is ignored, as the
            # XDG spec says (a typo like `~/.local/state`): the default under
            # HOME applies, never the account's real home, and the call runs.
            for name, value, default in (("XDG_STATE_HOME", "~/.local/state", (".local", "state")),
                                         ("XDG_CACHE_HOME", "relative/cache", (".cache",))):
                with mock.patch.dict(os.environ, {"HOME": self.home, name: value}):
                    bridge.scrub_environment()
                    self.assertNotIn(name, os.environ)
                    self.assertEqual(bridge.xdg_home(name, *default), os.path.join(self.home, *default))
            with mock.patch.dict(os.environ, {"HOME": self.home, "XDG_RUNTIME_DIR": "//run/x"}):
                bridge.scrub_environment()
                self.assertNotIn("XDG_RUNTIME_DIR", os.environ)
            with mock.patch.dict(os.environ, {"HOME": self.home, "XDG_STATE_HOME": "relative/state"}):
                out = io.StringIO()
                with mock.patch.object(sys, "stdout", out):
                    self.assertEqual(bridge.main(["status"]), 0)
                self.assertTrue(json.loads(out.getvalue())["ok"], out.getvalue())
        self.assertFalse(os.path.exists(fallback))

    def test_state_is_private(self):
        bridge.save_auth({"access_token": "a", "refresh_token": "r"})
        path = os.path.join(self.state, "auth.json")
        self.assertEqual(mode_of(path), 0o600)
        self.assertEqual(mode_of(self.state), 0o700)
        self.assertEqual(bridge.load_auth()["refresh_token"], "r")

    def test_symlinked_auth_is_refused(self):
        bridge.save_auth({"access_token": "a"})
        path = os.path.join(self.state, "auth.json")
        os.unlink(path)
        target = os.path.join(self.home, "elsewhere.json")
        with open(target, "w") as fh:
            fh.write("{}")
        os.symlink(target, path)
        with self.assertRaises(bridge.UnsafePath):
            bridge.load_auth()

    def test_auth_open_to_others_is_refused(self):
        bridge.save_auth({"access_token": "a"})
        os.chmod(os.path.join(self.state, "auth.json"), 0o644)
        with self.assertRaises(bridge.UnsafePath):
            bridge.load_auth()

    def test_signed_out_status(self):
        result = run_bridge("status")
        self.assertTrue(result["ok"])
        self.assertFalse(result["data"]["authenticated"])

    def test_login_needs_stdin_not_argv(self):
        result = run_bridge("login", stdin="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "bad_args")
        with self.assertRaises(SystemExit):
            with mock.patch.object(sys, "stderr", io.StringIO()):
                bridge.build_parser().parse_args(["login", "--password", "x"])


class TokenRefresh(TempHome):
    def test_401_refreshes_once_then_retries(self):
        bridge.save_auth({"access_token": "old", "refresh_token": "r1", "expires_at": time.time() + 3600})
        calls = []

        def fake_post(path, body, token="", timeout=None):
            calls.append((path, token))
            if path == "/user/token":
                return 200, {"accessToken": "new", "refreshToken": "r2", "expiresIn": 3600}
            return (401, {}) if token == "old" else (200, {"ok": 1})

        with mock.patch.object(bridge, "post_json", side_effect=fake_post):
            bridge._AUTH = None
            self.assertEqual(bridge.api("/user/in_progress"), {"ok": 1})
        self.assertEqual([c[0] for c in calls], ["/user/in_progress", "/user/token", "/user/in_progress"])
        self.assertEqual(bridge.load_auth()["refresh_token"], "r2")

    def test_rejected_refresh_marks_reauth(self):
        bridge.save_auth({"access_token": "old", "refresh_token": "r1", "expires_at": 0})
        with mock.patch.object(bridge, "post_json", return_value=(401, {})):
            bridge._AUTH = None
            with self.assertRaises(bridge.ApiError) as ctx:
                bridge.api("/user/in_progress")
        self.assertEqual(ctx.exception.code, "reauth")
        self.assertTrue(bridge.load_auth()["needs_reauth"])


# ------------------------------------------------- fake Pocket Casts server

class FakePocketCasts(http.server.BaseHTTPRequestHandler):
    """Just enough of api.pocketcasts.com and the show CDN to drive the
    bridge, with a log of every write the bridge makes."""

    state = None

    def log_message(self, *args):
        pass

    def reply(self, status, payload, gz=False, headers=None):
        body = json.dumps(payload).encode("utf-8") if not isinstance(payload, bytes) else payload
        if gz:
            body = gzip.compress(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def trickle(self, data):
        """Send `data` at the state's `rate` (bytes a second, like a real
        link: mpv's duration estimate and cache then see it arrive), or all at
        once."""
        rate = self.state.get("rate")
        if not rate:
            self.wfile.write(data)
            return
        step = max(1, rate // 20)
        try:
            for at in range(0, len(data), step):
                self.wfile.write(data[at:at + step])
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass  # mpv let go (a seek, the player closed)

    def do_GET(self):
        s = self.state
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/hls/"):
            # An HLS episode: a playlist and its segments; from `hlsCutAt` on,
            # segments fail (the network went).
            name = path.rsplit("/", 1)[1]
            segment = re.match(r"seg(\d+)\.ts$", name)
            if segment and int(segment.group(1)) >= s.get("hlsCutAt", 10 ** 6):
                # 403 (the network went), or `hlsEmpty`: an empty 200, which
                # FFmpeg's network layer doesn't complain about at all.
                self.send_response(200 if s.get("hlsEmpty") else 403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            blob = s["hls"][name]
            self.send_response(200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
            return
        if path.startswith("/audio/") and s.get("expired"):
            # The episode's (signed, expiring) link has run out, or its host
            # went: every new request gets an error page (the feed proxy
            # answers a connection it can't make with a 403 too).
            page = b"<html>expired</html>"
            self.send_response(s["expired"])
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            self.close_connection = True
            return
        if path.startswith("/audio/"):
            # Byte ranges, as real podcast hosts serve them, so mpv can start
            # a freshly loaded episode part way through.
            name = path.rsplit("/", 1)[1].split(".")[0]
            blob = s.get("media", {}).get(name, s["audio"])
            cut = s.get("cut", {}).get(name)
            if s.get("slowaudio", {}).get(name):  # a slow host: the first byte takes a while
                time.sleep(s["slowaudio"][name])
            if name in s.get("hang", {}) and not (s.get("hangResume") and s.get("hangServed", {}).get(name)
                                                  and time.time() >= s.get("hangUntil", 0)):
                # The link stalls part way: the first `hang` bytes, then
                # nothing for `hangFor` seconds with the connection open, then
                # it closes; reconnects get nothing. With `hangResume` the link
                # comes back: the rest arrives, and requests after the stall
                # are served.
                if s.setdefault("hangServed", {}).get(name):
                    self.close_connection = True
                    return
                s["hangServed"][name] = True
                s["hangUntil"] = time.time() + s.get("hangFor", 60)
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                if not s.get("hangNoRanges"):
                    self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob[:s["hang"][name]])
                self.wfile.flush()
                time.sleep(s.get("hangFor", 60))
                if s.get("hangResume"):  # the link comes back: the rest arrives
                    try:
                        self.wfile.write(blob[s["hang"][name]:])
                    except OSError:
                        pass
                self.close_connection = True
                return
            if name in s.get("nosize", ()):
                # A host that sends no size and serves no ranges: the body
                # runs until the connection closes (cut, if asked, part way).
                if cut is not None and s.setdefault("cutServed", {}).get(name):
                    self.close_connection = True
                    return
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.end_headers()
                if cut is not None:
                    s.setdefault("cutServed", {})[name] = True
                self.trickle(blob[:cut] if cut is not None else blob)
                self.close_connection = True
                return
            if name in s.get("noranges", ()):
                # A host that sends the size (Content-Length) but serves no
                # byte ranges: mpv can't start part way, nor reconnect.
                if cut is not None and s.setdefault("cutServed", {}).get(name):
                    self.close_connection = True
                    return
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                if cut is not None:
                    s.setdefault("cutServed", {})[name] = True
                self.trickle(blob[:cut] if cut is not None else blob)
                self.close_connection = True
                return
            if cut is not None and s.setdefault("cutServed", {}).get(name) and s.get("cutHeal"):
                cut = None  # the network is back: mpv's reconnect is served
            if cut is not None and s.setdefault("cutServed", {}).get(name):
                if s.get("cutReply"):
                    # The host is up but failing: mpv's reconnect gets an
                    # error page (a CDN's 503, an expired link's 403), whose
                    # length FFmpeg then reports as the file's size.
                    page = b"<html><body><h1>Service Temporarily Unavailable</h1></body></html>"
                    self.send_response(s["cutReply"])
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    self.wfile.write(page)
                    self.close_connection = True
                    return
                # The network is gone: later requests (mpv reconnecting) get
                # nothing at all.
                self.close_connection = True
                return
            wanted = re.match(r"bytes=(\d+)-(\d*)$", self.headers.get("Range") or "")
            first, last = 0, len(blob) - 1
            if wanted:
                first = int(wanted.group(1))
                last = min(int(wanted.group(2) or last), last)
            self.send_response(206 if wanted else 200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Accept-Ranges", "bytes")
            if wanted:
                self.send_header("Content-Range", "bytes %d-%d/%d" % (first, last, len(blob)))
            self.send_header("Content-Length", str(last - first + 1))
            self.end_headers()
            if cut is not None:
                # The stream breaks part way: the first `cut` bytes, then the
                # connection drops.
                s["cutServed"][name] = True
                self.trickle(blob[first:min(cut, last + 1)])
                self.close_connection = True
                return
            self.trickle(blob[first:last + 1])
            return
        if path.startswith("/podcast/full/"):
            uuid = path.rsplit("/", 1)[1]
            self.reply(302, b"", headers={"Location": "/cdn/%s.json" % uuid})
            return
        if path.startswith("/cdn/"):
            uuid = path.rsplit("/", 1)[1][:-5]
            show = s["shows"][uuid]
            self.reply(200, {"podcast": {"uuid": uuid, "title": show["title"], "author": "Author",
                                         "episodes": [s["episodes"][e] for e in show["episodes"]]}}, gz=True)
            return
        self.reply(404, {})

    def do_POST(self):
        s = self.state
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        path = urllib.parse.urlsplit(self.path).path
        s["log"].append((path, body))
        if s.get("slow", {}).get(path):  # a network that hangs
            time.sleep(s["slow"][path])
        reply = s.get("episodeReply")
        if isinstance(reply, dict):
            reply = reply.get(body.get("uuid"))
        if path == "/user/episode" and not reply and s.get("unfollowed") and \
                s["episodes"].get(body.get("uuid"), {}).get("podcast") in s["unfollowed"] and \
                body.get("uuid") not in s.get("recorded", ()):
            # No record: a show you never followed (`recorded`: episodes of one
            # you listened to all the same, which have one).
            reply = (404, b'{"errorMessage": "not found"}')
        if path == "/user/episode" and reply:
            # Pocket Casts answers the episode lookup oddly (a 404, an empty
            # 200, a redirect): for every episode, or by uuid.
            status, blob = reply
            self.send_response(status)
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
            return
        fails = s.setdefault("fail", {})
        if fails.get(path, 0) > 0:  # a dropped request, as when the network goes
            fails[path] -= 1
            self.reply(s.get("failStatus", {}).get(path, 503), {})  # (or another status: a redirect)
            return
        lost = s.setdefault("lostReply", {})
        if lost.get(path, 0) > 0:  # it went through, but the reply never came back
            lost[path] -= 1
            self.reply = lambda status, payload, **kw: FakePocketCasts.reply(self, 503, {})
        token = (self.headers.get("Authorization") or "").replace("Bearer ", "")
        if path == "/user/login_pocket_casts":
            if body.get("password") == PASSWORD:
                s["signedIn"] = (body["email"], s.get("accountUuids", {}).get(body["email"], "u"))
                self.reply(200, {"email": body["email"], "uuid": s.get("accountUuids", {}).get(body["email"], "u"),
                                 "accessToken": "t1", "tokenType": "Bearer",
                                 "expiresIn": 3600, "refreshToken": "r1"})
            else:
                self.reply(401, {"errorMessage": "Wrong password", "errorMessageId": "login_password_incorrect"})
            return
        if path == "/user/token":
            who = s.get("signedIn") or ("me@example.com", "u")  # (the account that signed in, not always the first)
            self.reply(200, {"email": who[0], "uuid": who[1], "accessToken": "t2", "expiresIn": 3600, "refreshToken": "r2"})
            return
        if token not in ("t1", "t2"):
            self.reply(401, {})
            return
        eps = s["episodes"]
        if path == "/user/podcast/list":
            def show(u, v):
                entry = {"uuid": u, "title": v["title"], "author": "Author", "lastEpisodePublished": "2026-09-30T00:00:00Z"}
                skips = s.get("showSettings", {}).get(u, {})
                if skips:  # as the real API sends them: top level and in settings
                    entry.update(skips)
                    entry["settings"] = {k: {"value": n, "changed": True} for k, n in skips.items()}
                return entry
            self.reply(200, {"podcasts": [] if s.get("showsEmpty") else  # (an odd reply: an empty list)
                             [show(u, v) for u, v in s["shows"].items() if u not in s.get("unfollowed", ())]})
        elif path == "/up_next/list":
            # `noSync`: episodes whose sync data the reply leaves out. As the
            # real reply does (checked live 2026-11-24), an episode not started
            # has no playedUpTo in it; `syncNoPosition`: others without one.
            def sync_entry(u):
                entry = {"uuid": u, "duration": eps[u]["duration"]}
                if s["progress"].get(u) and u not in s.get("syncNoPosition", ()):
                    entry["playedUpTo"] = s["progress"][u]
                if s.get("syncStatus"):  # each episode's playingStatus, as showPlayStatus asks
                    entry["playingStatus"] = s["status"].get(u, 1)
                return entry
            self.reply(200, {"serverModified": 1, "episodes": [
                {"uuid": u, "title": eps[u]["title"], "url": eps[u]["url"], "podcast": eps[u]["podcast"],
                 "published": eps[u]["published"]} for u in s["upnext"]],
                "episodeSync": [sync_entry(u) for u in s["upnext"] if u not in s.get("noSync", ())]})
        elif path in ("/up_next/play_now", "/up_next/play_next", "/up_next/play_last"):
            uuid = body["episode"]["uuid"]
            if uuid in s["upnext"]:
                s["upnext"].remove(uuid)
            if path == "/up_next/play_last":
                s["upnext"].append(uuid)
            else:
                s["upnext"].insert(0 if path.endswith("now") else 1, uuid)
            self.reply(200, {})
        elif path == "/up_next/remove":
            s["upnext"] = [u for u in s["upnext"] if u not in body["uuids"]]
            self.reply(200, {})
        elif path == "/sync/update_episode":
            s["progress"][body["uuid"]] = body["position"]
            s["status"][body["uuid"]] = body["status"]
            if eps.get(body["uuid"], {}).get("podcast") in s.get("unfollowed", ()):
                s.setdefault("recorded", set()).add(body["uuid"])  # a push creates the record
            self.reply(200, {})
        elif path == "/user/episode":
            e = dict(eps[body["uuid"]])
            e.update({"podcastUuid": e.pop("podcast"), "playedUpTo": s["progress"].get(body["uuid"], 0),
                      "playingStatus": s["status"].get(body["uuid"], 1)})
            self.reply(200, e)
        elif path in ("/user/in_progress", "/user/new_releases"):
            # In Progress: episodes in progress, but those it leaves out
            # (`notListed`: the real list is capped).
            listed = [u for u in eps if path.endswith("new_releases")
                      or (s["status"].get(u) == 2 and u not in s.get("notListed", ()))]
            self.reply(200, {"episodes": [dict(eps[u], podcastUuid=eps[u]["podcast"], playedUpTo=s["progress"].get(u, 0))
                                          for u in listed]})
        elif path == "/user/podcast/episodes":
            self.reply(200, {"episodes": [{"uuid": u, "playedUpTo": s["progress"].get(u, 0),
                                           "playingStatus": s["status"].get(u, 1)} for u in s["shows"][body["uuid"]]["episodes"]]})
        else:
            self.reply(404, {})


def make_gapped_audio():
    """7 s: a tone, 2 s of silence, a tone, 2 s of silence, a tone."""
    out = tempfile.mktemp(suffix=".mp3")
    tone = "sine=frequency=440:duration=1"
    subprocess.run(["/usr/bin/ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", tone + ",apad=pad_dur=2",
                    "-f", "lavfi", "-i", tone + ",apad=pad_dur=2", "-f", "lavfi", "-i", tone,
                    "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", "-q:a", "2", out], check=True)
    with open(out, "rb") as fh:
        blob = fh.read()
    os.unlink(out)
    return blob


def make_video(seconds):
    """A small test-pattern video with a tone, as a video podcast would be."""
    out = tempfile.mktemp(suffix=".mp4")
    subprocess.run(["/usr/bin/ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x180:rate=15:duration=%d" % seconds, "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=%d" % seconds, "-shortest", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", "-movflags", "+faststart", out], check=True)
    with open(out, "rb") as fh:
        blob = fh.read()
    os.unlink(out)
    return blob


def encode(args, suffix):
    """A file ffmpeg makes from `args` (sources and options), as bytes."""
    with tempfile.TemporaryDirectory() as folder:
        out = os.path.join(folder, "out" + suffix)
        subprocess.run(["/usr/bin/ffmpeg", "-loglevel", "error", "-n"] + args + [out], check=True)
        with open(out, "rb") as fh:
            return fh.read()


def make_hls(seconds):
    """An HLS episode of `seconds`: its playlist and 3-second segments."""
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(["/usr/bin/ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=%d" % seconds,
                        "-c:a", "aac", "-b:a", "32k", "-f", "hls", "-hls_time", "3", "-hls_playlist_type", "vod",
                        "-hls_segment_filename", os.path.join(folder, "seg%d.ts"), os.path.join(folder, "out.m3u8")],
                       check=True)
        return {name: open(os.path.join(folder, name), "rb").read() for name in os.listdir(folder)}


def make_stitched_mp3(ad_seconds=10, ad_rate="192k", body_seconds=50, body_rate="32k"):
    """An MP3 as a dynamic-ad stitcher makes one: two parts at different
    bitrates and no VBR header, so mpv estimates the duration from the first
    frames' bitrate (18 s of 60 here)."""
    ad = encode(["-f", "lavfi", "-i", "sine=frequency=880:duration=%d" % ad_seconds, "-b:a", ad_rate,
                 "-write_xing", "0", "-id3v2_version", "0"], ".mp3")
    body = encode(["-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % body_seconds, "-b:a", body_rate,
                   "-write_xing", "0", "-id3v2_version", "0"], ".mp3")
    return ad + body


def make_audio(seconds):
    out = tempfile.mktemp(suffix=".mp3")
    subprocess.run(["/usr/bin/ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=%d" % seconds, "-q:a", "9", out], check=True)
    with open(out, "rb") as fh:
        blob = fh.read()
    os.unlink(out)
    return blob


NEEDS_PLAYER = unittest.skipUnless(os.path.exists("/usr/bin/mpv") and os.path.exists("/usr/bin/ffmpeg"),
                                   "needs mpv and ffmpeg")


class PlayerTestCase(TempHome):
    """The fake server and a real (muted) mpv, for tests that play audio."""

    AUDIO_SECONDS = 4

    @classmethod
    def setUpClass(cls):
        cls.audio = make_audio(cls.AUDIO_SECONDS)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakePocketCasts)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        super().setUp()
        # Settings as after the service's first start (the old bar entry
        # copied in: the defaults). Before that, autoplay stays off.
        bridge.save_state("settings.json", {})
        ep = lambda uuid, podcast, title, day: {"uuid": uuid, "podcast": podcast, "title": title,
                                                "url": self.base + "/audio/%s.mp3" % uuid, "duration": 4,
                                                "published": "2026-09-%02dT08:00:00Z" % day}
        FakePocketCasts.state = {
            "log": [], "audio": self.audio, "progress": {}, "status": {},
            "shows": {PODCAST_A: {"title": "Show A", "episodes": [EP_1, EP_2]},
                      PODCAST_B: {"title": "Show B", "episodes": [EP_3]}},
            "episodes": {EP_1: ep(EP_1, PODCAST_A, "One, with a comma", 28),
                         EP_2: ep(EP_2, PODCAST_A, "Two", 29),
                         EP_3: ep(EP_3, PODCAST_B, "Three", 30)},
            "upnext": [EP_1, EP_2],
        }
        local = ("127.0.0.1",)
        for name, value in (("API", self.base), ("PODCAST_API", self.base),
                            ("_OPENER", bridge.build_opener(allow_plain_http=True)),
                            ("url_host_is", lambda url, hosts: urllib.parse.urlsplit(url).hostname in local),
                            ("podcast_art", lambda uuid: ""),
                            ("MPV_EXTRA_ARGS", ("--ao=null",)),
                            # No mpv-mpris: a test player would join the real
                            # session bus, a media player on the desktop.
                            ("mpris_script", lambda: ""),
                            # The FFmpeg self-check runs by itself in tests of its own.
                            ("start_watch_check", lambda version: None),
                            # Never the real Hyprland (VideoWindow records its calls).
                            ("hyprctl", lambda *args: ""),
                            # The sleep guard lowers these for its own short
                            # process; here every test starts from the real ones.
                            ("HTTP_TIMEOUT", bridge.HTTP_TIMEOUT), ("TOKEN_TIMEOUT", bridge.TOKEN_TIMEOUT),
                            ("REFRESH_ALLOWED", True),
                            # The fake server is on 127.0.0.1, which the feed
                            # proxy never fetches from: allow it here only.
                            # Playback still goes through a real FeedProxy.
                            ("feed_address_allowed", lambda address, allow_local: True),
                            ("same_address", lambda a, b: False),  # (a connection to oneself)
                            ("start_feed_proxy", self.thread_proxy)):
            patcher = mock.patch.object(bridge, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.quit_mpv)
        bridge.save_prefs({"volume": 0})

    def thread_proxy(self, watch_pid):
        proxy = bridge.FeedProxy("ab" * 16, allow_local=lambda: True)
        self.proxied = getattr(self, "proxied", [])
        handle = proxy.handle

        def counting(conn):
            peeked = conn.recv(512, socket.MSG_PEEK)
            self.proxied.append(peeked.split(b"\r\n", 1)[0].decode("latin-1"))
            handle(conn)
        proxy.handle = counting
        stop_r, stop_w = os.pipe()
        threading.Thread(target=proxy.serve, kwargs={"stop_fd": stop_r}, daemon=True).start()
        self.addCleanup(os.write, stop_w, b"x")
        return proxy.url()

    def quit_mpv(self):
        player = bridge.Mpv.connect()
        if player:
            with player:
                try:
                    player.command("quit")
                except bridge.ApiError:
                    pass
        # A player the bridge's own code can't reach (a mutant, a crash) still
        # ends with its test: found by this test's socket in its command line.
        mine = ("--input-ipc-server=" + os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/nonexistent"),
                                                     "omarchy-legato", "mpv.sock")).encode()
        for pid in filter(str.isdigit, os.listdir("/proc")):
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as fh:
                    words = fh.read().split(b"\0")
            except OSError:
                continue
            if mine in words:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except OSError:
                    pass
        # The bridge runs in this process here, so its players are this
        # process's children: reap the ones that have ended.
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break

    @contextlib.contextmanager
    def woken(self, seconds):
        """Calls made after the machine slept `seconds`: each a process of
        its own, whose suspend clock starts after the sleep (the bridge runs
        in this process here, so its start is moved on with the clock)."""
        later = bridge._SLEEP_BASE + seconds
        with mock.patch.object(bridge, "sleep_offset", lambda: later), \
                mock.patch.object(bridge, "_SLEEP_BASE", later):
            yield

    def mpv_paused(self):
        with bridge.Mpv.connect() as player:
            return player.get("pause")

    def mpv_running(self):
        player = bridge.Mpv.connect()
        if player:
            player.close()
        return player is not None

    @property
    def fake(self):
        return FakePocketCasts.state

    def writes(self, path):
        return [body for p, body in self.fake["log"] if p == path]

    def pushes_of(self, uuid):
        return [b for b in self.writes("/sync/update_episode") if b["uuid"] == uuid]

    def login(self):
        result = run_bridge("login", stdin=json.dumps({"email": "me@example.com", "password": PASSWORD}))
        self.assertTrue(result["ok"], result)

    def wait_for(self, predicate, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.2)
        self.fail("timed out")


@NEEDS_PLAYER
class EndToEnd(PlayerTestCase):
    """Every subcommand against the fake server, with a real (muted) mpv."""

    def test_wrong_password_is_reported_and_nothing_is_stored(self):
        result = run_bridge("login", stdin=json.dumps({"email": "me@example.com", "password": "nope"}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "login_failed")
        self.assertIn("Wrong password", result["error"])
        self.assertEqual(bridge.load_auth(), {})

    def test_password_is_never_written(self):
        self.login()
        run_bridge("podcasts")
        for dirpath, _, files in os.walk(self.home):
            for name in files:
                with open(os.path.join(dirpath, name), "rb") as fh:
                    self.assertNotIn(PASSWORD.encode(), fh.read(), name)
        self.assertEqual(bridge.load_auth()["refresh_token"], "r1")

    def test_lists(self):
        self.login()
        podcasts = run_bridge("podcasts")["data"]["items"]
        self.assertEqual({p["name"] for p in podcasts}, {"Show A", "Show B"})
        up_next = run_bridge("up-next")["data"]["items"]
        self.assertEqual([i["uuid"] for i in up_next], [EP_1, EP_2])
        self.assertEqual(up_next[0]["show"], "Show A")
        episodes = run_bridge("episodes", PODCAST_A)["data"]
        self.assertEqual(episodes["podcast"]["name"], "Show A")
        self.assertEqual([i["uuid"] for i in episodes["items"]], [EP_2, EP_1])  # newest first
        newest = run_bridge("new-releases")["data"]["items"]
        self.assertEqual(newest[0]["uuid"], EP_3)

    def test_queue_and_mark(self):
        self.login()
        self.assertTrue(run_bridge("queue", "last", EP_3, "--podcast", PODCAST_B)["ok"])
        self.assertEqual(self.fake["upnext"], [EP_1, EP_2, EP_3])
        self.assertTrue(run_bridge("queue", "remove", EP_1)["ok"])
        self.assertEqual(self.fake["upnext"], [EP_2, EP_3])
        self.assertTrue(run_bridge("mark", "played", EP_2, "--podcast", PODCAST_A)["ok"])
        self.assertEqual(self.fake["status"][EP_2], bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"], [EP_3])

    def test_play_sync_finish_and_autoplay(self):
        self.login()
        played = run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertTrue(played["ok"], played)
        self.assertEqual(played["data"]["item"]["uuid"], EP_1)
        self.assertEqual(self.writes("/up_next/play_now")[0]["episode"]["uuid"], EP_1)

        view = self.wait_for(lambda: (lambda v: v if v["active"] and v["position"] > 0.5 else None)(run_bridge("player")["data"]))
        self.assertTrue(view["playing"])
        self.assertEqual(view["volume"], 0)

        # Pausing pushes the position to Pocket Casts straight away.
        paused = run_bridge("pause")["data"]
        self.assertFalse(paused["playing"])
        last = self.writes("/sync/update_episode")[-1]
        self.assertEqual((last["uuid"], last["status"]), (EP_1, bridge.STATUS_IN_PROGRESS))
        self.assertGreaterEqual(last["position"], 0)

        # Playing on to the end marks it played, takes it off Up Next and
        # starts the next episode.
        run_bridge("resume")
        view = self.wait_for(lambda: (lambda v: v if v["item"] and v["item"]["uuid"] == EP_2 else None)(run_bridge("player")["data"]))
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertNotIn(EP_1, self.fake["upnext"])
        self.assertEqual(self.fake["upnext"][0], EP_2)

        # Skipping with nothing left queued says so.
        skipped = run_bridge("next")
        self.assertFalse(skipped["ok"])
        self.assertEqual(skipped["code"], "nothing_queued")

        stopped = run_bridge("stop")["data"]
        self.assertFalse(stopped["active"])
        self.assertFalse(self.mpv_running())

    def test_an_episode_finished_here_stays_played(self):
        """Autoplay off (or nothing left in Up Next): the episode ends here,
        is marked played, and nothing afterwards (later polls, the idle
        unload, Stop) sets it back to in progress."""
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: self.fake["status"].get(EP_1) == bridge.STATUS_PLAYED
                      or run_bridge("player", "--no-autoplay") and False)
        view = run_bridge("player", "--no-autoplay")["data"]
        self.assertFalse(view["playing"])  # ended: no poll timer, and the idle unload may close it
        state = bridge.load_playback()
        state["lastSyncAt"] -= 31  # the next poll, half a minute on
        bridge.save_playback(state)
        run_bridge("player", "--no-autoplay")
        run_bridge("stop", "--if-paused")      # the idle unload
        self.assertFalse(self.mpv_running())
        last = self.writes("/sync/update_episode")[-1]
        self.assertEqual((last["uuid"], last["status"]), (EP_1, bridge.STATUS_PLAYED))
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def end_without_autoplay(self):
        """Play One to its end with autoplay off; returns once it's marked played."""
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: self.fake["status"].get(EP_1) == bridge.STATUS_PLAYED
                      or run_bridge("player", "--no-autoplay") and False)
        return run_bridge("player", "--no-autoplay")["data"]

    def test_another_file_in_mpv_is_never_pushed_as_the_loaded_episode(self):
        # Strict review 10 (1): mpv playing a file other than the one
        # recorded (a load cut off before it was recorded; another program
        # opening one through mpv-mpris) had its position pushed as the
        # recorded episode's by pause and stop, rewinding every device.
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 2.5)
        before = len(self.pushes_of(EP_1))
        other = self.fake["episodes"][EP_2]["url"]
        with bridge.Mpv.connect() as player:  # while EP_1 plays, as mpv-mpris's OpenUri would
            player.command("loadfile", other, "replace", -1, "pause=no")
            self.wait_for(lambda: player.get("path") == other and (player.get("time-pos") or 0) > 0.2)
        run_bridge("pause")  # a forced push: the stretch was confirmed and recent
        self.assertEqual(len(self.pushes_of(EP_1)), before)
        run_bridge("stop")   # paused, moved more than a second from its push
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_a_play_cut_off_fetching_the_cover_has_recorded_the_new_episode(self):
        # The cover is fetched last: a play cut off there (the call's
        # deadline, a slow host) has recorded what mpv now plays.
        self.login()
        with mock.patch.object(bridge, "cache_art", side_effect=bridge.DeadlinePassed()):
            with self.assertRaises(bridge.DeadlinePassed):
                with bridge.StateLock():
                    bridge.play_item(bridge.resolve_episode(EP_2, PODCAST_A), bridge.load_prefs())
        self.assertEqual(bridge.load_playback()["episode"]["uuid"], EP_2)

    def test_settings_json_decides_autoplay_whoever_polls(self):
        # Strict review 10: a second service (a replacement bar on two
        # screens) or a hand edit: the bridge acts on settings.json itself.
        run_bridge("settings", "set", "--", "autoplay", "false")
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: self.fake["status"].get(EP_1) == bridge.STATUS_PLAYED
                      or run_bridge("player") and False)  # polls that say nothing about autoplay
        view = run_bridge("player")["data"]
        self.assertEqual((view["item"] or {}).get("uuid"), EP_1)
        self.assertNotIn(EP_2, [b["episode"]["uuid"] for b in self.writes("/up_next/play_now")])

    def test_before_the_import_the_callers_choice_decides_autoplay(self):
        # Strict review 12 (fit L4): after an update from 1.0, Omarchy keeps
        # 1.0's service, which never imports the bar entry; the bridge kept
        # autoplay off (and the player never unloading) until a restart.
        # Before the import it follows the caller: 1.0's passes its entry's
        # choice, 1.1's the safe one.
        os.remove(os.path.join(self.home, ".local/state/omarchy-legato/settings.json"))
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: (lambda v: v if v["item"] and v["item"]["uuid"] == EP_2 else None)(run_bridge("player")["data"]))

    def test_settings_json_decides_the_idle_unload_and_pause_before_sleep(self):
        run_bridge("settings", "set", "--", "unloadAfterMinutes", "0")
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        run_bridge("pause")
        self.assertTrue(run_bridge("stop", "--if-paused")["data"]["active"])  # never unloads
        self.assertTrue(self.mpv_running())
        run_bridge("settings", "set", "--", "pauseOnSleep", "false")
        paused = []
        with mock.patch.object(bridge, "wait_for_sleep", lambda stdout: True), \
                mock.patch.object(bridge, "pause_for_sleep", lambda: paused.append(1) or True):
            before = signal.getsignal(signal.SIGTERM)
            try:
                result = run_bridge("sleepguard")
            finally:
                signal.signal(signal.SIGTERM, before)
        self.assertEqual((result["data"]["sleeping"], result["data"]["paused"], paused), (True, False, []))

    def test_status_says_whether_a_player_runs(self):
        self.login()
        self.assertFalse(run_bridge("status")["data"]["running"])
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertTrue(run_bridge("status")["data"]["running"])

    def test_mpv_keeps_a_podcast_sized_buffer(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        with bridge.Mpv.connect() as player:
            self.assertEqual(player.get("demuxer-max-bytes"), 64 * 1024 * 1024)  # not mpv's 150 MB

    def test_the_show_list_is_cached_ten_minutes(self):
        self.login()
        lists = lambda: len(self.writes("/user/podcast/list"))
        run_bridge("podcasts")
        first = lists()
        run_bridge("podcasts")
        self.assertEqual(lists(), first)
        run_bridge("podcasts", "--force")
        self.assertEqual(lists(), first + 1)

    def test_play_after_the_end_plays_it_again(self):
        view = self.end_without_autoplay()
        self.assertTrue(view["ended"])
        played = run_bridge("resume")["data"]
        self.assertTrue(played["playing"])
        self.assertFalse(played["ended"])
        self.assertLess(played["position"], 2)
        last = self.writes("/sync/update_episode")[-1]
        self.assertEqual((last["uuid"], last["status"], last["position"]), (EP_1, bridge.STATUS_IN_PROGRESS, 0))
        # Pocket Casts' "played" from before must not stop it a while later.
        state = bridge.load_playback()
        state["lastSyncAt"] -= 600
        bridge.save_playback(state)
        self.assertTrue(run_bridge("player", "--no-autoplay")["data"]["playing"])
        self.assertTrue(self.mpv_running())
        # And at its end again, it's marked played again.
        self.wait_for(lambda: run_bridge("player", "--no-autoplay")["data"]["ended"])
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_dragged_back_from_the_end_it_plays_on_in_progress(self):
        # The drag lands before mpv pauses itself at the end (keep-open-pause,
        # under half a second; afterwards a drag waits there paused, as
        # test_a_drag_back_after_the_end_isnt_pushed_as_in_progress has it).
        # mpv's own pause is held off so that moment can't slip by under load.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        with bridge.Mpv.connect() as player:
            player.set("keep-open-pause", False)
        self.wait_for(lambda: self.fake["status"].get(EP_1) == bridge.STATUS_PLAYED
                      or run_bridge("player", "--no-autoplay") and False)
        view = run_bridge("seek", "1")["data"]
        self.assertTrue(view["playing"])
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)
        self.assertEqual(bridge.load_playback()["handledEnd"], "")

    def test_play_at_the_end_takes_what_was_queued_since(self):
        self.fake["upnext"] = [EP_1]
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        # Autoplay on, but nothing follows: it ends and stays there.
        view = self.wait_for(lambda: (lambda v: v if v["ended"] else None)(run_bridge("player")["data"]))
        self.assertFalse(view["playing"])
        self.fake["upnext"].append(EP_2)  # queued later, on the phone
        played = run_bridge("resume")["data"]
        self.assertEqual(played["item"]["uuid"], EP_2)
        self.assertEqual(self.fake["upnext"][0], EP_2)

    def test_a_played_mark_that_failed_is_retried(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.fake["fail"] = {"/sync/update_episode": 1, "/up_next/remove": 1}
        # Two plays on (autoplay); One is still unmarked and on Up Next.
        self.wait_for(lambda: (lambda v: v if v["item"] and v["item"]["uuid"] == EP_2 else None)(run_bridge("player")["data"]))
        self.assertEqual(self.fake["upnext"][0], EP_2)  # put on top all the same
        self.assertFalse(bridge.load_playback()["atTop"] is False)
        state = bridge.load_playback()
        state["pendingFinish"][0]["tried"] -= 60  # a minute on
        bridge.save_playback(state)
        run_bridge("player")  # the next poll tells Pocket Casts
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertNotIn(EP_1, self.fake["upnext"])
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])

    def test_a_removal_that_lands_on_retry_clears_at_top(self):
        # Review finding: atTop stayed true when Up Next's removal only
        # succeeded on a retry, so a replay was later switched away.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.fake["fail"] = {"/up_next/remove": 1}
        self.wait_for(lambda: self.fake["status"].get(EP_1) == bridge.STATUS_PLAYED
                      or run_bridge("player", "--no-autoplay") and False)
        self.assertIn(EP_1, self.fake["upnext"])
        self.assertIs(bridge.load_playback()["atTop"], True)
        state = bridge.load_playback()
        state["pendingFinish"][0]["tried"] -= 60
        bridge.save_playback(state)
        run_bridge("player", "--no-autoplay")
        self.assertNotIn(EP_1, self.fake["upnext"])
        self.assertIs(bridge.load_playback()["atTop"], False)

    def test_a_finish_retried_later_never_overrides_another_device(self):
        # Strict review 11 (M2): the played mark failed; you carried on with
        # the phone; hours later a poll marked it played over the phone's
        # place and took it off Up Next.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.fake["fail"] = {"/sync/update_episode": 1, "/up_next/remove": 1}
        self.wait_for(lambda: bridge.load_playback().get("pendingFinish")
                      or run_bridge("player", "--no-autoplay") and False)
        self.fake["progress"][EP_1] = 20  # the phone carried on from where this machine left it
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        state = bridge.load_playback()
        state["pendingFinish"][0]["tried"] -= 60
        bridge.save_playback(state)
        run_bridge("player", "--no-autoplay")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)
        self.assertIn(EP_1, self.fake["upnext"])
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])  # dropped: the phone's say stands

    def test_play_at_the_end_of_a_file_legato_didnt_record_never_pushes_0(self):
        # Strict review 11 (H1): mpv played another file to its end (another
        # program's OpenUri, a cut-off load); Play pushed the recorded
        # episode at 0. Now it starts over through Pocket Casts.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 1.5)
        run_bridge("pause")
        pushed = self.fake["progress"][EP_1]
        other = self.fake["episodes"][EP_3]["url"]
        with bridge.Mpv.connect() as player:
            player.command("loadfile", other, "replace", -1, "pause=no")
            self.wait_for(lambda: player.get("path") == other and player.get("eof-reached") is True, timeout=20)
        before = len(self.pushes_of(EP_1))
        view = run_bridge("toggle")["data"]
        self.assertGreaterEqual(pushed, 1)
        self.assertNotIn(0, [b["position"] for b in self.pushes_of(EP_1)[before:]])  # never "from the top"
        self.assertEqual(self.fake["progress"][EP_1], pushed)
        self.assertEqual((view["item"] or {}).get("uuid"), EP_1)  # Pocket Casts' episode, from its place

    def test_a_drag_back_on_a_file_legato_didnt_record_reopens_nothing(self):
        self.end_without_autoplay()  # EP_1 ended here, marked played
        other = self.fake["episodes"][EP_3]["url"]
        with bridge.Mpv.connect() as player:
            player.command("loadfile", other, "replace", -1, "pause=no")
            self.wait_for(lambda: player.get("path") == other and (player.get("time-pos") or 0) > 0.3)
        before = len(self.pushes_of(EP_1))
        run_bridge("seek", "--relative", "--", "-0.2")
        self.assertEqual(len(self.pushes_of(EP_1)), before)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_a_play_cut_off_during_the_load_has_recorded_what_mpv_plays(self):
        # The deadline firing while mpv opens the new episode waits until
        # playback.json names it.
        self.login()
        real_wait = bridge.Mpv.wait_for_load
        def deadline_now(player):
            bridge._deadline_passed(signal.SIGALRM, None)  # as the alarm would, mid-load
            return real_wait(player)
        with mock.patch.object(bridge.Mpv, "wait_for_load", deadline_now):
            with self.assertRaises(bridge.DeadlinePassed):
                with bridge.StateLock():
                    bridge.play_item(bridge.resolve_episode(EP_2, PODCAST_A), bridge.load_prefs())
        self.assertEqual(bridge.load_playback()["episode"]["uuid"], EP_2)
        with bridge.Mpv.connect() as player:
            self.assertEqual(player.get("path"), self.fake["episodes"][EP_2]["url"])

    def test_a_drag_back_while_paused_after_the_end_stays_played(self):
        # Strict review 11 (M1): the poll mpv's seek event brings pushed it
        # as in progress, un-finishing it everywhere.
        self.end_without_autoplay()
        with bridge.Mpv.connect() as player:
            self.wait_for(lambda: player.get("pause") is True)  # mpv pauses itself at the end
        run_bridge("seek", "1")
        before = len(self.pushes_of(EP_1))
        run_bridge("player", "--no-autoplay", "--seeked")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_pause_is_heard_at_once_behind_a_slow_poll(self):
        # Strict review 11 (L2): a poll on a slow link holding the state lock
        # made Pause wait 10 s and fail "busy", the episode playing on.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["playing"])
        done = []
        with bridge.StateLock():
            worker = threading.Thread(target=lambda: done.append(run_bridge("pause")))
            worker.start()
            with bridge.Mpv.connect() as player:
                self.wait_for(lambda: player.get("pause") is True, timeout=2)
        worker.join(15)
        self.assertTrue(done)

    def test_a_stretch_nobody_asked_about_is_never_pushed_by_a_poll(self):
        # Strict review 11 (L3): paused here (the next resume asks first), then
        # resumed and paused straight on mpv (a media key whose resume no
        # poll saw): the poll pushed that unchecked stretch.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        run_bridge("pause")
        before = len(self.pushes_of(EP_1))
        with bridge.Mpv.connect() as player:
            player.set("pause", False)
            time.sleep(1.6)
            player.set("pause", True)
        run_bridge("player")
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_a_finish_cut_off_by_the_deadline_is_retried(self):
        # Strict review 12 (M1): handledEnd was saved before the pending
        # entry; a call cut off between (the deadline, a plugin reload)
        # left the end handled and never told.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        real = bridge.push_position
        cut = []
        def push(item, position, status=bridge.STATUS_IN_PROGRESS):
            if status == bridge.STATUS_PLAYED and not cut:
                cut.append(1)
                raise bridge.DeadlinePassed()
            return real(item, position, status)
        with mock.patch.object(bridge, "push_position", push):
            self.wait_for(lambda: bridge.load_playback().get("handledEnd") == EP_1
                          or run_bridge("player", "--no-autoplay") and False)
        state = bridge.load_playback()
        self.assertEqual([p["uuid"] for p in state["pendingFinish"]], [EP_1])
        state["pendingFinish"][0]["tried"] -= 60
        bridge.save_playback(state)
        run_bridge("player", "--no-autoplay")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_play_after_a_half_told_end_starts_the_next_episode(self):
        # Strict review 12 (M2): the removal from Up Next failed at the end;
        # Play with the player closed took the top of Up Next, the finished
        # episode itself, and pushed it in progress.
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.fake["fail"] = {"/up_next/remove": 1}
        self.wait_for(lambda: self.fake["status"].get(EP_1) == bridge.STATUS_PLAYED
                      or run_bridge("player", "--no-autoplay") and False)
        self.assertIn(EP_1, self.fake["upnext"])
        run_bridge("stop", "--if-paused")
        before = len(self.pushes_of(EP_1))
        view = run_bridge("toggle")["data"]
        self.assertEqual((view["item"] or {}).get("uuid"), EP_2)
        self.assertEqual(len(self.pushes_of(EP_1)), before)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertNotIn(EP_1, self.fake["upnext"])  # the pending removal went through first

    def test_play_after_a_half_told_end_skips_it_even_when_the_removal_fails_again(self):
        # The retry's removal fails too: the finished episode stays on top of
        # Up Next, and Play still starts the next one, pushing nothing for it.
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.fake["fail"] = {"/up_next/remove": 1}
        self.wait_for(lambda: self.fake["status"].get(EP_1) == bridge.STATUS_PLAYED
                      or run_bridge("player", "--no-autoplay") and False)
        run_bridge("stop", "--if-paused")
        self.fake["fail"] = {"/up_next/remove": 1}
        before = len(self.pushes_of(EP_1))
        view = run_bridge("toggle")["data"]
        self.assertEqual((view["item"] or {}).get("uuid"), EP_2)
        self.assertEqual(len(self.pushes_of(EP_1)), before)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    # Strict review 13 (M3, SR137): an episode that ended here and whose
    # removal from Up Next is still pending (`pendingFinish`) is never "what's
    # next". Up Next's sync data carries each episode's playingStatus here
    # (`syncStatus`, as the bridge asks for it): replayed, a played one
    # started from 0 and was pushed in progress.

    def end_ep1_with_its_removal_failing(self, failures=1000):
        self.fake["syncStatus"] = True
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.fake["fail"] = {"/up_next/remove": failures}
        # EP_1 ends here: marked played, its removal fails (pending), autoplay starts EP_2
        self.wait_for(lambda: (run_bridge("player")["data"].get("item") or {}).get("uuid") == EP_2, timeout=20)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertIn(EP_1, self.fake["upnext"])
        return len(self.pushes_of(EP_1))

    def test_the_resume_checks_switch_never_replays_a_half_told_end(self):
        before = self.end_ep1_with_its_removal_failing()
        run_bridge("pause")
        # The phone finishes EP_2 and takes it off Up Next: EP_1 (played here,
        # its removal pending) is on top. That's not the phone moving on to it.
        self.fake["status"][EP_2] = bridge.STATUS_PLAYED
        self.fake["progress"][EP_2] = 4
        self.fake["upnext"] = [u for u in self.fake["upnext"] if u != EP_2]
        self.assertEqual(run_bridge("toggle").get("code"), "finished_elsewhere")
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_next_never_replays_a_half_told_end(self):
        before = self.end_ep1_with_its_removal_failing()
        run_bridge("pause")
        self.assertEqual(run_bridge("next").get("code"), "nothing_queued")
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_autoplay_and_play_at_the_end_never_replay_a_half_told_end(self):
        before = self.end_ep1_with_its_removal_failing(failures=1)  # EP_2's own removal works
        self.wait_for(lambda: bridge.load_playback().get("handledEnd") == EP_2
                      or run_bridge("player") and False, timeout=20)
        view = run_bridge("player")["data"]
        self.assertEqual((view["item"] or {}).get("uuid"), EP_2)  # nothing followed it
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        # Something new queued since (on the phone): Play at the end starts it,
        # past the half-told one still on top.
        self.fake["upnext"].append(EP_3)
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_3)
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_play_with_nothing_loaded_never_replays_a_half_told_end(self):
        # As above, then the player closed (Stop, the idle unload): Play picks
        # from Up Next past the half-told episode, not just past the last one.
        before = self.end_ep1_with_its_removal_failing(failures=1000)
        self.wait_for(lambda: bridge.load_playback().get("handledEnd") == EP_2
                      or run_bridge("player") and False, timeout=20)
        run_bridge("stop")
        self.fake["upnext"].append(EP_3)
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_3)
        self.assertEqual(self.pushes_of(EP_1)[before:], [])

    # A feed that keeps only its newest episodes drops an older one, and
    # Pocket Casts forgets it: its record comes back empty, and every Play
    # said "Pocket Casts didn't answer", for good (strict review 14).

    def test_play_after_the_last_episode_left_its_feed_moves_on(self):
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        run_bridge("stop")
        self.fake["shows"][PODCAST_A]["episodes"] = [EP_2]  # the feed moved on
        self.fake["episodeReply"] = {EP_1: (404, b'{"errorMessage": "not found"}')}
        before = len(self.pushes_of(EP_1))
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_2)
        self.assertEqual(self.pushes_of(EP_1)[before:], [])

    def test_next_skips_an_episode_that_left_its_feed(self):
        self.fake["upnext"] = [EP_3, EP_1, EP_2]
        self.login()
        run_bridge("play", EP_3, "--podcast", PODCAST_B)
        self.fake["shows"][PODCAST_A]["episodes"] = [EP_2]
        self.fake["episodeReply"] = {EP_1: (404, b'{"errorMessage": "not found"}')}
        self.assertEqual(run_bridge("next")["data"]["item"]["uuid"], EP_2)

    def test_an_empty_lookup_is_still_no_answer_while_the_feed_has_it_or_wont_load(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        run_bridge("stop")
        self.fake["episodeReply"] = {EP_1: (404, b'{"errorMessage": "not found"}')}
        self.assertEqual(run_bridge("toggle").get("code"), "no_record")  # still in the feed
        self.fake["shows"][PODCAST_A]["episodes"] = [EP_2]
        with mock.patch.object(bridge, "fetch_show", side_effect=bridge.ApiError("network", "down")):
            self.assertEqual(run_bridge("toggle").get("code"), "no_record")  # the list didn't load
        self.fake["shows"][PODCAST_A]["episodes"] = []
        self.assertEqual(run_bridge("toggle").get("code"), "no_record")  # an empty list proves nothing

    def test_playing_a_half_told_end_again_drops_its_retry(self):
        # Strict review 13 (R32): you chose it again from a list, and that
        # play's own push failed: a later retry took it off Up Next under you.
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.fake["fail"] = {"/up_next/remove": 1}
        self.wait_for(lambda: bridge.load_playback().get("handledEnd") == EP_1
                      or run_bridge("player", "--no-autoplay") and False)
        self.assertEqual([p["uuid"] for p in bridge.load_playback()["pendingFinish"]], [EP_1])
        self.fake["fail"] = {"/sync/update_episode": 1}
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A, "--from-start")["ok"])
        state = bridge.load_playback()
        for p in state.get("pendingFinish") or []:
            p["tried"] -= 60  # a minute on
        bridge.save_playback(state)
        run_bridge("player", "--no-autoplay")
        self.assertIn(EP_1, self.fake["upnext"])
        self.assertEqual(bridge.load_playback().get("pendingFinish"), [])

    def finished_with_a_retry_left(self, **fails):
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        for kind, paths in fails.items():
            self.fake[kind] = dict(paths)
        self.wait_for(lambda: bridge.load_playback().get("handledEnd") == EP_1
                      or run_bridge("player", "--no-autoplay") and False)
        self.assertEqual([p["uuid"] for p in bridge.load_playback()["pendingFinish"]], [EP_1])

    def retry_now(self):
        state = bridge.load_playback()
        for p in state["pendingFinish"]:
            p["tried"] -= 60
        bridge.save_playback(state)
        run_bridge("player", "--no-autoplay")

    def test_a_played_mark_whose_reply_was_lost_is_finished_by_the_retry(self):
        # Strict review 13 (R33): the mark went through, its reply never came
        # back, and the removal failed. The retry finds it played and takes it
        # off Up Next (it isn't someone else carrying on).
        self.finished_with_a_retry_left(lostReply={"/sync/update_episode": 1}, fail={"/up_next/remove": 1})
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.retry_now()
        self.assertNotIn(EP_1, self.fake["upnext"])
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])

    def test_a_retry_with_an_empty_lookup_waits(self):
        # Strict review 13 (R16): no answer about the record isn't "where this
        # machine left it": nothing is marked until Pocket Casts answers.
        self.finished_with_a_retry_left(fail={"/sync/update_episode": 1})
        self.fake["episodeReply"] = {EP_1: (404, b'{"errorMessage": "not found"}')}
        self.retry_now()
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual([p["uuid"] for p in bridge.load_playback()["pendingFinish"]], [EP_1])
        self.fake["episodeReply"] = None
        self.retry_now()
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_a_removal_left_to_retry_waits_if_the_phone_started_it_again(self):
        # Strict review 13 (L5): only the removal was left; the phone started
        # the episode again meanwhile. It isn't taken off Up Next under it.
        self.finished_with_a_retry_left(fail={"/up_next/remove": 1})
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.fake["progress"][EP_1] = 1
        self.retry_now()
        self.assertIn(EP_1, self.fake["upnext"])
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])

    def test_a_malformed_playback_file_doesnt_jam_stop_or_play(self):
        # Strict review 13 (L4): a string where a time belongs raised in every
        # command that read the file; Stop couldn't stop.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        state = bridge.load_state("playback.json")
        state.update(lastSyncAt="soon", lastSyncPos=[1], pendingFinish=[5, {"uuid": 3}, {"uuid": EP_2, "at": "x"}],
                     unsentPush={"uuid": EP_1, "position": "far", "at": 1}, stream="big")
        bridge.save_state("playback.json", state)
        self.assertTrue(run_bridge("stop")["ok"])
        self.assertFalse(self.mpv_running())
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assertTrue(run_bridge("player")["ok"])

    def test_an_empty_lookup_is_no_answer_when_your_shows_wont_load(self):
        # Strict review 13 (R1): with the list of shows you follow failing (and
        # its ten-minute copy gone), a followed show read as unfollowed, and
        # an empty lookup started it from the public list at 0.
        self.login()
        bridge.drop_state("podcasts-cache.json")
        self.fake["progress"][EP_1] = 30
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.fake["notListed"] = self.fake["noSync"] = {EP_1}  # Pocket Casts lists its place nowhere else
        self.fake["fail"] = {"/user/podcast/list": 1000}
        self.fake["episodeReply"] = {EP_1: (404, b'{"errorMessage": "not found"}')}
        self.assertEqual(run_bridge("play", EP_1, "--podcast", PODCAST_A).get("code"), "no_record")
        self.assertEqual(self.fake["progress"][EP_1], 30)

    def test_an_empty_lookup_is_no_answer_when_your_shows_come_back_empty(self):
        # Strict review 22 (M1): the list loads, but empty (an odd reply),
        # its ten-minute copy old: a followed show read as unfollowed, and an
        # empty lookup started it at 0 over the phone's 30.
        self.login()
        self.assertTrue(run_bridge("podcasts")["ok"])  # a list that loaded, kept
        cached = bridge.load_state("podcasts-cache.json")
        cached["at"] -= 3600
        bridge.save_state("podcasts-cache.json", cached)
        self.fake["showsEmpty"] = True
        self.fake["progress"][EP_1] = 30
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.fake["notListed"] = self.fake["noSync"] = {EP_1}
        self.fake["episodeReply"] = {EP_1: (404, b'{"errorMessage": "not found"}'),
                                     EP_2: (404, b'{"errorMessage": "not found"}')}
        self.assertEqual(run_bridge("play", EP_1, "--podcast", PODCAST_A).get("code"), "no_record")
        self.assertEqual(self.fake["progress"][EP_1], 30)
        # Never listed (someone who follows no show): an episode nobody
        # played still plays, from the show's list, as before.
        bridge.drop_state("podcasts-cache.json")
        self.assertTrue(run_bridge("play", EP_2, "--podcast", PODCAST_A)["ok"])

    def test_a_call_that_spans_a_suspend_sends_nothing(self):
        # Strict review 12 (M4): a push decided before a suspend and sent after
        # it landed the pre-sleep place over the phone's newer one.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 1)
        before = len(self.pushes_of(EP_1))
        with mock.patch.object(bridge, "sleep_offset", lambda: bridge._SLEEP_BASE + 600):
            result = run_bridge("pause")
        self.assertEqual(len(self.pushes_of(EP_1)), before)
        self.assertNotIn("unsentPush", bridge.load_playback())  # from before the sleep: nothing to keep
        with bridge.Mpv.connect() as player:
            self.assertIs(player.get("pause"), True)  # paused all the same
        # A suspend during the connection itself (the TLS handshake, say):
        # connected, nothing is sent.
        real_connect = bridge.http_client.HTTPConnection.connect
        offset = [bridge._SLEEP_BASE]
        def connect_then_sleep(conn):
            real_connect(conn)
            offset[0] = bridge._SLEEP_BASE + 600
        with mock.patch.object(bridge.http_client.HTTPConnection, "connect", connect_then_sleep), \
                mock.patch.object(bridge, "sleep_offset", lambda: offset[0]):
            with self.assertRaises(bridge.ApiError):
                bridge.push_position({"uuid": EP_1, "podcast": PODCAST_A}, 3)
        self.assertEqual(len(self.pushes_of(EP_1)), before)
        # Pocket Casts itself is https: the same check there.
        self.assertTrue(any(isinstance(h, bridge.SleepAwareHTTPSHandler) for h in bridge.build_opener().handlers))

    def test_an_answer_read_across_a_suspend_isnt_applied(self):
        # Asked before the sleep, answered after: from before it, so the
        # resume stays unconfirmed (and pushes nothing) until a fresh answer.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 1)
        run_bridge("pause")
        real = bridge.user_episode
        offset = [bridge._SLEEP_BASE]
        def answered_after_a_sleep(uuid):
            record = real(uuid)
            offset[0] = bridge._SLEEP_BASE + 600
            return record
        with mock.patch.object(bridge, "user_episode", answered_after_a_sleep), \
                mock.patch.object(bridge, "sleep_offset", lambda: offset[0]):
            run_bridge("toggle")
        self.assertTrue(bridge.load_playback().get("unconfirmed"))
        self.assertIs(self.mpv_paused(), True)  # pressed as the lid closed: nothing plays behind the lock screen

    def test_play_again_pressed_as_the_lid_closes_stays_paused(self):
        # Play at an end plays it again, unless the call slept: then nothing
        # plays on behind the lock screen.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: bridge.load_playback().get("handledEnd") == EP_1
                      or run_bridge("player", "--no-autoplay") and False)
        self.wait_for(lambda: self.mpv_paused() is True)  # mpv pauses itself at the end (keep-open)
        with mock.patch.object(bridge, "sleep_offset", lambda: bridge._SLEEP_BASE + 600):
            run_bridge("toggle")
        self.assertIs(self.mpv_paused(), True)
        # The sleep after Pocket Casts answered that it's still played, just
        # before it plays again: still paused.
        offset = [bridge._SLEEP_BASE]

        def still_played_then_slept(uuid):
            offset[0] = bridge._SLEEP_BASE + 600
            return False
        with mock.patch.object(bridge, "reopened_elsewhere", still_played_then_slept), \
                mock.patch.object(bridge, "sleep_offset", lambda: offset[0]):
            run_bridge("toggle")
        self.assertIs(self.mpv_paused(), True)

    def test_status_tells_the_service_which_version_the_files_are(self):
        self.login()
        manifest = json.load(open(os.path.join(os.path.dirname(str(BRIDGE)), "..", "manifest.json")))
        self.assertEqual(run_bridge("status")["data"]["version"], manifest["version"])

    def test_the_loaded_episode_isnt_marked_or_moved(self):
        # Strict review 12 (L4): only the panel refused it.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertEqual(run_bridge("mark", "played", EP_1, "--podcast", PODCAST_A).get("code"), "loaded")
        self.assertEqual(run_bridge("queue", "remove", EP_1).get("code"), "loaded")
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_the_sleep_guard_sets_ask_first_itself(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        self.assertTrue(bridge.pause_for_sleep())
        self.assertIs(bridge.load_playback().get("checkServer"), True)  # before any poll sees the pause

    def test_toggle_with_no_player_resumes_the_last_episode(self):
        self.login()
        self.fake["progress"][EP_2] = 2
        self.fake["upnext"] = [EP_2]
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_2)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] >= 2)

    def test_speed_and_volume_persist(self):
        self.login()
        self.assertEqual(run_bridge("speed", "cycle")["data"]["speed"], 1.1)
        self.assertEqual(run_bridge("speed", "1.5")["data"]["speed"], 1.5)
        self.assertEqual(run_bridge("speed", "cycle")["data"]["speed"], 1.7)
        self.assertEqual(run_bridge("volume", "40")["data"]["volume"], 40)
        prefs = bridge.load_prefs()
        self.assertEqual((prefs["speed"], prefs["volume"]), (1.7, 40))

    def test_unplayable_audio_is_reported(self):
        self.login()
        self.fake["episodes"][EP_1]["url"] = self.base + "/missing.mp3"
        result = run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "playback_failed")

    def test_socket_and_runtime_dir_are_private(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        runtime = os.path.join(os.environ["XDG_RUNTIME_DIR"], "omarchy-legato")
        self.assertEqual(mode_of(runtime), 0o700)
        self.assertTrue(stat.S_ISSOCK(os.lstat(os.path.join(runtime, "mpv.sock")).st_mode))

    def test_status_names_the_socket_the_panel_listens_on(self):
        socket_path = run_bridge("status")["data"]["socket"]
        runtime = os.path.join(os.environ["XDG_RUNTIME_DIR"], "omarchy-legato")
        self.assertEqual(socket_path, os.path.join(runtime, "mpv.sock"))
        self.assertEqual(mode_of(runtime), 0o700)

    def test_idle_unload_never_stops_a_playing_episode(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        view = run_bridge("stop", "--if-paused")["data"]
        self.assertTrue(view["playing"])
        self.assertTrue(self.mpv_running())
        run_bridge("pause")
        self.assertFalse(run_bridge("stop", "--if-paused")["data"]["active"])
        self.assertFalse(self.mpv_running())

    def test_audio_that_never_loads_is_reported_and_the_player_closed(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        state = bridge.load_playback()
        state["checkServer"] = True  # an idle player must not resume or switch either
        bridge.save_playback(state)
        before = len(self.fake["log"])
        # The episode's server stops answering: mpv gives up on the stream
        # and goes idle, still listing it.
        with bridge.Mpv.connect() as player:
            player.command("loadfile", "http://127.0.0.1:1/gone.mp3", "replace")
        view = self.wait_for(lambda: (lambda v: v if v.get("loadFailed") else None)(run_bridge("player")["data"]))
        self.assertFalse(view["active"])
        self.assertFalse(self.mpv_running())
        self.assertEqual(self.fake["log"][before:], [])  # nothing pushed, queued or played
        # The next poll is quiet: the failure is reported once.
        self.assertFalse(run_bridge("player")["data"]["loadFailed"])

    def test_audio_from_a_host_that_hangs_is_reported_and_the_player_closed(self):
        # The host accepts the connection and then sends nothing (a listening
        # socket nobody accepts on: the kernel completes the handshake).
        # mpv's network timeout is cut from 30 s to 1 s on this player so the
        # test doesn't wait half a minute.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        silent = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(silent.close)
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        before = len(self.fake["log"])
        with bridge.Mpv.connect() as player:
            player.command("set_property", "network-timeout", 1)
            player.command("loadfile", "http://127.0.0.1:%d/hangs.mp3" % silent.getsockname()[1], "replace")
        view = self.wait_for(lambda: (lambda v: v if v.get("loadFailed") else None)(run_bridge("player")["data"]), timeout=15)
        self.assertFalse(view["active"])
        self.assertFalse(self.mpv_running())
        self.assertEqual(self.fake["log"][before:], [])  # nothing pushed, queued or played

    def test_before_sleep_a_playing_episode_is_paused_and_saved(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        before = len(self.writes("/sync/update_episode"))
        self.assertTrue(bridge.pause_for_sleep())
        # Everything it sends is quick, and it never refreshes the sign-in.
        self.assertEqual(bridge.HTTP_TIMEOUT, bridge.SLEEP_PUSH_TIMEOUT)
        self.assertFalse(bridge.REFRESH_ALLOWED)
        self.assertFalse(run_bridge("player")["data"]["playing"])
        self.assertEqual(len(self.writes("/sync/update_episode")), before + 1)
        self.assertTrue(bridge.load_playback()["checkServer"])  # the next resume asks first
        # Already paused: nothing to do, nothing sent.
        self.assertFalse(bridge.pause_for_sleep())
        self.assertEqual(len(self.writes("/sync/update_episode")), before + 1)

    def test_a_new_ffmpeg_is_checked_when_a_player_starts(self):
        calls = []
        real = bridge.start_watch_check

        def record(version):
            calls.append(version)
            bridge.save_state(bridge.WATCH_CHECK, {"ffmpeg": version, "ok": True, "at": int(time.time())})
        with mock.patch.object(bridge, "start_watch_check", record):
            self.login()
            self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
            run_bridge("stop")
            self.assertTrue(run_bridge("play", EP_2, "--podcast", PODCAST_A)["ok"])  # a second player: checked already
        self.assertEqual(len(calls), 1)
        with bridge.Mpv.connect() as player:
            self.assertEqual(calls[0], bridge.player_versions(player))
            self.assertIn(player.get("ffmpeg-version"), calls[0])

    def test_a_drag_back_after_the_end_isnt_pushed_as_in_progress(self):
        # Strict review 8: only Play reopens an episode that ended here.
        for episode in self.fake["episodes"].values():
            episode["duration"] = self.AUDIO_SECONDS
        self.fake["progress"][EP_1] = 1  # 3 s to play: under 2 s after the start would prove nothing (end_unproven)
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: run_bridge("player", "--no-autoplay")["data"].get("ended"), timeout=15)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        time.sleep(1)  # keep-open pauses at the end
        run_bridge("seek", "--episode", EP_1, "2.5")  # somewhere it was never pushed from
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_before_sleep_it_pauses_even_while_a_poll_holds_the_lock(self):
        # Strict review 6: a poll pushing on a slow link holds the state lock
        # for many seconds; the guard pauses first, then pushes if it can.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        held = bridge.StateLock()
        held.__enter__()
        try:
            started = time.monotonic()
            self.assertTrue(bridge.pause_for_sleep())
            self.assertLess(time.monotonic() - started, 4)
            with bridge.Mpv.connect() as player:
                self.assertIs(player.get("pause"), True)
            # And it leaves its mark: the call holding the lock, if it loads
            # an episode now, loads it paused (strict review 18, L3).
            self.assertTrue(bridge.sleeping_soon())
        finally:
            held.__exit__(None, None, None)

    def test_before_sleep_an_expired_sign_in_is_never_refreshed(self):
        # A refresh cut short by the guard's 4 s limit after Pocket Casts
        # rotated the refresh token would sign you out: no refresh, no push,
        # and the next resume asks first.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        auth = bridge.load_auth()
        auth["expires_at"] = time.time() - 10
        bridge.save_auth(auth)
        bridge._AUTH = None
        pushes, refreshes = len(self.writes("/sync/update_episode")), len(self.writes("/user/token"))
        self.assertTrue(bridge.pause_for_sleep())
        self.assertEqual(len(self.writes("/user/token")), refreshes)
        self.assertEqual(len(self.writes("/sync/update_episode")), pushes)
        self.assertFalse(run_bridge("player")["data"]["playing"])
        self.assertTrue(bridge.load_playback()["checkServer"])
        self.assertEqual(bridge.load_auth().get("refresh_token"), auth.get("refresh_token"))

    def test_a_hung_player_is_ended_and_replaced(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.5)
        with bridge.Mpv.connect() as player:
            pid, uid = player.peer_pid()
        self.assertEqual(uid, os.geteuid())
        os.kill(pid, signal.SIGSTOP)  # frozen: it no longer answers
        self.addCleanup(lambda: os.path.exists("/proc/%d" % pid) and os.kill(pid, signal.SIGKILL))
        started = time.monotonic()
        view = run_bridge("player")["data"]
        self.assertTrue(view["playerHung"])
        self.assertLess(time.monotonic() - started, 8)
        self.wait_for(lambda: not os.path.exists("/proc/%d" % pid) or open("/proc/%d/stat" % pid).read().split()[2] == "Z")
        self.assertFalse(self.mpv_running())
        # And the next play starts a fresh player.
        self.assertTrue(run_bridge("toggle")["ok"])
        self.wait_for(lambda: run_bridge("player")["data"]["playing"])

    def test_a_hung_socket_that_is_not_mpv_is_never_signalled(self):
        path = bridge.socket_path(create=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        self.addCleanup(server.close)
        player = bridge.Mpv.connect()
        self.assertIsNotNone(player)
        self.assertFalse(player.responsive(timeout=0.5))
        self.assertFalse(bridge.end_hung_player(player))  # this test's own process: left alone
        self.assertTrue(os.path.exists(path))

    def expire_tokens(self):
        auth = bridge.load_auth()
        auth["expires_at"] = time.time() - 10
        bridge.save_auth(auth)

    def test_the_deadline_never_lands_between_a_refresh_and_its_write(self):
        # The call's deadline (SIGALRM) arriving just after Pocket Casts
        # answered a refresh must not lose the new tokens (a rotated refresh
        # token would sign you out): it waits until they're stored.
        self.login()
        self.expire_tokens()
        bridge._AUTH = None
        real_post = bridge.post_json

        def post(path, *args, **kwargs):
            result = real_post(path, *args, **kwargs)
            if path == "/user/token":
                os.kill(os.getpid(), signal.SIGALRM)
            return result
        previous = signal.signal(signal.SIGALRM, bridge._deadline_passed)
        try:
            with mock.patch.object(bridge, "post_json", post), self.assertRaises(bridge.DeadlinePassed):
                bridge.access_token(bridge.load_auth())
        finally:
            signal.signal(signal.SIGALRM, previous)
        self.assertGreater(float(bridge.load_auth()["expires_at"]), time.time() + 60)

    def test_a_sign_out_during_a_token_refresh_stays_signed_out(self):
        # Marketplace review (#15655): a list call refreshing an expired token
        # while you sign out used to save the old account's tokens again.
        self.login()
        self.expire_tokens()
        real_post = bridge.post_json
        logout = {}

        def post_json(path, body, token="", timeout=None):
            if path == "/user/token" and not logout:
                # Sign out from another process while the refresh is in flight.
                logout["proc"] = subprocess.Popen([sys.executable, "-I", "-B", str(BRIDGE), "logout"],
                                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                try:
                    logout["proc"].wait(timeout=1.5)  # done at once, unless it waits for this refresh
                except subprocess.TimeoutExpired:
                    pass
            return real_post(path, body, token, timeout)

        with mock.patch.object(bridge, "post_json", post_json):
            run_bridge("up-next")
        out, _ = logout["proc"].communicate(timeout=20)
        self.assertTrue(json.loads(out)["ok"])
        self.assertEqual(bridge.load_auth(), {})  # the sign-out won: no tokens written back
        self.assertFalse(run_bridge("status")["data"]["authenticated"])

    def test_an_expired_flag_is_never_written_over_a_sign_out(self):
        self.login()
        bridge._AUTH = bridge.load_auth()
        bridge._AUTH["expires_at"] = time.time() - 10
        bridge.clear_auth()  # signed out in another process meanwhile
        with mock.patch.object(bridge, "post_json", lambda path, body, token="", timeout=None: (401, {})):
            with self.assertRaises(bridge.ApiError):
                bridge.api("/up_next/list", {})
        self.assertEqual(bridge.load_auth(), {})

    def test_two_calls_refreshing_at_once_share_one_refresh(self):
        self.login()
        stale = bridge.load_auth()
        stale["expires_at"] = time.time() - 10  # this call's copy: expired
        fresh = dict(stale, access_token="t2", expires_at=time.time() + 3600)
        bridge.save_auth(fresh)  # another call refreshed it meanwhile
        bridge._AUTH = stale
        before = len(self.writes("/user/token"))
        bridge.api("/up_next/list", {"version": 2})
        self.assertEqual(len(self.writes("/user/token")), before)  # no second refresh
        self.assertEqual(bridge._AUTH["access_token"], "t2")

    def test_a_sign_out_that_cant_delete_the_tokens_says_so(self):
        self.login()
        with mock.patch.object(bridge, "clear_auth", lambda: None):
            result = run_bridge("logout")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "logout")

    def test_mpv_fetches_through_the_feed_proxy(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.3)  # it plays, through it
        with bridge.Mpv.connect() as player:
            self.assertTrue(bridge.proxy_alive(player.get("http-proxy")))
        self.assertTrue(any(line.startswith("GET http://127.0.0.1:") and "/audio/" + EP_1 in line
                            for line in self.proxied), self.proxied)

    def test_mpv_checks_tls_certificates(self):
        # Review finding: mpv's --tls-verify is off by default.
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        with bridge.Mpv.connect() as player:
            pid, _ = player.peer_pid()
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            self.assertIn(b"--tls-verify=yes", fh.read().split(b"\0"))

    def test_logout_stops_the_player_and_forgets_tokens(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertTrue(run_bridge("logout")["ok"])
        self.wait_for(lambda: not self.mpv_running())
        self.assertEqual(bridge.load_auth(), {})


@NEEDS_PLAYER
class ToldEnds(PlayerTestCase):
    """Strict review 21 (F3): a landed "played" mark makes a record."""

    def test_a_told_end_of_an_unfollowed_show_isnt_replayed_from_0_after_an_empty_lookup(self):
        # Played from the show's public list; its load push failed (no record
        # seen), its end's mark landed. Then one empty lookup: Play played it
        # from 0 and pushed it in progress over "played".
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["upnext"] = [EP_3, EP_1]
        self.login()
        self.fake["fail"] = {"/sync/update_episode": 1}  # the load's push
        bridge.save_state("settings.json", {"autoplay": False})
        self.assertTrue(run_bridge("play", EP_3, "--podcast", PODCAST_B)["ok"])
        self.wait_for(lambda: self.fake["status"].get(EP_3) == bridge.STATUS_PLAYED
                      or run_bridge("player", "--no-autoplay")["data"].get("ended"), timeout=20)
        run_bridge("player", "--no-autoplay")
        state = bridge.load_playback()
        self.assertEqual(self.fake["status"].get(EP_3), bridge.STATUS_PLAYED)
        self.assertEqual(state.get("handledEnd"), EP_3)
        self.assertTrue(state.get("recordSeen"))
        run_bridge("stop")
        before = len(self.pushes_of(EP_3))
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        result = run_bridge("toggle")
        self.assertNotEqual(((result.get("data") or {}).get("item") or {}).get("uuid"), EP_3)
        self.assertEqual(self.fake["status"].get(EP_3), bridge.STATUS_PLAYED)
        self.assertEqual(len(self.pushes_of(EP_3)), before)


    def test_an_end_whose_mark_sent_nothing_isnt_told(self):
        # Strict review 22 (L1): with no show id, push_position sends
        # nothing, but the end's mark was recorded as told.
        self.login()
        bridge.save_state("settings.json", {"autoplay": False})
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        state = bridge.load_playback()
        state["episode"]["podcast"] = ""
        bridge.save_playback(state)
        self.wait_for(lambda: run_bridge("player", "--no-autoplay")["data"].get("ended"), timeout=20)
        run_bridge("player", "--no-autoplay")
        pending = bridge.load_playback().get("pendingFinish") or []
        self.assertTrue(any(p.get("uuid") == EP_1 and not p.get("played") for p in pending), pending)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)


class ResumeAsksPocketCastsFirst(PlayerTestCase):
    """You pause here, listen on in another device (simulated by writing to
    the fake server, as that device's app would), then play here again. The
    episode, position and Up Next another device left behind must win, and
    this machine must never push its old position over them."""

    AUDIO_SECONDS = 120

    def setUp(self):
        super().setUp()
        for episode in self.fake["episodes"].values():
            episode["duration"] = self.AUDIO_SECONDS

    def other_device(self, uuid, position, status=bridge.STATUS_IN_PROGRESS):
        self.fake["progress"][uuid] = position
        self.fake["status"][uuid] = status

    def age_last_push(self, seconds):
        """Back here `seconds` later: the last push, and any push that failed
        since, are that much older."""
        state = bridge.load_playback()
        state["lastSyncAt"] = float(state.get("lastSyncAt") or time.time()) - seconds
        if isinstance(state.get("unsentPush"), dict):
            state["unsentPush"]["at"] -= seconds
        bridge.save_playback(state)

    def pushes(self, uuid):
        return [body for body in self.writes("/sync/update_episode") if body["uuid"] == uuid]

    def position(self):
        return run_bridge("player")["data"]["position"]

    def play_then_pause(self, uuid=EP_1, podcast=PODCAST_A):
        self.login()
        self.assertTrue(run_bridge("play", uuid, "--podcast", podcast)["ok"])
        self.wait_for(lambda: self.position() > 0.5)
        self.assertFalse(run_bridge("pause")["data"]["playing"])

    def mpv_set_pause(self, paused):
        """What mpv-mpris does for a media key or playerctl: straight to mpv."""
        with bridge.Mpv.connect() as player:
            player.set("pause", paused)

    def resume_with_reply(self, reply):
        self.play_then_pause()
        self.other_device(EP_1, 25)  # the phone carried on
        self.fake["episodeReply"] = reply  # and Pocket Casts answers the lookup oddly
        run_bridge("toggle")
        time.sleep(1)
        run_bridge("pause")
        self.assertGreaterEqual(self.fake["progress"][EP_1], 25)

    def test_a_404_for_a_known_episode_isnt_an_answer(self):
        # Strict review 8: Pocket Casts knew this episode a moment ago; an
        # empty lookup now confirmed our own stale place.
        self.resume_with_reply((404, b'{"errorMessage": "not found"}'))

    def test_an_empty_answer_for_a_known_episode_isnt_one(self):
        self.resume_with_reply((200, b""))

    def test_a_redirect_for_a_known_episode_isnt_an_answer(self):
        self.resume_with_reply((302, b""))

    def test_play_after_the_player_closed_never_restarts_from_the_public_list(self):
        self.play_then_pause()
        run_bridge("stop")
        self.other_device(EP_1, 25)
        self.fake["episodeReply"] = (404, b'{"errorMessage": "not found"}')
        self.assertFalse(run_bridge("toggle")["ok"])  # "Pocket Casts didn't answer: try again"
        self.assertGreaterEqual(self.fake["progress"][EP_1], 25)

    def test_play_from_a_list_with_an_empty_lookup_pushes_nothing(self):
        # Strict review 9: a show you follow has a record of every episode; an
        # empty lookup started it from the public list at 0, pushed.
        self.other_device(EP_2, 25)
        self.login()
        self.fake["episodeReply"] = {EP_2: (404, b'{"errorMessage": "not found"}')}
        result = run_bridge("play", EP_2, "--podcast", PODCAST_A)
        self.assertFalse(result["ok"])
        self.assertEqual(self.fake["progress"][EP_2], 25)
        self.assertEqual(self.pushes_of(EP_2), [])

    def test_a_followed_shows_episode_listed_nowhere_isnt_started_from_its_list(self):
        # "A show you follow" alone: the phone at 25, Up Next's places and In
        # Progress leave it out, nothing known here; an empty lookup must
        # refuse, not start it from the public list at 0 and push that.
        self.other_device(EP_2, 25)
        self.fake["notListed"] = self.fake["noSync"] = {EP_2}
        self.login()
        self.fake["episodeReply"] = {EP_2: (404, b'{"errorMessage": "not found"}')}
        self.assertEqual(run_bridge("play", EP_2, "--podcast", PODCAST_A).get("code"), "no_record")
        self.assertEqual((self.fake["progress"][EP_2], self.pushes_of(EP_2)), (25, []))

    def test_following_the_phone_with_an_empty_lookup_pushes_nothing(self):
        # The phone moved on to EP_2; its lookup comes back empty.
        self.play_then_pause()
        self.other_device(EP_1, 30, bridge.STATUS_PLAYED)
        self.fake["upnext"] = [EP_2]
        self.other_device(EP_2, 20)
        self.fake["episodeReply"] = {EP_2: (200, b"")}
        run_bridge("resume")
        self.assertEqual(self.fake["progress"][EP_2], 20)
        self.assertEqual(self.pushes_of(EP_2), [])

    def test_an_autoplayed_episode_with_an_empty_lookup_never_starts_at_0(self):
        # Started by Next (no record read for it), closed; the phone listened
        # to 20; Play's lookup comes back empty.
        self.play_then_pause()
        run_bridge("next")
        self.wait_for(lambda: (run_bridge("player")["data"]["item"] or {}).get("uuid") == EP_2)
        run_bridge("pause")
        run_bridge("stop")
        self.other_device(EP_2, 20)
        before = len(self.pushes_of(EP_2))
        self.fake["episodeReply"] = {EP_2: (302, b"")}
        self.assertFalse(run_bridge("toggle")["ok"])
        self.assertEqual(self.fake["progress"][EP_2], 20)
        self.assertEqual(len(self.pushes_of(EP_2)), before)

    def test_a_404_for_a_known_episode_of_a_show_you_dont_follow_isnt_an_answer(self):
        # recordSeen alone: a show you don't follow has no record of every
        # episode, but this one had one (you played it), so an empty lookup
        # is no answer either (strict review 8; round 9's mutation run).
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["recorded"] = {EP_3}
        self.fake["notListed"] = self.fake["noSync"] = {EP_3}  # recordSeen alone decides
        self.play_then_pause(EP_3, PODCAST_B)
        self.other_device(EP_3, 25)
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        run_bridge("toggle")
        time.sleep(1)
        run_bridge("pause")
        self.assertGreaterEqual(self.fake["progress"][EP_3], 25)

    def test_a_record_the_resume_check_saw_counts_too(self):
        # Started from a show's public list (no record yet), then played on
        # another device: the resume check sees its record from then on, so a
        # later empty lookup is no answer (round 9's reviewer: mutB).
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["notListed"] = self.fake["noSync"] = {EP_3}  # not on In Progress (the list is capped)
        self.play_then_pause(EP_3, PODCAST_B)
        self.other_device(EP_3, 20)
        run_bridge("toggle")
        self.wait_for(lambda: self.position() >= 20, timeout=20)
        run_bridge("pause")
        self.other_device(EP_3, 40)
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        run_bridge("toggle")
        time.sleep(1)
        run_bridge("pause")
        self.assertEqual(self.fake["progress"][EP_3], 40)

    def test_play_after_the_player_closed_never_restarts_a_known_unfollowed_episode_from_0(self):
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["recorded"] = {EP_3}
        self.fake["notListed"] = self.fake["noSync"] = {EP_3}  # recordSeen alone decides
        self.play_then_pause(EP_3, PODCAST_B)
        run_bridge("stop")
        self.other_device(EP_3, 25)
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        before = len(self.pushes_of(EP_3))
        self.assertFalse(run_bridge("toggle")["ok"])  # "Pocket Casts didn't answer: try again"
        self.assertEqual(self.fake["progress"][EP_3], 25)
        self.assertEqual(len(self.pushes_of(EP_3)), before)

    def test_play_from_a_list_never_restarts_a_known_unfollowed_episode_from_0(self):
        # Strict review 21 (F1): the same, but from a list (cmd_play): it
        # took the show's public list and pushed 0 over the phone's 25.
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["notListed"] = self.fake["noSync"] = {EP_3}  # recordSeen alone decides
        self.play_then_pause(EP_3, PODCAST_B)
        self.assertTrue(bridge.load_playback().get("recordSeen"))
        run_bridge("stop")
        self.other_device(EP_3, 25)
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        before = len(self.pushes_of(EP_3))
        result = run_bridge("play", EP_3, "--podcast", PODCAST_B)
        self.assertEqual(result.get("code"), "no_record")
        self.assertEqual(self.fake["progress"][EP_3], 25)
        self.assertEqual(len(self.pushes_of(EP_3)), before)
        self.assertFalse(self.mpv_running())

    def test_a_marked_closed_episode_isnt_replayed_from_0_after_an_empty_lookup(self):
        # Strict review 21 (F3's second door): Mark played on the last
        # episode, closed, makes a record; an empty lookup then is no answer.
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["notListed"] = self.fake["noSync"] = {EP_3}
        self.fake["upnext"] = [EP_3]
        self.login()
        self.fake["fail"] = {"/sync/update_episode": 1}  # the load's push: no record seen
        self.assertTrue(run_bridge("play", EP_3, "--podcast", PODCAST_B)["ok"])
        bridge.Mpv.connect().command("quit")  # the player closed some other way: no push
        self.wait_for(lambda: not self.mpv_running())
        self.assertFalse(bridge.load_playback().get("recordSeen"))
        self.assertTrue(run_bridge("mark", "played", EP_3, "--podcast", PODCAST_B)["ok"])
        self.assertTrue(bridge.load_playback().get("recordSeen"))
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        before = len(self.pushes_of(EP_3))
        self.assertFalse(run_bridge("toggle")["ok"])
        self.assertEqual(self.fake["status"][EP_3], bridge.STATUS_PLAYED)
        self.assertEqual(len(self.pushes_of(EP_3)), before)

    def test_an_episode_of_a_show_you_dont_follow_on_in_progress_never_starts_at_0(self):
        # Strict review 10 (4): a show you don't follow has records for the
        # episodes anyone played; In Progress lists this one, so an empty
        # lookup is no answer: Play refuses rather than start it at 0.
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["recorded"] = {EP_3}
        self.other_device(EP_3, 50)
        self.login()
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        result = run_bridge("play", EP_3, "--podcast", PODCAST_B)
        self.assertEqual(result.get("code"), "no_record", result)
        self.assertEqual(self.fake["progress"][EP_3], 50)
        self.assertEqual(self.pushes_of(EP_3), [])
        self.fake["episodeReply"] = None
        self.fake["status"][EP_3] = bridge.STATUS_UNPLAYED  # listed nowhere now: the lists can't tell
        self.fake["fail"] = {"/user/in_progress": 1}
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        self.assertEqual(run_bridge("play", EP_3, "--podcast", PODCAST_B).get("code"), "no_record")

    def test_the_resume_check_reads_in_progress_for_a_show_you_dont_follow(self):
        # Loaded from the public list (no record then; Legato's own push made
        # one), carried on on the phone; now its lookup is empty, but In
        # Progress lists it: no answer, nothing pushed over the phone's 25.
        self.fake["unfollowed"] = {PODCAST_B}
        # (Its pushes from here fail: a push that lands makes the record seen,
        # strict review 17, and the empty lookup would be no answer for that
        # alone, In Progress never asked.)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.play_then_pause(EP_3, PODCAST_B)
        self.assertFalse(bridge.load_playback().get("recordSeen"))
        self.fake["fail"] = {}
        self.other_device(EP_3, 25)
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        run_bridge("toggle")
        time.sleep(1)
        run_bridge("pause")
        self.assertEqual(self.fake["progress"][EP_3], 25)

    def test_a_resume_seeking_past_this_copys_end_never_marks_it_played(self):
        # Strict review 12 (H1): an ad-stitched episode's copies differ: the
        # phone got past the end of this one; the resume check's seek landed
        # at its end, and the poll marked it played everywhere.
        self.fake["episodes"][EP_1]["duration"] = 130  # listed; this copy runs 120 s
        self.play_then_pause()
        self.other_device(EP_1, 125)
        run_bridge("toggle")
        self.wait_for(lambda: run_bridge("player")["data"].get("streamBroke") or not self.mpv_running()
                      or self.fake["status"].get(EP_1) == bridge.STATUS_PLAYED, timeout=20)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)
        self.assertIn(EP_1, self.fake["upnext"])

    def test_a_media_key_stretch_nobody_asked_about_loses_to_the_phone(self):
        # Strict review 12 (M3): played and paused by media keys while Legato
        # was off; the phone went back meanwhile. Play kept the unchecked
        # place over the phone's and pushed it.
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 5, timeout=30)
        run_bridge("pause")  # pushed at about 5; the next resume asks first
        self.mpv_set_pause(False)  # a media key, no poll
        time.sleep(1.5)
        self.mpv_set_pause(True)
        self.other_device(EP_1, 2)  # the phone went back
        run_bridge("player")  # Legato back: its first poll
        run_bridge("toggle")
        time.sleep(0.5)
        run_bridge("pause")
        self.assertLess(self.fake["progress"][EP_1], 5, [b["position"] for b in self.pushes_of(EP_1)])

    # Places in these tests sit well outside DRIFT_SLACK (3 s) of the last
    # push: a phone "going back" by less is indistinguishable from not moving.

    def test_a_stretch_played_through_a_gap_loses_to_the_phone(self):
        # Strict review 13 (M1, P1): confirmed, then Legato went off (the chip
        # dragged off, the shell down); mpv played on and a media key paused
        # it. The phone went back meanwhile. Play kept the stretch (further
        # on, never pushed) over the phone's place, then pushed it.
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 31, timeout=30)
        time.sleep(4)                # plays on, unwatched
        self.mpv_set_pause(True)     # a media key
        self.age_last_push(200)      # Legato was off for minutes
        self.other_device(EP_1, 10)  # the phone went back
        run_bridge("player")         # Legato back: its first poll
        run_bridge("toggle")
        time.sleep(0.5)
        run_bridge("pause")
        self.assertLess(self.fake["progress"][EP_1], 15, [b["position"] for b in self.pushes_of(EP_1)])

    def test_a_stretch_played_through_a_gap_isnt_pushed_by_stop(self):
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 31, timeout=30)
        time.sleep(4)
        self.mpv_set_pause(True)
        self.age_last_push(200)
        self.other_device(EP_1, 10)
        run_bridge("player")
        run_bridge("stop")
        self.assertEqual(self.fake["progress"][EP_1], 10)
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_1)
        self.assertLess(self.position(), 15)

    def test_a_media_key_stretch_nobody_asked_about_isnt_pushed_by_stop(self):
        # SR132's marking: resumed and paused by media keys within a minute
        # (no gap to go on); the first poll marks the stretch, and Stop sends
        # nothing of it over the phone that went on meanwhile.
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 31, timeout=30)
        run_bridge("pause")          # pushed; the next resume asks first
        self.mpv_set_pause(False)    # a media key, no poll
        time.sleep(2)
        self.mpv_set_pause(True)
        self.other_device(EP_1, 60)
        run_bridge("player")
        self.assertTrue(bridge.load_playback().get("unconfirmed"))
        run_bridge("stop")
        self.assertEqual(self.fake["progress"][EP_1], 60)

    def test_still_playing_after_a_gap_the_phone_going_back_wins(self):
        # Strict review 13 (M1, P1b): a sleep Legato missed (or Legato off)
        # while playing, and mpv plays on. The first poll asks (rule 2), got
        # the phone's place, kept its own (further on, never pushed), and the
        # next poll pushed it.
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 31, timeout=30)
        time.sleep(4)                # plays on, unwatched
        self.age_last_push(200)      # the gap
        self.other_device(EP_1, 10)  # the phone went back
        before = len(self.pushes_of(EP_1))
        self.assertLess(run_bridge("player")["data"]["position"], 15)  # asked: the phone's place wins
        self.age_last_push(31)
        run_bridge("player")         # the next periodic poll
        self.assertLess(self.fake["progress"][EP_1], 15, [b["position"] for b in self.pushes_of(EP_1)[before:]])

    def test_a_failed_push_then_a_gap_keeps_nothing_that_played_since(self):
        # A periodic push failed (the one place worth keeping), then mpv
        # played on through a gap: what played since is no news, and the
        # phone's older place wins over all of it.
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 31, timeout=30)
        self.fake["fail"] = {"/sync/update_episode": 1}
        self.age_last_push(31)
        run_bridge("player")         # its push fails: unsent at about 31
        self.assertTrue(bridge.load_playback().get("unsentPush"))
        time.sleep(7)                # plays on, unwatched
        self.age_last_push(200)
        self.other_device(EP_1, 10)
        self.assertLess(run_bridge("player")["data"]["position"], 15)

    def unsent_then_closed(self, close=("stop",)):
        """Played from 20 to past 26 here, the pause's push failed (and the
        poll its pause brings, and Stop's, failed too), then the player
        closed: Pocket Casts still has 20."""
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 26)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        run_bridge("player")         # the poll mpv's pause event brings
        self.assertFalse(bridge.load_playback().get("unconfirmed"))
        run_bridge(*close)
        self.fake["fail"] = {}
        self.assertFalse(self.mpv_running())
        self.assertEqual(self.fake["progress"][EP_1], 20)

    def test_a_place_whose_push_failed_survives_stop(self):
        # Strict review 14 (F1, high): kept only while the player stayed
        # loaded; Stop, then Play, went back to Pocket Casts' older place.
        self.unsent_then_closed()
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertGreater(view["position"], 25)
        self.assertGreater(self.fake["progress"][EP_1], 25)  # and sent now
        self.assertNotIn("unsentPush", bridge.load_playback())

    def test_a_place_whose_push_failed_survives_the_idle_unload(self):
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 26)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        self.age_last_push(16 * 60)  # 15 minutes paused
        run_bridge("stop", "--if-paused")
        self.fake["fail"] = {}
        self.assertFalse(self.mpv_running())
        self.assertGreater(run_bridge("toggle")["data"]["position"], 25)

    def test_a_place_whose_push_failed_is_kept_for_an_hour_only(self):
        self.unsent_then_closed()
        self.age_last_push(bridge.UNSENT_KEPT + 60)
        self.assertLess(run_bridge("toggle")["data"]["position"], 22)

    def test_an_unsent_place_is_kept_while_nobody_moved_it_whatever_happened_here(self):
        # The pause's push failed; then Play couldn't ask Pocket Casts
        # (unconfirmed), and it was paused and stopped. Pocket Casts' answer at
        # the next Play still holds this machine's last push: nobody else has
        # written since, so the unsent place is still the latest there is.
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 26)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        self.fake["fail"] = {"/up_next/list": 1, "/sync/update_episode": 1000}  # the resume can't ask
        run_bridge("resume")
        run_bridge("pause")
        run_bridge("stop")
        self.fake["fail"] = {}
        self.assertTrue(bridge.load_playback().get("unsentPush"))
        self.assertGreater(run_bridge("toggle")["data"]["position"], 25)

    def test_a_reload_of_an_episode_finished_elsewhere_keeps_nothing(self):
        # Its last confirmed push was its start (no periodic push yet), the
        # pause's push failed, then the phone finished it. Played again from a
        # list, it starts at the top, not at this machine's unsent place.
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 7)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        run_bridge("stop")
        self.fake["fail"] = {}
        self.other_device(EP_1, 0, bridge.STATUS_PLAYED)
        self.assertLess(run_bridge("play", EP_1, "--podcast", PODCAST_A)["data"]["position"], 3)

    def test_a_lookup_that_fails_never_drops_an_unsent_place(self):
        # Strict review 14 (F1's second door): a 503 on the episode's lookup
        # fell through to Up Next, which started it at Pocket Casts' older
        # place. Now: try again, then the unsent place.
        self.unsent_then_closed()
        self.fake["fail"] = {"/user/episode": 1}
        result = run_bridge("toggle")
        self.assertFalse(result["ok"])
        self.assertFalse(self.mpv_running())
        self.assertGreater(run_bridge("toggle")["data"]["position"], 25)

    def test_a_pause_whose_push_failed_is_sent_by_the_poll_it_brings(self):
        # The place it paused at played here, confirmed, a moment ago: the
        # poll mpv's pause event brings sends it (it isn't unasked-for motion).
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 26)
        self.fake["fail"] = {"/sync/update_episode": 1}
        run_bridge("pause")
        self.assertLess(self.fake["progress"][EP_1], 25)
        before = len(self.fake["log"])
        run_bridge("player")
        self.assertGreater(self.fake["progress"][EP_1], 25)
        self.assertNotIn("unsentPush", bridge.load_playback())
        # Only after asking: Pocket Casts still had it where this machine
        # left it (strict review 21, F2).
        paths = [p for p, _ in self.fake["log"][before:]]
        self.assertLess(paths.index("/user/episode"), paths.index("/sync/update_episode"))

    # --- Strict review 21 (F2): a failed pause's place went out blind, over
    # a phone that carried on meanwhile, by anything within the 90 s.
    def failed_pause_then_phone(self):
        """Played from 0 past 6 here; the pause's push failed (Pocket Casts
        has the load's 0); the phone then carried on from 0 to 40."""
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 6, timeout=20)
        self.fake["fail"] = {"/sync/update_episode": 1}
        run_bridge("pause")
        self.assertGreater(bridge.load_playback()["unsentPush"]["position"], 6)
        self.other_device(EP_1, 40)
        return len(self.pushes_of(EP_1))

    def test_stop_never_sends_a_failed_pause_place_over_the_phone(self):
        before = self.failed_pause_then_phone()
        run_bridge("stop")
        self.assertEqual(self.fake["progress"][EP_1], 40)
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_next_never_sends_a_failed_pause_place_over_the_phone(self):
        before = self.failed_pause_then_phone()
        run_bridge("next")
        self.assertEqual(self.fake["progress"][EP_1], 40)
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_playing_another_episode_never_sends_a_failed_pause_place(self):
        before = self.failed_pause_then_phone()
        self.assertTrue(run_bridge("play", EP_2, "--podcast", PODCAST_A)["ok"])
        self.age_unsent_tries()
        run_bridge("player")  # (and the stashed place's retry asks too)
        self.assertEqual(self.fake["progress"][EP_1], 40)
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_pause_again_or_the_poll_never_sends_a_failed_pause_place(self):
        before = self.failed_pause_then_phone()
        run_bridge("pause")
        run_bridge("player")  # an mpv event (the video window, a media widget)
        self.assertEqual(self.fake["progress"][EP_1], 40)
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_a_seek_while_paused_after_a_failed_push_never_goes_over_the_phone(self):
        before = self.failed_pause_then_phone()
        run_bridge("seek", "--relative", "--", "-3")
        self.assertEqual(self.fake["progress"][EP_1], 40)
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_a_push_that_never_went_out_isnt_taken_for_one_that_landed(self):
        # Strict review 21 (L1): an episode without a show id can't be pushed
        # (push_position sends nothing), but four callers recorded a landed
        # push: Pocket Casts' place moved here, and the episode never synced.
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 4, timeout=20)
        state = bridge.load_playback()
        state["episode"]["podcast"] = ""
        bridge.save_playback(state)
        run_bridge("pause")
        self.assertLess(bridge.load_playback()["lastSyncPos"], 1)  # still the load's

    def test_a_redirect_from_the_api_isnt_a_landed_push(self):
        # Strict review 21 (L2): a 3xx passed as success.
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 4, timeout=20)
        self.fake["failStatus"] = {"/sync/update_episode": 302}
        self.fake["fail"] = {"/sync/update_episode": 1}
        run_bridge("pause")
        state = bridge.load_playback()
        self.assertIn("unsentPush", state)
        self.assertLess(state["lastSyncPos"], 1)

    # --- Strict review 22 (H1): another account signing in.
    def sign_in_as(self, email):
        result = run_bridge("login", stdin=json.dumps({"email": email, "password": PASSWORD}))
        self.assertTrue(result["ok"], result)

    def unsent_in_two_episodes(self):
        """EP_1 played here, its place stashed unsent by Next; EP_2 played and
        paused, its place unsent too (every push failing: a session expiring
        does that)."""
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 4, timeout=20)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("next")
        self.wait_for(lambda: (run_bridge("player")["data"].get("item") or {}).get("uuid") == EP_2 and self.position() > 2,
                      timeout=20)
        run_bridge("pause")
        state = bridge.load_playback()
        self.assertTrue(state.get("unsentPlaces") and state.get("unsentPush"), state)
        self.fake["fail"] = {}

    def test_another_account_signing_in_gets_none_of_the_last_ones_places(self):
        # The sign-in page (a session expired) took another account: the
        # next poll and the retries pushed the first account's places into it.
        self.fake["accountUuids"] = {"other@example.com": "u2"}
        self.unsent_in_two_episodes()
        before = len(self.writes("/sync/update_episode"))
        self.sign_in_as("other@example.com")
        self.assertFalse(self.mpv_running())
        self.assertEqual(bridge.load_playback(), {})
        run_bridge("player")
        self.assertEqual(self.writes("/sync/update_episode")[before:], [])

    def test_the_same_account_signing_in_again_keeps_its_places(self):
        self.unsent_in_two_episodes()
        self.assertTrue(run_bridge("podcasts")["ok"])
        self.sign_in_as("me@example.com")
        self.assertTrue(bridge.load_state("podcasts-cache.json").get("items"))  # (its show list kept: round 23, F6)
        self.assertTrue(self.mpv_running())
        state = bridge.load_playback()
        self.assertIn("unsentPush", state)
        self.assertTrue(state.get("unsentPlaces"))

    def test_a_sign_in_cut_off_never_leaves_the_other_accounts_playback(self):
        # Strict review 23 (F3): the new session was stored before the old
        # playback went; a call cut off between (a plugin reload) left the
        # first account's playback under the second's session.
        self.fake["accountUuids"] = {"other@example.com": "u2"}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 3, timeout=20)

        def killed(*args, **kwargs):
            raise SystemExit("killed")  # the process ends here
        with mock.patch.object(bridge, "quit_mpv", killed):
            with self.assertRaises(SystemExit):
                run_bridge("login", stdin=json.dumps({"email": "other@example.com", "password": PASSWORD}))
        # Not signed in as the other account: what's there is still one
        # account's session and its own playback.
        self.assertEqual(bridge.load_auth().get("uuid"), "u")

    # --- Strict review 23 (F1, F2, F4).
    def test_an_episode_left_unsent_isnt_restarted_from_its_public_list(self):
        # A show you don't follow, Pocket Casts at 20, played here to 26+
        # with every push failing, its place stashed by Next; then its lookup
        # comes back empty and In Progress leaves it out: Play from a list
        # started it from the public list at 0, pushed over 20, and dropped
        # the place.
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["recorded"] = {EP_3}
        self.other_device(EP_3, 20)
        self.fake["upnext"] = [EP_3, EP_1]
        self.login()
        self.assertTrue(run_bridge("play", EP_3, "--podcast", PODCAST_B)["ok"])
        self.wait_for(lambda: self.position() > 26, timeout=20)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        self.assertEqual(run_bridge("next")["data"]["item"]["uuid"], EP_1)
        run_bridge("pause")
        self.assertTrue(any(p["uuid"] == EP_3 for p in bridge.load_playback().get("unsentPlaces") or []))
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        self.fake["notListed"] = {EP_3}
        self.fake["fail"] = {}
        before = len(self.pushes_of(EP_3))
        self.assertEqual(run_bridge("play", EP_3, "--podcast", PODCAST_B).get("code"), "no_record")
        self.assertEqual(self.pushes_of(EP_3)[before:], [])
        self.assertEqual(self.fake["progress"][EP_3], 20)
        self.assertTrue(any(p["uuid"] == EP_3 for p in bridge.load_playback().get("unsentPlaces") or []))

    def test_a_last_episode_with_a_place_isnt_restarted_from_its_public_list(self):
        # The last episode came from Up Next's sync data at 20 (no record
        # seen: its lookup was empty all along, every push failing); with
        # its place listed nowhere else, Play with nothing loaded took the
        # public list's 0.
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["syncStatus"] = True
        self.other_device(EP_3, 20)
        self.fake["upnext"] = [EP_1, EP_3]
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertEqual(run_bridge("next")["data"]["item"]["uuid"], EP_3)
        self.wait_for(lambda: self.position() > 22, timeout=20)
        run_bridge("stop")
        state = bridge.load_playback()
        self.assertFalse(state.get("recordSeen"))
        self.fake["fail"] = {}
        self.fake["notListed"] = self.fake["noSync"] = {EP_3}
        before = len(self.pushes_of(EP_3))
        self.assertFalse(run_bridge("toggle")["ok"])
        self.assertEqual(self.pushes_of(EP_3)[before:], [])
        self.assertEqual(self.fake["progress"][EP_3], 20)

    def gone_on_up_next(self):
        g = dict(self.fake["episodes"][EP_2], uuid=GONE, title="Gone")
        g["url"] = self.base + "/audio/%s.mp3" % GONE
        self.fake["episodes"][GONE] = g  # on Up Next, not in its show's list
        self.fake["episodeReply"] = {GONE: (404, b'{"errorMessage": "not found"}')}  # forgotten

    def mpv_get(self, name):
        with bridge.Mpv.connect() as player:
            return player.get(name)

    def test_autoplay_past_an_entry_gone_from_its_feed_keeps_syncing(self):
        # Up Next [EP_1, GONE, EP_2]: EP_1 ends, autoplay skips GONE and
        # played EP_2 taking it for the top; every later resume check read
        # GONE as another device's move, couldn't follow it, said unverified,
        # and nothing of EP_2 was pushed again; after Stop, "Up Next is empty".
        self.fake["media"] = {EP_1: make_audio(4)}
        self.fake["episodes"][EP_1]["duration"] = 4
        self.gone_on_up_next()
        self.fake["upnext"] = [EP_1, GONE, EP_2]
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.mpv_get("eof-reached") is True, timeout=20)
        self.assertEqual((run_bridge("player")["data"].get("item") or {}).get("uuid"), EP_2)
        self.wait_for(lambda: self.position() > 4, timeout=20)
        run_bridge("pause")
        paused_at = self.fake["progress"][EP_2]
        before = len(self.pushes_of(EP_2))
        run_bridge("toggle")
        self.wait_for(lambda: self.position() > paused_at + 12, timeout=30)
        self.age_last_push(40)
        run_bridge("player")
        self.assertTrue(self.pushes_of(EP_2)[before:], "nothing of EP_2 pushed after Play")
        self.assertGreater(self.fake["progress"][EP_2], paused_at + 8)
        run_bridge("stop")
        self.assertEqual((run_bridge("toggle")["data"].get("item") or {}).get("uuid"), EP_2)

    def test_a_top_gone_from_its_feed_isnt_another_devices_move(self):
        # The resume check alone: a top that can't be followed (gone from
        # its feed) isn't "another device moved on" (said unverified at
        # every check, for good).
        self.gone_on_up_next()
        self.play_then_pause()
        self.assertTrue(bridge.load_playback().get("atTop"))
        self.fake["upnext"] = [GONE] + [u for u in self.fake["upnext"] if u != GONE]
        run_bridge("toggle")
        state = bridge.load_playback()
        self.assertEqual(state["episode"]["uuid"], EP_1)
        self.assertFalse(state.get("unconfirmed"))

    def test_a_resume_pocket_casts_cant_confirm_is_said(self):
        # "Unverified" was silent however long it lasted: no push was tried,
        # so "not synced" never showed.
        self.play_then_pause()
        self.fake["fail"] = {"/user/episode": 10 ** 6}
        views = [run_bridge("toggle")["data"]]
        self.wait_for(lambda: (self.mpv_get("time-pos") or 0) > 6, timeout=30)  # (not by polls: each counts)
        for _ in range(3):
            self.age_last_push(40)
            views.append(run_bridge("player")["data"])
        self.assertEqual(len([v for v in views if v.get("syncFailed")]), 1, views)

    def test_a_stop_after_a_failed_pause_never_unmarks_a_played_mark(self):
        # The reviewer's surviving mutant M14: Pocket Casts at 20, paused
        # here at 26+ with the pause's push failed; the phone marks it played
        # without moving its place; Stop must not push 26 in progress over
        # "played" (paused_push_stands reads the mark).
        self.unsent_paused()
        self.other_device(EP_1, 20, bridge.STATUS_PLAYED)
        self.fake["fail"] = {}
        run_bridge("stop")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_a_place_played_after_the_phones_unplayed_mark_is_kept(self):
        # The reviewer's surviving mutant M4: the phone marked it unplayed
        # (0) while paused here; Play adopts 0 and plays on here, every push
        # failing; Stop; Play with nothing loaded starts there (nobody else
        # wrote since), not at 0.
        self.play_then_pause()
        self.assertTrue(run_bridge("toggle")["ok"])
        self.wait_for(lambda: self.position() > 21, timeout=30)
        run_bridge("pause")
        self.other_device(EP_1, 0, bridge.STATUS_UNPLAYED)
        run_bridge("toggle")
        self.wait_for(lambda: 10 < self.position() < 40, timeout=30)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        place = bridge.load_playback()["unsentPush"]["position"]
        run_bridge("stop")
        self.fake["fail"] = {}
        self.assertGreater(run_bridge("toggle")["data"]["position"], place - 2)

    def test_a_failed_pause_place_without_an_answer_waits_for_the_next_play(self):
        # Pocket Casts can't be asked: nothing is sent, and the place is
        # kept (Play after the player closed starts there, nobody having
        # moved it).
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 6, timeout=20)
        self.fake["fail"] = {"/sync/update_episode": 1}
        run_bridge("pause")
        place = bridge.load_playback()["unsentPush"]["position"]
        before = len(self.pushes_of(EP_1))
        self.fake["fail"] = {"/user/episode": 1}
        run_bridge("stop")
        self.assertEqual(len(self.pushes_of(EP_1)), before)
        self.assertLess(self.fake["progress"][EP_1], 3)
        self.assertGreater(run_bridge("toggle")["data"]["position"], place - 1)

    # --- Strict review 24 (F1, F3, F4, T3, T4).
    def up_next_start_unsent(self, via_next=False):
        """A show you don't follow, the phone at 10 with it on Up Next;
        started here from Up Next's sync data (no record seen, Pocket Casts'
        place 10), every push failing; played on, paused; then the phone
        finishes it (played, off Up Next) and its lookup comes back empty."""
        f = self.fake
        f["unfollowed"] = {PODCAST_B}
        f["recorded"] = {EP_3}
        f["syncStatus"] = True
        self.other_device(EP_3, 10)
        if via_next:
            self.play_then_pause()  # EP_1, a show you follow
            f["upnext"] = [EP_1, EP_3, EP_2]
        else:
            f["upnext"] = [EP_3]
            self.login()
        f["fail"] = {"/sync/update_episode": 1000}
        r = run_bridge("next" if via_next else "toggle")
        self.assertEqual(r["data"]["item"]["uuid"], EP_3, r)
        state = bridge.load_playback()
        self.assertFalse(state.get("recordSeen"))
        self.assertEqual(state.get("lastSyncPos"), 10)
        self.wait_for(lambda: (self.mpv_get("time-pos") or 0) > 13, timeout=20)
        run_bridge("pause")
        self.other_device(EP_3, 120, bridge.STATUS_PLAYED)
        f["upnext"] = [u for u in f["upnext"] if u != EP_3]
        f["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        f["fail"] = {}

    def test_an_up_next_place_makes_an_empty_lookup_no_answer_on_resume(self):
        # The resume check kept its own older rule for an empty lookup (a
        # record seen, a show you follow, a place listed elsewhere), not
        # record_held: Play said "same" and the next push sent 13 in progress
        # over the phone's "played".
        self.up_next_start_unsent()
        run_bridge("toggle")
        self.assertTrue(bridge.load_playback().get("unconfirmed"))
        self.wait_for(lambda: (self.mpv_get("time-pos") or 0) > 15, timeout=20)
        run_bridge("pause")
        self.assertEqual(self.fake["status"][EP_3], bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["progress"][EP_3], 120)

    def test_an_up_next_place_by_next_makes_an_empty_lookup_no_answer(self):
        # The same through Next, another episode still queued (atTop false).
        self.up_next_start_unsent(via_next=True)
        run_bridge("toggle")
        self.wait_for(lambda: (self.mpv_get("time-pos") or 0) > 15, timeout=20)
        run_bridge("pause")
        self.assertEqual(self.fake["status"][EP_3], bridge.STATUS_PLAYED)

    def test_a_pending_end_from_an_up_next_place_waits_on_an_empty_lookup(self):
        # empty_lookup_answers had the same older rule: an end reached here
        # (from Up Next's place, 112), its mark and removal failing; the
        # phone went back to 60; an empty lookup was taken for "nobody has a
        # place", and the retry marked it played over the phone's 60.
        f = self.fake
        f["unfollowed"] = {PODCAST_B}
        f["recorded"] = {EP_3}
        f["syncStatus"] = True
        self.other_device(EP_3, 112)
        f["upnext"] = [EP_3]
        self.login()
        f["fail"] = {"/sync/update_episode": 1000, "/up_next/remove": 1000}
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_3)
        self.assertFalse(bridge.load_playback().get("recordSeen"))
        self.wait_for(lambda: run_bridge("player", "--no-autoplay")["data"].get("ended"), timeout=30)
        self.assertEqual([p["uuid"] for p in bridge.load_playback().get("pendingFinish") or []], [EP_3])
        self.other_device(EP_3, 60)  # the phone went back into it
        f["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        f["notListed"] = f["noSync"] = {EP_3}
        f["fail"] = {}
        run_bridge("toggle")  # Play at its end: the pending end is retried first
        self.assertEqual((self.fake["progress"][EP_3], self.fake["status"][EP_3]),
                         (60, bridge.STATUS_IN_PROGRESS))
        self.assertEqual([p["uuid"] for p in bridge.load_playback().get("pendingFinish") or []], [EP_3])

    def test_a_pending_ends_place_makes_an_empty_lookup_no_answer(self):
        # The reviewer's surviving mutant (record_held without its
        # pendingFinish clause): an end here whose mark failed, another
        # episode loaded since, then Play from a list on an empty lookup
        # must refuse, not start it from the public list at 0.
        f = self.fake
        f["unfollowed"] = {PODCAST_B}
        f["recorded"] = {EP_3}
        f["notListed"] = f["noSync"] = {EP_3}
        self.other_device(EP_3, 112)
        self.login()
        self.assertTrue(run_bridge("play", EP_3, "--podcast", PODCAST_B)["ok"])  # from 112: its push lands
        f["fail"] = {"/sync/update_episode": 1000, "/up_next/remove": 1000}
        self.wait_for(lambda: run_bridge("player", "--no-autoplay")["data"].get("ended"), timeout=30)
        self.assertEqual([p["uuid"] for p in bridge.load_playback().get("pendingFinish") or []], [EP_3])
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        f["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        before = len(self.pushes_of(EP_3))
        self.assertEqual(run_bridge("play", EP_3, "--podcast", PODCAST_B).get("code"), "no_record")
        self.assertEqual(self.pushes_of(EP_3)[before:], [])

    def test_a_last_episode_pocket_casts_forgot_says_so(self):
        # Play with nothing loaded refuses for as long as the lookup comes
        # back empty for an episode it must have a record of: said as it is,
        # naming the episode, and Next still moves on.
        f = self.fake
        f["unfollowed"] = {PODCAST_B}
        f["notListed"] = f["noSync"] = {EP_3}
        self.play_then_pause(EP_3, PODCAST_B)
        self.assertTrue(bridge.load_playback().get("recordSeen"))
        run_bridge("stop")
        f["upnext"] = [EP_1, EP_2]
        f["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        r = run_bridge("toggle")
        self.assertEqual(r.get("code"), "no_record")
        self.assertIn(f["episodes"][EP_3]["title"][:20], r["error"])
        self.assertIn("another episode", r["error"])
        self.assertNotIn("didn't answer", r["error"])
        self.assertEqual(run_bridge("next")["data"]["item"]["uuid"], EP_1)

    def test_an_answered_check_ends_a_run_of_failures(self):
        # pushFailures counted an unverified check and kept counting past an
        # answer: one failed push after it was said at once.
        self.play_then_pause()
        self.fake["fail"] = {"/user/episode": 1}
        self.mpv_set_pause(False)  # a media key: the poll asks, unanswered
        run_bridge("player")
        self.assertEqual(bridge.load_playback().get("pushFailures"), 1)
        run_bridge("player")  # asks again: answered
        self.assertIsNone(bridge.load_playback().get("pushFailures"))
        self.wait_for(lambda: (self.mpv_get("time-pos") or 0) > 3, timeout=20)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.age_last_push(40)
        self.assertFalse(run_bridge("player")["data"].get("syncFailed"))  # one failure: not said yet
        self.wait_for(lambda: (self.mpv_get("time-pos") or 0) > 5, timeout=20)
        self.age_last_push(40)
        self.assertTrue(run_bridge("player")["data"].get("syncFailed"))  # two in a row: said

    def test_plays_unanswered_check_is_asked_again_by_the_next_poll(self):
        # The reviewer's surviving mutant (Play's unverified check not
        # setting checkServer): the next poll, well inside the 90 s, asks.
        # Paused by a media key no poll saw, so nothing had set it before.
        self.play_then_pause()
        run_bridge("toggle")  # answered: checkServer off
        self.wait_for(lambda: (self.mpv_get("time-pos") or 0) > 2, timeout=20)
        self.mpv_set_pause(True)
        self.assertFalse(bridge.load_playback().get("checkServer"))
        self.fake["fail"] = {"/user/episode": 1}
        run_bridge("toggle")
        self.assertTrue(bridge.load_playback().get("unconfirmed"))
        before = len(self.writes("/user/episode"))
        run_bridge("player")
        self.assertGreater(len(self.writes("/user/episode")), before)
        self.assertFalse(bridge.load_playback().get("unconfirmed"))

    # --- Strict review 15 (H1): an unsent place left behind by a switch.
    def unsent_paused(self):
        """Played from 20 to past 26 here; the pause's push (and its poll's)
        failed: Pocket Casts still has 20, this machine 26+."""
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 26)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        run_bridge("player")
        self.assertGreater(bridge.load_playback()["unsentPush"]["position"], 25)
        self.assertEqual(self.fake["progress"][EP_1], 20)

    def age_unsent_tries(self, seconds=120):
        state = bridge.load_playback()
        for entry in state.get("unsentPlaces") or []:
            entry["tried"] -= seconds
        bridge.save_playback(state)

    def test_next_sends_the_place_it_leaves_unsent(self):
        # Next took the episode off Up Next and dropped the place this
        # machine played and couldn't send: Pocket Casts kept 20.
        self.unsent_paused()
        self.age_last_push(120)  # two minutes later, the network is back
        self.fake["fail"] = {}
        self.assertTrue(run_bridge("next")["ok"])
        self.assertGreater(self.fake["progress"][EP_1], 25)
        self.assertEqual(bridge.load_playback().get("unsentPlaces"), [])

    def test_a_place_left_unsent_by_next_is_where_a_reload_starts_and_is_sent_later(self):
        self.unsent_paused()
        self.age_last_push(120)
        self.assertTrue(run_bridge("next")["ok"])  # still no network for pushes
        self.assertEqual(self.fake["progress"][EP_1], 20)
        self.assertEqual([p["uuid"] for p in bridge.load_playback()["unsentPlaces"]], [EP_1])
        self.fake["fail"] = {}
        self.age_unsent_tries()
        run_bridge("player")  # a poll, once Pocket Casts can be told
        self.assertGreater(self.fake["progress"][EP_1], 25)
        self.assertEqual(bridge.load_playback()["unsentPlaces"], [])

    def test_a_place_left_unsent_starts_its_episode_again_from_a_list(self):
        # Played another after the idle unload, then this one from a list.
        self.unsent_paused()
        self.age_last_push(16 * 60)
        run_bridge("stop", "--if-paused")
        self.assertTrue(run_bridge("play", EP_3, "--podcast", PODCAST_B)["ok"])  # pushes still failing
        run_bridge("stop")
        self.fake["fail"] = {}
        view = run_bridge("play", EP_1, "--podcast", PODCAST_A)["data"]
        self.assertGreater(view["position"], 25)
        self.assertGreater(self.fake["progress"][EP_1], 25)  # and sent now
        self.assertNotIn("unsentPush", bridge.load_playback())

    def test_following_the_phone_to_another_episode_sends_this_ones_unsent_place(self):
        # The phone started EP_2 (nobody wrote EP_1): Play follows it, and
        # EP_1's place from here is still the latest there is.
        self.unsent_paused()
        self.fake["fail"] = {}
        self.fake["upnext"] = [EP_2, EP_1]
        self.other_device(EP_2, 30)
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_2)
        self.assertGreater(self.fake["progress"][EP_1], 25)

    def test_a_place_left_unsent_never_goes_over_another_devices(self):
        self.unsent_paused()
        self.age_last_push(120)
        self.assertTrue(run_bridge("next")["ok"])
        self.other_device(EP_1, 40)  # the phone played on in it meanwhile
        self.fake["fail"] = {}
        self.age_unsent_tries()
        run_bridge("player")
        self.assertEqual(self.fake["progress"][EP_1], 40)
        self.assertEqual(bridge.load_playback()["unsentPlaces"], [])  # its say stands
        run_bridge("stop")
        self.assertTrue(38 < run_bridge("play", EP_1, "--podcast", PODCAST_A)["data"]["position"] < 45)

    def test_a_place_left_unsent_never_reopens_an_episode_finished_elsewhere(self):
        self.unsent_paused()
        self.age_last_push(120)
        self.assertTrue(run_bridge("next")["ok"])
        self.other_device(EP_1, 20, bridge.STATUS_PLAYED)  # the phone marked it played, its place unchanged
        self.fake["fail"] = {}
        self.age_unsent_tries()
        run_bridge("player")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertEqual(bridge.load_playback()["unsentPlaces"], [])

    def test_a_place_left_unsent_is_kept_for_an_hour_only(self):
        self.unsent_paused()
        self.age_last_push(120)
        self.assertTrue(run_bridge("next")["ok"])
        state = bridge.load_playback()
        state["unsentPlaces"][0]["at"] -= bridge.UNSENT_KEPT
        bridge.save_playback(state)
        self.fake["fail"] = {}
        self.age_unsent_tries()
        run_bridge("player")
        self.assertEqual(self.fake["progress"][EP_1], 20)
        run_bridge("stop")
        self.assertLess(run_bridge("play", EP_1, "--podcast", PODCAST_A)["data"]["position"], 22)

    def test_a_kept_place_survives_a_reload_whose_push_fails_too(self):
        # Strict review 15 (two of the reviewer's mutants survived): the
        # reload keeps the unsent place until a push of it goes through, and
        # still compares with Pocket Casts' place (20), not its own.
        self.unsent_then_closed()
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertGreater(run_bridge("toggle")["data"]["position"], 25)
        self.assertGreater(bridge.load_playback()["unsentPush"]["position"], 25)  # kept through the reload
        run_bridge("pause")
        self.assertGreater(run_bridge("resume")["data"]["position"], 25)  # the check doesn't seek back to 20
        run_bridge("stop")
        self.fake["fail"] = {}
        self.assertGreater(run_bridge("toggle")["data"]["position"], 25)
        self.assertGreater(self.fake["progress"][EP_1], 25)

    # --- Strict review 16 (C1): a resume that took the phone's place makes
    # a place whose push failed history. lastSyncPos became the phone's
    # place, and the keep rules (comparing with it) read "nobody wrote":
    # a reload or a switch pushed the old place over the phone.
    def took_the_phones_place(self):
        self.unsent_paused()          # unsent 26+, Pocket Casts 20
        self.fake["fail"] = {}
        self.other_device(EP_1, 70)   # the phone carried on from 20 to 70
        run_bridge("toggle")          # Play asks first: seeks to 70
        self.assertEqual(self.fake["progress"][EP_1], 70)

    def test_a_place_unsent_before_a_resume_took_the_phones_place_never_comes_back_on_a_reload(self):
        self.took_the_phones_place()
        self.mpv_set_pause(True)      # a media key, at once
        run_bridge("player")
        run_bridge("stop")
        view = run_bridge("toggle")["data"]
        self.assertGreaterEqual(view["position"], 68)
        self.assertGreaterEqual(self.fake["progress"][EP_1], 68)

    def test_a_place_unsent_before_a_resume_took_the_phones_place_never_goes_with_next(self):
        self.took_the_phones_place()
        self.mpv_set_pause(True)
        run_bridge("player")
        self.assertTrue(run_bridge("next")["ok"])
        self.assertGreaterEqual(self.fake["progress"][EP_1], 68)
        self.assertEqual(bridge.load_playback().get("unsentPlaces"), [])

    def test_a_place_unsent_before_a_resume_took_the_phones_place_never_returns_after_a_stall(self):
        self.took_the_phones_place()
        with bridge.Mpv.connect() as player:  # the watcher reports a 20 s stall: nothing pushed
            player.set("user-data/legato", {"watching": True, "stallSince": int(time.time()) - 20})
        run_bridge("player")
        self.assertTrue(run_bridge("next")["ok"])
        self.assertGreaterEqual(self.fake["progress"][EP_1], 68)

    def test_a_place_unsent_before_a_resume_took_the_phones_place_never_returns_after_a_gap(self):
        self.took_the_phones_place()
        time.sleep(1.5)
        self.mpv_set_pause(True)      # a media key while the shell was down
        self.age_last_push(200)
        run_bridge("player")
        run_bridge("stop")
        self.assertGreaterEqual(run_bridge("toggle")["data"]["position"], 68)
        self.assertGreaterEqual(self.fake["progress"][EP_1], 68)

    # --- Strict review 16 (T1): kept_elsewhere's own rules, before any retry.
    def stashed(self):
        self.unsent_paused()
        self.age_last_push(120)
        self.assertTrue(run_bridge("next")["ok"])  # pushes still failing: stashed, tried just now
        self.assertEqual([p["uuid"] for p in bridge.load_playback()["unsentPlaces"]], [EP_1])

    def test_a_reload_of_an_episode_left_unsent_that_the_phone_moved_follows_the_phone(self):
        self.stashed()
        self.other_device(EP_1, 40)
        self.fake["fail"] = {}
        run_bridge("stop")
        view = run_bridge("play", EP_1, "--podcast", PODCAST_A)["data"]  # within the minute: no retry yet
        self.assertTrue(38 < view["position"] < 45, view["position"])
        self.assertGreaterEqual(self.fake["progress"][EP_1], 38)

    def test_a_reload_of_an_episode_left_unsent_keeps_its_place_through_a_push_that_fails_too(self):
        self.stashed()
        run_bridge("stop")
        self.assertGreater(run_bridge("play", EP_1, "--podcast", PODCAST_A)["data"]["position"], 25)  # pushes still failing
        kept = bridge.unsent_push(bridge.load_playback())  # carried, and measured from Pocket Casts' place now
        self.assertTrue(kept and kept["position"] > 25, kept)
        run_bridge("stop")
        self.fake["fail"] = {}
        self.assertGreater(run_bridge("toggle")["data"]["position"], 25)
        self.assertGreater(self.fake["progress"][EP_1], 25)

    def test_a_reload_of_an_episode_left_unsent_over_an_hour_ago_starts_at_pocket_casts_place(self):
        self.stashed()
        state = bridge.load_playback()
        state["unsentPlaces"][0]["at"] -= bridge.UNSENT_KEPT + 60
        bridge.save_playback(state)
        self.fake["fail"] = {}
        run_bridge("stop")
        self.assertLess(run_bridge("play", EP_1, "--podcast", PODCAST_A)["data"]["position"], 23)

    # --- Strict review 16 (M1): a mark is a say about where it stands.
    def left_unsent_from_the_top(self):
        """Started from the top here; the pause's push failed; Next stashed
        it with Pocket Casts at 0 (left)."""
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 6)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        run_bridge("player")
        self.assertTrue(run_bridge("next")["ok"])
        self.fake["fail"] = {}

    def test_mark_as_unplayed_here_isnt_undone_by_a_place_left_unsent(self):
        self.left_unsent_from_the_top()
        self.assertTrue(run_bridge("mark", "unplayed", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assertEqual(bridge.load_playback()["unsentPlaces"], [])
        self.age_unsent_tries()
        run_bridge("player")
        self.assertEqual((self.fake["progress"][EP_1], self.fake["status"][EP_1]), (0, bridge.STATUS_UNPLAYED))

    def test_mark_as_unplayed_on_the_phone_isnt_undone_by_a_place_left_unsent(self):
        self.left_unsent_from_the_top()
        self.other_device(EP_1, 0, bridge.STATUS_UNPLAYED)
        self.age_unsent_tries()
        run_bridge("player")
        self.assertEqual((self.fake["progress"][EP_1], self.fake["status"][EP_1]), (0, bridge.STATUS_UNPLAYED))
        self.assertEqual(bridge.load_playback()["unsentPlaces"], [])

    def test_a_reload_after_the_phone_marked_it_unplayed_starts_at_the_top(self):
        self.unsent_then_closed()
        self.other_device(EP_1, 0, bridge.STATUS_UNPLAYED)
        self.assertLess(run_bridge("toggle")["data"]["position"], 3)
        self.assertEqual(self.fake["progress"][EP_1], 0)

    # --- Strict review 16 (L1, R9a): ends whose lookup stays empty.
    def test_an_unwatched_end_of_an_episode_that_left_its_feed_lets_play_move_on(self):
        # Unanswered at its end (the player closed); since then the feed
        # moved on and Pocket Casts forgot it: Play said "try again" for six
        # hours. Gone, it's nothing to tell and nothing to follow.
        self.end_through_a_gap()
        self.fake["fail"] = {"/user/episode": 1}
        run_bridge("player", "--no-autoplay")
        self.assertFalse(self.mpv_running())
        self.fake["shows"][PODCAST_A]["episodes"] = [EP_2]
        self.fake["episodeReply"] = {EP_1: (404, b'{"errorMessage": "not found"}')}
        before = len(self.pushes_of(EP_1))
        view = run_bridge("toggle")["data"]
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.assertEqual(view["item"]["uuid"], EP_2)
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])

    def test_an_empty_lookup_at_an_unwatched_end_of_a_followed_show_is_no_answer(self):
        # Its record never seen here (loaded from Up Next's sync data), no
        # place listed anywhere: for a show you follow, an empty lookup is a
        # glitch, and the phone's place stands (never marked played). (Since
        # strict review 24 its Up Next place, 105, is a record held as well;
        # test_a_followed_shows_episode_listed_nowhere_isnt_started_from_its_list
        # has "a show you follow" alone.)
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.fake["upnext"] = [EP_1, EP_2]
        self.fake["syncStatus"] = True  # (its status in Up Next's sync data: no record read for it)
        self.other_device(EP_2, 105)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        run_bridge("pause")  # (so Next pushes nothing of EP_1's)
        # EP_2's load push fails: a push that lands makes its record seen
        # (strict review 17), and the empty lookup would be no answer for that
        # alone, "a show you follow" never asked.
        self.fake["fail"] = {"/sync/update_episode": 1}
        self.assertEqual(run_bridge("next")["data"]["item"]["uuid"], EP_2)
        self.assertFalse(bridge.load_playback().get("recordSeen"))
        self.wait_for(lambda: self.position() > 111)
        self.age_last_push(600)
        self.wait_for(lambda: self.mpv_get("eof-reached") is True, timeout=15)
        self.other_device(EP_2, 50)
        self.fake["episodeReply"] = {EP_2: (404, b'{"errorMessage": "not found"}')}
        self.fake["noSync"] = self.fake["notListed"] = {EP_2}
        run_bridge("player", "--no-autoplay")
        self.assertEqual((self.fake["progress"][EP_2], self.fake["status"][EP_2]), (50, bridge.STATUS_IN_PROGRESS))
        self.assertFalse(self.mpv_running())

    # --- Strict review 17.
    def test_the_switch_never_follows_up_next_to_a_played_episode_it_has_no_sync_data_for(self):
        # F1: Up Next's reply had no sync entry for the new top (finished on
        # the phone, its removal not in yet); its record says played.
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 21)
        run_bridge("pause")
        run_bridge("player")
        self.other_device(EP_2, 100, bridge.STATUS_PLAYED)
        self.fake["upnext"] = [EP_2] + [u for u in self.fake["upnext"] if u != EP_2]
        self.fake["noSync"] = [EP_2]
        before = len(self.pushes_of(EP_2))
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertEqual(self.fake["status"][EP_2], bridge.STATUS_PLAYED)
        self.assertEqual(self.pushes_of(EP_2)[before:], [])
        run_bridge("pause")
        self.mpv_set_pause(False)  # a media key: the poll's check, the same
        self.assertEqual(run_bridge("player")["data"]["item"]["uuid"], EP_1)
        self.assertEqual(self.pushes_of(EP_2)[before:], [])

    def test_the_switch_follows_up_next_when_another_device_finished_this_one(self):
        # (The switch's other arm: this episode wasn't on top, and the phone
        # finished it: Up Next's top plays.)
        self.fake["upnext"] = [EP_2]
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        state = bridge.load_playback()
        state["atTop"] = False
        bridge.save_playback(state)
        self.fake["upnext"] = [EP_2]
        run_bridge("pause")
        self.other_device(EP_1, 0, bridge.STATUS_PLAYED)
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_2)

    def watched_end_told(self):
        """EP_1 played to its end here, watched, autoplay off: marked played,
        off Up Next, the player left loaded at its end."""
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.other_device(EP_1, 108)
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.mpv_get("eof-reached") is True
                      or run_bridge("player", "--no-autoplay") and False, timeout=20)
        run_bridge("player", "--no-autoplay")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertEqual(bridge.load_playback()["handledEnd"], EP_1)
        self.assertTrue(self.mpv_running())

    def test_play_at_an_end_the_phone_went_back_into_follows_the_phone(self):
        # F2: Play played it again from 0 and pushed 0 over the phone.
        self.watched_end_told()
        self.other_device(EP_1, 50)
        before = len(self.pushes_of(EP_1))
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertTrue(48 < view["position"] < 60, view["position"])
        self.assertNotIn(0, [b["position"] for b in self.pushes_of(EP_1)[before:]])
        self.assertGreaterEqual(self.fake["progress"][EP_1], 48)

    def test_play_with_the_player_closed_after_an_end_the_phone_went_back_into_follows_it(self):
        self.watched_end_told()
        run_bridge("stop")
        self.other_device(EP_1, 50)
        self.fake["upnext"] = [EP_1, EP_2]  # the phone plays it: back on top
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertTrue(48 < view["position"] < 60, view["position"])

    def test_play_at_an_end_pocket_casts_cant_be_asked_about_plays_nothing(self):
        self.watched_end_told()
        before = len(self.pushes_of(EP_1))
        self.fake["fail"] = {"/user/episode": 1}  # the network
        self.assertFalse(run_bridge("toggle")["ok"])
        self.fake["episodeReply"] = {EP_1: (404, b'{"errorMessage": "not found"}')}  # an empty answer
        self.assertFalse(run_bridge("toggle")["ok"])
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.fake["episodeReply"] = None
        self.assertLess(run_bridge("toggle")["data"]["position"], 5)  # asked, still played: from the top

    def test_play_at_a_handled_end_doesnt_judge_it_again(self):
        # F4: the self-check's verdict changed since (finished "failed"), and
        # Play took the finished episode for a break, pushed in progress.
        self.fake["episodes"][EP_1]["duration"] = 200  # listed longer than the file
        self.watched_end_told()
        with bridge.Mpv.connect() as player:
            version = bridge.player_versions(player)
        bridge.save_state("watchcheck.json", {"ffmpeg": version, "ok": False, "at": int(time.time())})
        before = len(self.pushes_of(EP_1))
        view = run_bridge("toggle")["data"]
        # Played again from the top (it ended here), not reloaded as a break
        # at its end and pushed there in progress.
        self.assertLess(view["position"], 5)
        self.assertEqual([b["position"] for b in self.pushes_of(EP_1)[before:] if b["position"] > 5], [])

    def test_a_place_played_from_the_top_while_every_push_failed_is_kept(self):
        # F3 (b): Pocket Casts never had a place from this load (its push
        # failed too): "unplayed at 0" is where this machine left it, not a
        # Mark as unplayed.
        self.login()
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 9, timeout=25)
        run_bridge("pause")
        run_bridge("player")
        run_bridge("stop")
        self.fake["fail"] = {}
        self.assertGreater(run_bridge("toggle")["data"]["position"], 8)
        self.assertGreater(self.fake["progress"][EP_1], 8)

    def test_a_skip_intro_whose_push_failed_isnt_taken_for_another_devices_write(self):
        # F3 (a): the unpushed start (the show's skip-intro) was taken for
        # Pocket Casts' place: the next check read Pocket Casts' own 0 as
        # another device's write and sent the player back there.
        self.fake["showSettings"] = {PODCAST_A: {"autoStartFrom": 10}}
        self.login()
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 18, timeout=25)
        run_bridge("pause")
        run_bridge("player")
        self.fake["fail"] = {}
        self.assertGreater(run_bridge("resume")["data"]["position"], 16)

    def test_a_skip_intro_whose_push_landed_is_pocket_casts_place_from_then_on(self):
        # Its push landed: Pocket Casts has the intro's end (lastSyncPos),
        # and a later failed stretch here isn't read as another write.
        self.fake["showSettings"] = {PODCAST_A: {"autoStartFrom": 10}}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assertEqual(self.fake["progress"][EP_1], 10)
        self.wait_for(lambda: self.position() > 18, timeout=25)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        run_bridge("player")
        self.fake["fail"] = {}
        self.assertGreater(run_bridge("resume")["data"]["position"], 16)

    def test_after_following_the_phone_a_failed_stretch_here_isnt_sent_back(self):
        # The check takes the phone's place as Pocket Casts' (lastSyncPos):
        # played on here with pushes failing, the next check is no "write
        # elsewhere" (without it, the player went back to the phone's place).
        self.took_the_phones_place()   # at 70
        self.wait_for(lambda: self.position() > 73)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        run_bridge("player")
        self.fake["fail"] = {}
        self.assertGreater(run_bridge("resume")["data"]["position"], 72)

    def test_an_episode_that_ended_here_is_never_left_unsent(self):
        # Its last stretch couldn't be sent and its finish neither; autoplay
        # moved on. Stashed, its place would go out in progress later, and
        # the pending finish then read "carried on": unfinished everywhere.
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.other_device(EP_1, 100)
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 104)
        self.fake["fail"] = {"/sync/update_episode": 1000, "/up_next/remove": 1000}
        self.age_last_push(31)
        run_bridge("player")  # its periodic push fails: unsent
        self.assertTrue(bridge.load_playback().get("unsentPush"))
        self.wait_for(lambda: (run_bridge("player")["data"].get("item") or {}).get("uuid") == EP_2, timeout=30)
        self.assertEqual(bridge.load_playback().get("unsentPlaces") or [], [])
        self.fake["fail"] = {}
        state = bridge.load_playback()
        for p in state.get("pendingFinish") or []:
            p["tried"] -= 120
        bridge.save_playback(state)
        run_bridge("player")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_a_record_without_a_place_never_sends_a_place_left_unsent(self):
        self.stashed()
        self.fake["fail"] = {}
        self.fake["episodeReply"] = {EP_1: (200, json.dumps({"uuid": EP_1, "playingStatus": 2}).encode())}
        self.age_unsent_tries()
        self.assertTrue(run_bridge("player")["ok"])
        self.assertEqual(self.fake["progress"][EP_1], 20)
        self.assertEqual([p["uuid"] for p in bridge.load_playback()["unsentPlaces"]], [EP_1])  # no answer: kept

    def test_a_push_that_lands_counts_as_a_record_seen(self):
        # F5: an episode of a show you don't follow, loaded from its public
        # list: its first push creates its record, so a later empty lookup is
        # a glitch, never "no place anywhere".
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["notListed"] = self.fake["noSync"] = {EP_3}
        self.login()
        self.assertTrue(run_bridge("play", EP_3, "--podcast", PODCAST_B)["ok"])
        self.assertTrue(bridge.load_playback()["recordSeen"])

    # --- Strict review 18 (F1): every way back into an end told here asks.
    def dragged_back_after_a_told_end(self, to):
        self.watched_end_told()
        with bridge.Mpv.connect() as player:
            self.wait_for(lambda: player.get("pause") is True)  # (mpv pauses itself at the end, a moment after)
        run_bridge("seek", "--episode", EP_1, str(to))  # dragged back while paused: nothing pushed
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_play_after_a_skip_back_from_a_told_end_follows_the_phone(self):
        self.dragged_back_after_a_told_end(10)
        self.other_device(EP_1, 50)  # the phone went back into it meanwhile
        before = len(self.pushes_of(EP_1))
        run_bridge("toggle")
        run_bridge("player", "--no-autoplay")  # (the poll its resume brings)
        pushed = [b["position"] for b in self.pushes_of(EP_1)[before:]]
        self.assertTrue(48 <= self.fake["progress"][EP_1] < 60, (pushed, self.fake["progress"][EP_1]))
        self.assertNotIn(10, pushed)

    def test_play_after_a_drag_from_a_told_end_follows_the_phone(self):
        self.dragged_back_after_a_told_end(100)
        self.other_device(EP_1, 50)
        before = len(self.pushes_of(EP_1))
        run_bridge("toggle")
        run_bridge("player", "--no-autoplay")
        pushed = [b["position"] for b in self.pushes_of(EP_1)[before:]]
        self.assertTrue(48 <= self.fake["progress"][EP_1] < 60, (pushed, self.fake["progress"][EP_1]))

    def test_a_media_key_after_a_drag_from_a_told_end_asks_first(self):
        self.dragged_back_after_a_told_end(100)
        self.other_device(EP_1, 50)
        before = len(self.pushes_of(EP_1))
        self.mpv_set_pause(False)  # a media key, playerctl
        run_bridge("player", "--no-autoplay")
        run_bridge("player", "--no-autoplay")  # (the next poll asks Pocket Casts)
        pushed = [b["position"] for b in self.pushes_of(EP_1)[before:]]
        self.assertTrue(48 <= self.fake["progress"][EP_1] < 60, (pushed, self.fake["progress"][EP_1]))

    def test_a_media_key_at_a_told_end_pocket_casts_cant_be_asked_about_pushes_nothing(self):
        self.dragged_back_after_a_told_end(100)
        before = len(self.pushes_of(EP_1))
        self.fake["fail"] = {"/user/episode": 1000}
        self.mpv_set_pause(False)
        run_bridge("player", "--no-autoplay")
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.assertEqual(bridge.load_playback()["handledEnd"], EP_1)  # still ended here till it can ask

    def test_a_drag_back_from_a_told_end_still_played_plays_it_again_from_there(self):
        # Nobody else went back into it: playing it again from the drag is
        # this machine's place, pushed in progress.
        self.dragged_back_after_a_told_end(100)
        run_bridge("toggle")
        run_bridge("player", "--no-autoplay")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)
        self.assertGreaterEqual(self.fake["progress"][EP_1], 98)

    # --- Strict review 18 (F3, F4, L3).
    def test_a_resume_check_whose_seek_never_happened_never_takes_the_place(self):
        # Fault injection: mpv's `path` read fails inside the poll's check (a
        # stall in its IPC): it took Pocket Casts' place as known though mpv
        # never went there, and the next push sent mpv's old place over it.
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 14, timeout=25)
        run_bridge("pause")
        self.other_device(EP_1, 2)  # the phone went back near the start
        self.mpv_set_pause(False)   # a media key
        real_get = bridge.Mpv.get
        calls = {"n": 0}

        def flaky(player, name, default=None):
            if name == "path":
                calls["n"] += 1
                if calls["n"] == 2:  # the check's own read (the snapshot's is the first)
                    return default
            return real_get(player, name, default)
        with mock.patch.object(bridge.Mpv, "get", flaky):
            run_bridge("player")
        self.age_last_push(31)
        run_bridge("player")
        self.assertLess(self.fake["progress"][EP_1], 6)

    def test_a_load_from_the_start_whose_push_failed_keeps_the_place_played(self):
        self.other_device(EP_1, 60)
        self.login()
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A, "--from-start")["ok"])
        self.wait_for(lambda: self.position() > 12, timeout=25)
        run_bridge("pause")
        self.fake["fail"] = {}
        self.assertLess(run_bridge("toggle")["data"]["position"], 40)  # Pocket Casts' 60 isn't another write

    def test_a_played_episode_replayed_while_its_push_fails_isnt_finished_elsewhere(self):
        self.other_device(EP_1, 120, bridge.STATUS_PLAYED)
        self.login()
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])  # from a list: replayed from 0
        self.wait_for(lambda: self.position() > 5, timeout=25)
        run_bridge("pause")
        self.fake["fail"] = {}
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertTrue(view["playing"])
        self.assertLess(view["position"], 40)

    def test_the_sleep_guards_mark_is_spent_once_the_suspend_happened(self):
        # Strict review 19: a 30 s mark tied to nothing left a Play right after
        # a short suspend loading paused. Once the suspend clock moved on, the
        # mark is spent.
        bridge.mark_sleeping()
        self.assertTrue(bridge.sleeping_soon())
        later = bridge.sleep_offset() + 60
        with mock.patch.object(bridge, "sleep_offset", lambda: later):
            self.assertFalse(bridge.sleeping_soon())

    def test_a_load_just_as_the_sleep_guard_pauses_loads_paused(self):
        # L3: a Play holding the state lock when the guard paused for a
        # suspend loaded with pause=no and played behind the lock screen.
        self.login()
        bridge.mark_sleeping()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assertIs(self.mpv_paused(), True)

    # --- Strict review 19.
    def replayed_with_pushes_failing(self):
        """EP_1 played everywhere (at 120); replayed here from a list (from
        0), played past 9 s, every push failing."""
        self.other_device(EP_1, 120, bridge.STATUS_PLAYED)
        self.login()
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 9, timeout=25)
        run_bridge("pause")
        run_bridge("player")
        unsent = bridge.load_playback().get("unsentPush")
        self.assertTrue(unsent and unsent["position"] > 8, unsent)

    def test_a_played_episode_replayed_here_keeps_its_unsent_place_through_stop(self):
        # "Played" read as a new mark dropped it: Play went to Up Next's next.
        self.replayed_with_pushes_failing()
        run_bridge("stop")
        self.fake["fail"] = {}
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertGreater(view["position"], 7)

    def test_a_played_episode_replayed_here_sends_its_unsent_place_after_next(self):
        self.replayed_with_pushes_failing()
        self.assertTrue(run_bridge("next")["ok"])
        self.fake["fail"] = {}
        self.age_unsent_tries()
        run_bridge("player")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)
        self.assertTrue(7 < self.fake["progress"][EP_1] < 60, self.fake["progress"][EP_1])

    def test_a_play_again_whose_pushes_fail_isnt_finished_elsewhere(self):
        self.watched_end_told()
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertTrue(run_bridge("toggle")["data"]["playing"])  # played again from the top
        self.assertIsNotNone(bridge.unsent_push(bridge.load_playback()))  # its failed push kept at once
        self.wait_for(lambda: self.position() > 5, timeout=20)
        run_bridge("pause")
        run_bridge("player", "--no-autoplay")
        self.fake["fail"] = {}
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertGreater(view["position"], 4)

    # Strict review 20 (F1, critical): round 19 took Pocket Casts showing any
    # place this machine had tried to push for its own (a reply lost), and a
    # phone that stopped near one was overwritten. Withdrawn: another
    # device's place always wins over a place left unsent.
    def failed_then_dragged_back(self):
        """Pushes fail at 24 and 31 while it plays on, then a drag back to 5
        (its push fails too): unsent at 5, Pocket Casts at 20."""
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.wait_for(lambda: self.position() > 24, timeout=20)
        self.age_last_push(31)
        run_bridge("player")
        self.wait_for(lambda: self.position() > 31, timeout=20)
        self.age_last_push(31)
        run_bridge("player")
        self.assertTrue(run_bridge("seek", "--episode", EP_1, "5")["ok"])
        run_bridge("pause")
        run_bridge("player")
        self.assertLess(bridge.load_playback()["unsentPush"]["position"], 9)

    def test_a_phone_that_stopped_near_a_place_tried_here_wins_at_play(self):
        self.failed_then_dragged_back()
        self.other_device(EP_1, 33)  # within the slack of the 31 tried here
        self.fake["fail"] = {}
        run_bridge("toggle")
        time.sleep(1)
        self.age_last_push(31)
        run_bridge("player")
        self.assertGreaterEqual(self.fake["progress"][EP_1], 30)

    def test_a_phone_that_stopped_near_a_place_tried_here_wins_after_next(self):
        self.failed_then_dragged_back()
        self.assertTrue(run_bridge("next")["ok"])
        self.other_device(EP_1, 33)
        self.fake["fail"] = {}
        self.age_unsent_tries()
        run_bridge("player")
        self.assertEqual(self.fake["progress"][EP_1], 33)

    def replayed_to_its_end(self, mark_fails):
        """A played episode replayed here, its pushes failing, played to its
        end here again (strict review 20, F2)."""
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.other_device(EP_1, 120, bridge.STATUS_PLAYED)
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 2, timeout=20)
        self.assertTrue(run_bridge("seek", "--episode", EP_1, "100")["ok"])
        self.wait_for(lambda: self.position() > 104, timeout=20)
        self.age_last_push(31)
        run_bridge("player", "--no-autoplay")
        self.assertTrue(bridge.load_playback().get("unsentPush"))
        if not mark_fails:
            self.fake["fail"] = {}
        self.wait_for(lambda: self.mpv_get("eof-reached") is True, timeout=20)
        run_bridge("player", "--no-autoplay")
        self.fake["fail"] = {}
        run_bridge("stop")

    def test_a_replay_played_to_its_end_isnt_reopened_by_its_old_unsent_place(self):
        self.replayed_to_its_end(mark_fails=False)
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_2)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_a_replay_played_to_its_end_whose_mark_failed_isnt_reopened_either(self):
        self.replayed_to_its_end(mark_fails=True)
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_2)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_an_old_state_files_tried_pushes_are_dropped(self):
        state = {"episode": {"uuid": EP_1}, "unsentPush": {"uuid": EP_1, "position": 5.0, "at": 1.0, "left": 0.0,
                                                           "triedPushes": 3}}
        bridge.clean_playback(state)
        self.assertNotIn("triedPushes", state["unsentPush"])

    def test_next_reads_the_record_of_an_up_next_entry_without_a_status(self):
        # Up Next's entry had a place but no status (the fake's default
        # shape): taken for in progress, a played episode was loaded and
        # pushed in progress.
        self.fake["upnext"] = [EP_1, EP_2, EP_3]
        self.other_device(EP_2, 110, bridge.STATUS_PLAYED)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = run_bridge("next")["data"]
        self.assertEqual(self.fake["status"][EP_2], bridge.STATUS_PLAYED)
        self.assertEqual(view["item"]["uuid"], EP_3)

    def test_a_play_in_flight_longer_than_the_guards_wait_stays_paused(self):
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 0.5)
        run_bridge("pause")
        real = bridge.user_episode
        guards = []

        def slow_answer(uuid):
            guard = threading.Thread(target=bridge.pause_for_sleep)
            guard.start()
            guards.append(guard)
            time.sleep(7.5)  # past the guard's 6 s wait for the lock
            return real(uuid)
        try:
            with mock.patch.object(bridge, "user_episode", slow_answer):
                run_bridge("toggle")
            guards[0].join(15)
        finally:
            bridge.HTTP_TIMEOUT, bridge.REFRESH_ALLOWED = 15, True
        self.assertIs(self.mpv_paused(), True)

    def test_play_again_as_the_sleep_guard_pauses_for_a_suspend_stays_paused(self):
        self.watched_end_told()
        bridge.mark_sleeping()
        run_bridge("toggle")  # played again from the top, but not unpaused behind the lock screen
        self.assertIs(self.mpv_paused(), True)

    def test_play_with_nothing_loaded_after_marking_the_last_episode_played_moves_on(self):
        # Its Up Next removal keeps failing: a pending finish, but a told one
        # (played), not an end Pocket Casts couldn't confirm.
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        run_bridge("stop")
        self.fake["fail"] = {"/up_next/remove": 1000}
        self.assertTrue(run_bridge("mark", "played", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_2)

    # --- Strict review 15 (H2, L1): an end that isn't known to have ended here.
    def test_an_unwatched_end_pocket_casts_couldnt_confirm_is_never_played_again_over_the_phone(self):
        # The end's record read failed (the outage that left it unwatched):
        # it stayed "ended here", and Play played it again from 0 and pushed
        # 0 over the phone's place.
        self.end_through_a_gap()
        self.other_device(EP_1, 50)  # the phone went back into it
        self.fake["fail"] = {"/user/episode": 1}
        run_bridge("player", "--no-autoplay")
        self.fake["fail"] = {}
        state = bridge.load_playback()
        self.assertEqual(state["handledEnd"], "")
        self.assertFalse(self.mpv_running())
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)
        before = len(self.pushes_of(EP_1))
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertTrue(48 < view["position"] < 60, view["position"])  # where the phone is
        self.assertNotIn(0, [b["position"] for b in self.pushes_of(EP_1)[before:]])
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])

    def test_an_unwatched_end_confirmed_later_is_marked_played(self):
        self.end_through_a_gap()
        self.fake["fail"] = {"/user/episode": 1}
        run_bridge("player", "--no-autoplay")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)  # not yet: unknown
        self.fake["fail"] = {"/user/episode": 1}
        self.assertFalse(run_bridge("toggle")["ok"])  # still no answer: neither replayed nor skipped
        self.assertFalse(self.mpv_running())
        self.fake["fail"] = {}
        view = run_bridge("toggle")["data"]  # nobody carried on: it ended here
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertNotIn(EP_1, self.fake["upnext"])
        self.assertEqual(view["item"]["uuid"], EP_2)

    def test_an_unwatched_end_confirmed_while_its_mark_fails_is_never_played_again(self):
        # The retry at Play confirms the end (nobody carried on) but the
        # played mark fails: it ended here all the same, so Play moves on
        # to the next, not back into its last minutes; a later retry marks it.
        self.end_through_a_gap()
        self.fake["fail"] = {"/user/episode": 1}
        run_bridge("player", "--no-autoplay")
        self.fake["fail"] = {"/sync/update_episode": 1}  # the mark, first of the pushes
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_2)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)
        state = bridge.load_playback()
        self.assertEqual([(p["uuid"], p.get("confirmed")) for p in state["pendingFinish"]], [(EP_1, True)])
        state["pendingFinish"][0]["tried"] -= 60
        bridge.save_playback(state)
        run_bridge("player")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_an_unwatched_end_of_an_episode_pocket_casts_keeps_no_record_of_is_settled(self):
        # A show you don't follow, every push from here failed: no record, no
        # place anywhere. An empty lookup is an answer then (check_server's
        # rule): the next Play marks it played and moves on, rather than say
        # "try again" for six hours or play it again from 0.
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["notListed"] = self.fake["noSync"] = {EP_3}
        self.fake["upnext"] = [EP_3, EP_2]
        self.login()
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.assertTrue(run_bridge("play", EP_3, "--podcast", PODCAST_B)["ok"])
        run_bridge("seek", "--episode", EP_3, "110")
        self.wait_for(lambda: self.position() > 111)
        self.age_last_push(600)
        self.wait_for(lambda: self.mpv_get("eof-reached") is True, timeout=15)
        # At the end, its empty lookup can't be judged (Up Next won't load):
        # no answer, so the player closes.
        self.fake["fail"] = {"/up_next/list": 1}
        run_bridge("player", "--no-autoplay")
        self.assertFalse(self.mpv_running())
        self.assertEqual(bridge.load_playback()["handledEnd"], "")
        self.fake["fail"] = {}
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_2)
        self.assertEqual(self.fake["status"].get(EP_3), bridge.STATUS_PLAYED)
        self.assertNotIn(EP_3, self.fake["upnext"])
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])

    def test_an_empty_lookup_at_an_unwatched_end_of_an_episode_with_a_record_is_no_answer(self):
        # Pocket Casts showed this episode's record before (you played it):
        # an empty lookup at its end is a glitch, not "no place anywhere",
        # and the phone's place in it stands.
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.fake["unfollowed"] = {PODCAST_B}
        self.fake["recorded"] = {EP_3}
        self.fake["notListed"] = self.fake["noSync"] = {EP_3}
        self.other_device(EP_3, 105)
        self.login()
        self.assertTrue(run_bridge("play", EP_3, "--podcast", PODCAST_B)["ok"])
        self.assertTrue(bridge.load_playback()["recordSeen"])
        self.wait_for(lambda: self.position() > 111)
        self.age_last_push(600)
        self.wait_for(lambda: self.mpv_get("eof-reached") is True, timeout=15)
        self.other_device(EP_3, 50)
        self.fake["episodeReply"] = {EP_3: (404, b'{"errorMessage": "not found"}')}
        run_bridge("player", "--no-autoplay")
        self.assertEqual(self.fake["status"][EP_3], bridge.STATUS_IN_PROGRESS)
        self.assertEqual(self.fake["progress"][EP_3], 50)
        self.assertFalse(self.mpv_running())

    def cut_off_at_an_unwatched_end(self):
        """The poll that handled an unwatched end was cut off (the deadline, a
        plugin reload) after recording it, before Pocket Casts answered:
        "ended here", the player at its end, the end unconfirmed."""
        self.end_through_a_gap()
        self.other_device(EP_1, 50)
        with mock.patch.object(bridge, "retry_pending_finish", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                with bridge.StateLock():
                    bridge.poll(autoplay=False)
        self.assertEqual(bridge.load_playback()["handledEnd"], EP_1)
        self.assertTrue(self.mpv_running())

    def test_a_drag_back_from_an_end_cut_off_while_asking_pushes_nothing(self):
        self.cut_off_at_an_unwatched_end()
        before = len(self.pushes_of(EP_1))
        run_bridge("seek", "--episode", EP_1, "30")  # back into it while mpv still plays at its end
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.fake["fail"] = {"/user/episode": 1000}  # and Pocket Casts still can't say
        run_bridge("player", "--no-autoplay")
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.assertEqual(self.fake["progress"][EP_1], 50)

    def test_play_at_an_end_cut_off_while_asking_asks_again(self):
        # A call cut off between recording the end and Pocket Casts' answer
        # leaves it "ended here" with the player at its end: Play asks
        # before playing it again.
        self.cut_off_at_an_unwatched_end()
        before = len(self.pushes_of(EP_1))
        self.fake["fail"] = {"/user/episode": 1}
        self.assertFalse(run_bridge("toggle")["ok"])
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.fake["fail"] = {}
        view = run_bridge("toggle")["data"]
        self.assertTrue(48 < view["position"] < 60, view["position"])
        self.assertNotIn(0, [b["position"] for b in self.pushes_of(EP_1)[before:]])

    def watched_end_unmarked(self):
        """EP_1 played to its end with Legato watching, and Pocket Casts
        couldn't be told (the mark and the removal failed)."""
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.other_device(EP_1, 110)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {"/sync/update_episode": 1, "/up_next/remove": 1}
        self.wait_for(lambda: bridge.load_playback().get("pendingFinish")
                      or run_bridge("player", "--no-autoplay") and False)
        self.assertEqual(bridge.load_playback()["handledEnd"], EP_1)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)

    def test_a_retry_that_finds_the_phone_carried_on_lets_play_follow_it(self):
        # Strict review 15 (L1): the retry dropped the entry but left the
        # episode "ended here": Play skipped it for Up Next's next.
        self.watched_end_unmarked()
        self.other_device(EP_1, 50)
        state = bridge.load_playback()
        state["pendingFinish"][0]["tried"] -= 60
        bridge.save_playback(state)
        run_bridge("player", "--no-autoplay")  # the retry: carried on elsewhere
        state = bridge.load_playback()
        self.assertEqual((state["handledEnd"], state["pendingFinish"]), ("", []))
        self.assertFalse(self.mpv_running())
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertTrue(48 < view["position"] < 60, view["position"])

    def test_play_at_a_watched_end_pocket_casts_wasnt_told_of_asks_first(self):
        # Strict review 18 (F2): with Pocket Casts out of reach, Play played
        # it again from 0 over a phone that had carried on in it (its mark
        # never landed, so the phone showed it in progress). No answer now:
        # "try again"; then it follows the phone.
        self.watched_end_unmarked()
        self.other_device(EP_1, 50)
        before = len(self.pushes_of(EP_1))
        self.fake["fail"] = {"/user/episode": 1}
        self.assertFalse(run_bridge("toggle")["ok"])
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertTrue(48 < view["position"] < 60, view["position"])
        self.assertNotIn(0, [b["position"] for b in self.pushes_of(EP_1)[before:]])

    def test_play_at_an_end_pocket_casts_wasnt_told_of_follows_the_phone(self):
        # Pressed before any retry: Play asks first, and follows the phone
        # rather than play it again from 0 over it.
        self.watched_end_unmarked()
        self.other_device(EP_1, 50)
        before = len(self.pushes_of(EP_1))
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertTrue(48 < view["position"] < 60, view["position"])
        self.assertNotIn(0, [b["position"] for b in self.pushes_of(EP_1)[before:]])

    # --- Strict review 15 (M1): played episodes still on Up Next.
    def test_next_never_replays_an_episode_you_marked_played(self):
        self.fake["upnext"] = [EP_1, EP_2, EP_3]
        self.other_device(EP_2, 60)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {"/up_next/remove": 1}
        self.assertTrue(run_bridge("mark", "played", EP_2, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {}
        self.assertEqual([p["uuid"] for p in bridge.load_playback()["pendingFinish"]], [EP_2])
        view = run_bridge("next")["data"]
        self.assertEqual(view["item"]["uuid"], EP_3)
        self.assertEqual(self.fake["status"][EP_2], bridge.STATUS_PLAYED)
        state = bridge.load_playback()
        state["pendingFinish"][0]["tried"] -= 60
        bridge.save_playback(state)
        run_bridge("player")  # a later retry takes it off Up Next
        self.assertNotIn(EP_2, self.fake["upnext"])
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])

    def test_next_never_replays_an_episode_finished_elsewhere_still_on_up_next(self):
        self.fake["syncStatus"] = True
        self.fake["upnext"] = [EP_1, EP_2, EP_3]
        self.other_device(EP_2, 120, bridge.STATUS_PLAYED)  # finished on the phone; its removal not in yet
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = run_bridge("next")["data"]
        self.assertEqual(view["item"]["uuid"], EP_3)
        self.assertEqual(self.fake["status"][EP_2], bridge.STATUS_PLAYED)

    def test_next_never_replays_a_played_episode_up_next_sends_no_sync_for(self):
        # No sync data for it: its record says played.
        self.fake["upnext"] = [EP_1, EP_2, EP_3]
        self.fake["noSync"] = [EP_2]
        self.other_device(EP_2, 120, bridge.STATUS_PLAYED)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assertEqual(run_bridge("next")["data"]["item"]["uuid"], EP_3)
        self.assertEqual(self.fake["status"][EP_2], bridge.STATUS_PLAYED)

    def test_the_switch_never_follows_up_next_to_a_played_episode(self):
        # The resume check: the top of Up Next changed, but to an episode
        # Pocket Casts says is played (its removal not in yet).
        self.fake["syncStatus"] = True
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assertTrue(self.fake["upnext"][0] == EP_1)
        run_bridge("pause")
        self.other_device(EP_2, 100, bridge.STATUS_PLAYED)
        self.fake["upnext"] = [EP_2] + [u for u in self.fake["upnext"] if u != EP_2]
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertEqual(self.fake["status"][EP_2], bridge.STATUS_PLAYED)

    def test_putting_back_an_episode_that_ended_here_stops_its_retry(self):
        # Strict review 15 (N3): queued again (or marked unplayed) on
        # purpose, a pending retry took it off Up Next again.
        self.fake["upnext"] = [EP_1, EP_2, EP_3]
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {"/up_next/remove": 1}
        self.assertTrue(run_bridge("mark", "played", EP_2, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {}
        self.assertTrue(run_bridge("queue", "last", EP_2, "--podcast", PODCAST_A)["ok"])
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])
        self.fake["fail"] = {"/up_next/remove": 1}
        self.assertTrue(run_bridge("mark", "played", EP_3, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {}
        self.assertTrue(run_bridge("mark", "unplayed", EP_3, "--podcast", PODCAST_A)["ok"])
        self.assertEqual(bridge.load_playback()["pendingFinish"], [])

    def test_an_end_on_a_resume_nobody_checked_asks_first(self):
        # Strict review 14 (F2): paused near the end (pushed), the phone went
        # back to 30, and a media key resumed here with no poll before the
        # end: the end was marked played everywhere, over the phone's 30.
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.other_device(EP_1, 110)
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 110.5)
        run_bridge("pause")
        self.other_device(EP_1, 30)
        self.mpv_set_pause(False)  # a media key; no poll until the end
        self.wait_for(lambda: self.mpv_get("eof-reached") is True, timeout=15)
        run_bridge("player", "--no-autoplay")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)
        self.assertEqual(self.fake["progress"][EP_1], 30)
        self.assertIn(EP_1, self.fake["upnext"])

    def test_a_media_widgets_seek_while_paused_is_sent(self):
        # Strict review 14 (F4): a scrub in a media widget, reported by mpv
        # as a seek (`--seeked`), is this machine's: sent, like the panel's.
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 31, timeout=30)
        run_bridge("pause")
        with bridge.Mpv.connect() as player:
            player.command("seek", 60, "absolute")
        time.sleep(0.3)
        run_bridge("player", "--seeked")
        self.assertGreaterEqual(self.fake["progress"][EP_1], 59)

    def test_a_move_while_paused_that_no_seek_explains_isnt_sent(self):
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 31, timeout=30)
        run_bridge("pause")
        pushed = self.fake["progress"][EP_1]
        with bridge.Mpv.connect() as player:
            player.command("seek", 60, "absolute")
        time.sleep(0.3)
        run_bridge("player")
        self.assertEqual(self.fake["progress"][EP_1], pushed)
        self.assertTrue(bridge.load_playback().get("unconfirmed"))

    def test_a_play_in_flight_as_the_lid_closes_is_paused_by_the_guard(self):
        # Strict review 14 (F5): mpv was still paused when the guard fired,
        # so it let the sleep go; the Play's check answered just before the
        # suspend and unpaused behind the lock screen.
        self.play_then_pause()
        real = bridge.user_episode
        guards, results = [], []

        def answered_after_the_guard_fired(uuid):
            guard = threading.Thread(target=lambda: results.append(bridge.pause_for_sleep()))
            guard.start()
            guards.append(guard)
            time.sleep(0.5)  # the guard finds mpv paused and waits for this Play
            return real(uuid)
        with mock.patch.object(bridge, "user_episode", answered_after_the_guard_fired):
            run_bridge("toggle")
        guards[0].join(15)
        bridge.HTTP_TIMEOUT, bridge.REFRESH_ALLOWED = 15, True  # (the guard lowers them for its own process)
        # Paused: by the guard after the Play (round 14), or, since round 19,
        # by the Play itself, which sees the guard's mark and doesn't unpause
        # (the guard then finds nothing to pause).
        self.assertIn(results, ([True], [False]))
        self.assertIs(self.mpv_paused(), True)

    def test_the_guards_unpushed_pause_after_a_long_sleep_loses_to_the_phone(self):
        # Strict review 13 (M1, P1e): the guard paused but couldn't take the
        # lock (a poll pushing on a slow link held it), so nothing was pushed
        # or tried. Half an hour asleep; the phone went back. Play asked, then
        # kept its own place.
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 31, timeout=30)
        time.sleep(4)
        held = bridge.StateLock()
        held.__enter__()
        try:
            self.assertTrue(bridge.pause_for_sleep())  # paused, not pushed
        finally:
            held.__exit__(None, None, None)
        bridge.HTTP_TIMEOUT, bridge.REFRESH_ALLOWED = 15, True  # (the guard lowers them for its own process)
        self.other_device(EP_1, 10)
        with self.woken(1800):
            run_bridge("player")     # the poll that sees the pause, after the wake
            run_bridge("toggle")
            time.sleep(0.5)
            run_bridge("pause")
        self.assertLess(self.fake["progress"][EP_1], 15, [b["position"] for b in self.pushes_of(EP_1)])

    def test_the_guards_unpushed_pause_after_a_short_sleep_isnt_pushed_blind(self):
        # Strict review 13 (L3): the same, after a sleep of half a minute: the
        # poll after the wake found the last push "recent" and pushed the
        # place the guard paused at over the phone's.
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 32, timeout=30)
        held = bridge.StateLock()
        held.__enter__()
        try:
            self.assertTrue(bridge.pause_for_sleep())
        finally:
            held.__exit__(None, None, None)
        bridge.HTTP_TIMEOUT, bridge.REFRESH_ALLOWED = 15, True
        self.other_device(EP_1, 60)  # the phone, during the sleep
        before = len(self.pushes_of(EP_1))
        with self.woken(30):
            run_bridge("player")
            run_bridge("stop")
        self.assertEqual(self.pushes_of(EP_1)[before:], [])
        self.assertEqual(self.fake["progress"][EP_1], 60)

    def test_a_push_cut_off_by_a_suspend_isnt_kept_as_unsent(self):
        # The sleep came during the periodic push itself: the place is from
        # before it, and the phone may go back meanwhile. Nothing to keep
        # over Pocket Casts' answer.
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 32, timeout=30)
        self.age_last_push(31)
        offset = [bridge._SLEEP_BASE]

        def push_then_sleep(item, position, status=bridge.STATUS_IN_PROGRESS):
            offset[0] = bridge._SLEEP_BASE + 600
            raise bridge.ApiError("slept", "The computer slept during this call: nothing was sent")
        with mock.patch.object(bridge, "push_position", push_then_sleep), \
                mock.patch.object(bridge, "sleep_offset", lambda: offset[0]):
            run_bridge("player")
        self.assertNotIn("unsentPush", bridge.load_playback())

    def test_a_pause_right_after_a_short_unguarded_sleep_pushes_nothing(self):
        # Under RECHECK_AFTER by the clock, but the machine slept: as old as
        # any gap (sync_age).
        self.other_device(EP_1, 30)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 32, timeout=30)
        self.other_device(EP_1, 60)
        before = len(self.pushes_of(EP_1))
        with self.woken(40):
            run_bridge("pause")
        self.assertEqual(self.pushes_of(EP_1)[before:], [])

    def mpv_get(self, name):
        with bridge.Mpv.connect() as player:
            return player.get(name)

    def end_through_a_gap(self):
        """EP_1 plays to its end while Legato isn't watching (off, or a sleep
        it missed): no poll from a few seconds before the end."""
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.other_device(EP_1, 110)
        self.fake["upnext"] = [EP_1, EP_2]
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 111)
        self.age_last_push(600)
        self.wait_for(lambda: self.mpv_get("eof-reached") is True, timeout=15)

    def test_an_end_reached_through_a_gap_is_no_news_when_the_phone_went_back(self):
        # Strict review 13 (M1, P1c): Legato's first poll marked it played
        # everywhere (the phone had gone back into it) and autoplayed the
        # next, asking nobody.
        self.end_through_a_gap()
        self.other_device(EP_1, 50)  # the phone went back into it meanwhile
        view = run_bridge("player")["data"]  # Legato back: its first poll
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_IN_PROGRESS)
        self.assertEqual(self.fake["progress"][EP_1], 50)
        self.assertIn(EP_1, self.fake["upnext"])
        self.assertFalse(view["playing"])
        self.assertNotEqual((view["item"] or {}).get("uuid"), EP_2)
        # Play picks up from the phone's place.
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertTrue(48 < view["position"] < 60, view["position"])

    def test_an_end_reached_through_a_gap_is_marked_played_but_starts_nothing(self):
        # Nobody else touched it: played, off Up Next; the next episode waits
        # for Play.
        self.end_through_a_gap()
        view = run_bridge("player")["data"]
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertNotIn(EP_1, self.fake["upnext"])
        self.assertEqual((view["item"] or {}).get("uuid"), EP_1)
        self.assertFalse(view["playing"])
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_2)

    def test_a_play_that_spans_a_suspend_loads_paused_and_pushes_nothing(self):
        # Strict review 13 (M2): Play pressed as the lid closed: EP_2's record
        # was read before the sleep, the load landed after it with pause=no
        # (playing behind the lock screen), and the next poll pushed the
        # pre-sleep place over the phone that played EP_2 on meanwhile.
        self.other_device(EP_2, 10)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 1, timeout=30)
        real = bridge.resolve_episode
        offset = [bridge._SLEEP_BASE]

        def resolved_then_slept(uuid, podcast_uuid=""):
            item = real(uuid, podcast_uuid)
            if uuid == EP_2:
                offset[0] = bridge._SLEEP_BASE + 600  # the machine sleeps here...
                self.other_device(EP_2, 60)           # ...and the phone plays EP_2 on
            return item
        with mock.patch.object(bridge, "resolve_episode", resolved_then_slept), \
                mock.patch.object(bridge, "sleep_offset", lambda: offset[0]):
            run_bridge("play", EP_2, "--podcast", PODCAST_A)
        self.assertIs(self.mpv_paused(), True)
        before = len(self.pushes_of(EP_2))
        with self.woken(600):
            self.mpv_set_pause(False)  # a media key after the wake
            time.sleep(1)
            run_bridge("player")       # the poll it brings asks first
            self.age_last_push(31)
            run_bridge("player")
        self.assertGreaterEqual(self.fake["progress"][EP_2], 60, [b["position"] for b in self.pushes_of(EP_2)[before:]])

    def test_a_sleep_while_the_file_loads_leaves_it_paused(self):
        # The guard's pause landed before the new file did (loadfile replaces
        # it, pause=no): paused once loaded.
        self.login()
        real = bridge.Mpv.wait_for_load
        offset = [bridge._SLEEP_BASE]

        def loaded_then_slept(player, *args, **kwargs):
            result = real(player, *args, **kwargs)
            offset[0] = bridge._SLEEP_BASE + 600
            return result
        with mock.patch.object(bridge.Mpv, "wait_for_load", loaded_then_slept), \
                mock.patch.object(bridge, "sleep_offset", lambda: offset[0]):
            run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertIs(self.mpv_paused(), True)

    def test_another_episodes_record_is_no_answer(self):
        # Strict review 12 (L1): a mix-up returning another episode's record.
        self.play_then_pause()
        self.other_device(EP_1, 30)
        other = json.dumps({"uuid": EP_2, "podcastUuid": PODCAST_A, "playedUpTo": 3, "playingStatus": 2}).encode()
        self.fake["episodeReply"] = {EP_1: (200, other)}
        run_bridge("toggle")
        self.assertTrue(bridge.load_playback().get("unconfirmed"))
        run_bridge("pause")
        self.assertEqual(self.fake["progress"][EP_1], 30)

    def test_a_record_without_a_position_is_no_answer(self):
        # Strict review 11 (M3): read as 0, the resume check sought to 0 and
        # the next push sent it. Every record has a position (checked live).
        self.play_then_pause()
        self.other_device(EP_1, 30)
        partial = json.dumps({"uuid": EP_1, "podcastUuid": PODCAST_A, "title": "One",
                              "url": self.fake["episodes"][EP_1]["url"]}).encode()
        self.fake["episodeReply"] = {EP_1: (200, partial)}
        run_bridge("toggle")
        self.assertTrue(bridge.load_playback().get("unconfirmed"))
        run_bridge("pause")
        self.assertEqual(self.fake["progress"][EP_1], 30)
        run_bridge("stop")
        self.assertEqual(run_bridge("play", EP_1, "--podcast", PODCAST_A).get("code"), "no_record")

    def test_next_without_up_nexts_sync_data_starts_from_the_record(self):
        # Strict review 10 (3) and 11 (M3): Up Next's reply without an
        # episode's sync data, or with an entry but no position (the real
        # reply leaves it out for episodes not started), read as 0 and
        # pushed 0 over the phone's 50.
        self.fake["syncStatus"] = True  # (statuses in the sync data: only a missing entry or place reads the record)
        self.play_then_pause()
        self.fake["upnext"] = [EP_1, EP_2]
        self.other_device(EP_2, 50)
        self.fake["noSync"] = {EP_2}
        result = run_bridge("next")
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["data"]["item"] or {}).get("uuid"), EP_2)
        self.assertGreaterEqual(min(b["position"] for b in self.pushes_of(EP_2)), 50)
        self.fake["noSync"] = set()
        self.fake["syncNoPosition"] = {EP_3}  # an entry that's there, with no position
        self.other_device(EP_3, 40)
        self.fake["upnext"] = [EP_2, EP_3]
        result = run_bridge("next")
        self.assertEqual((result["data"]["item"] or {}).get("uuid"), EP_3)
        self.assertGreaterEqual(min(b["position"] for b in self.pushes_of(EP_3)), 40)
        self.fake["episodeReply"] = {EP_1: (404, b"")}  # and an empty lookup for it refuses, never 0
        self.fake["noSync"] = {EP_1}
        self.fake["upnext"] = [EP_3, EP_1]
        before = len(self.pushes_of(EP_1))
        self.assertEqual(run_bridge("next").get("code"), "no_record")
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_after_an_unconfirmed_play_pocket_casts_answer_wins(self):
        # Strict review 10 (2): Play couldn't reach Pocket Casts, so it played
        # on unconfirmed; the phone had gone back to 5. The poll's answer must
        # win over the unconfirmed stretch, never push it.
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 8, timeout=30)
        run_bridge("pause")  # pushed at about 8
        self.other_device(EP_1, 1)  # the phone went back to the start
        self.fake["fail"] = {"/up_next/list": 1}  # Play's quick check gets no answer
        run_bridge("toggle")
        self.assertTrue(bridge.load_playback().get("unconfirmed"))
        time.sleep(1.5)
        run_bridge("player")  # the poll asks, and gets 1
        run_bridge("pause")
        self.assertLess(self.fake["progress"][EP_1], 5, [b["position"] for b in self.pushes_of(EP_1)])

    def test_a_show_you_dont_follow_still_plays_from_its_public_list(self):
        # No record exists for it: the empty lookup is the answer there.
        self.fake["unfollowed"] = {PODCAST_B}
        self.login()
        result = run_bridge("play", EP_3, "--podcast", PODCAST_B)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["item"]["uuid"], EP_3)

    def test_the_periodic_push_waits_while_unconfirmed(self):
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 1.5)
        state = bridge.load_playback()
        state.update(unconfirmed=True, checkServer=False, lastSyncAt=time.time() - 31)
        bridge.save_playback(state)
        before = len(self.pushes_of(EP_1))
        run_bridge("player")
        self.assertEqual(len(self.pushes_of(EP_1)), before)

    def test_play_after_the_player_closed_follows_the_top_of_up_next(self):
        # resume_last's atTop check (a surviving mutant in review 8): the phone
        # moved on to another episode: Play takes it, not the old one.
        self.play_then_pause()
        run_bridge("stop")
        state = bridge.load_playback()
        self.assertTrue(state.get("atTop"))
        self.fake["upnext"] = [EP_2, EP_1]
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_2)

    def test_a_media_key_resume_then_a_panel_pause_pushes_nothing_unchecked(self):
        # Strict review 7: the pause forced its push, past the check.
        self.play_then_pause()
        self.other_device(EP_1, 25)
        self.mpv_set_pause(False)
        time.sleep(1)
        run_bridge("pause")
        self.assertEqual(self.fake["progress"][EP_1], 25)

    def test_a_pause_after_a_gap_pushes_nothing(self):
        # The machine slept without the guard, the phone listened on; you wake
        # it and press Pause before any poll: that position is old news.
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 0.5)
        self.age_last_push(200)
        self.other_device(EP_1, 25)
        run_bridge("pause")
        self.assertEqual(self.fake["progress"][EP_1], 25)
        run_bridge("seek", "5", "--relative", "--episode", EP_1)  # a skip meanwhile: nothing either
        self.assertEqual(self.fake["progress"][EP_1], 25)

    def test_an_unsent_position_carries_on_while_nobody_moved_it(self):
        # Its push failed; Pocket Casts still has this machine's last push:
        # nobody moved it, so Play carries on from here.
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 26)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        self.fake["fail"] = {}
        self.assertGreater(run_bridge("resume")["data"]["position"], 25)

    def test_an_unsent_position_loses_to_any_write_elsewhere_since(self):
        # Strict review 14 (design): the phone went back after this machine's
        # push failed. Its write is newer than anything this machine sent:
        # it wins, even behind the unsent place (it used to be undone, within
        # the hour).
        self.other_device(EP_1, 20)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: self.position() > 26)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        run_bridge("pause")
        self.fake["fail"] = {}
        self.other_device(EP_1, 12)
        self.assertLess(run_bridge("resume")["data"]["position"], 15)
        run_bridge("stop")
        self.assertLess(run_bridge("toggle")["data"]["position"], 15)  # the same once the player closed

    def test_a_media_key_resume_then_stop_pushes_nothing_unchecked(self):
        # Strict review 5: playing again by a media key (not yet checked with
        # Pocket Casts), then Stop before any poll: the phone's further
        # position stays.
        self.play_then_pause()
        self.other_device(EP_1, 25)
        self.mpv_set_pause(False)
        time.sleep(1)
        run_bridge("stop")
        self.assertEqual(self.fake["progress"][EP_1], 25)

    def test_play_never_restarts_an_episode_finished_elsewhere(self):
        # The player closed; the phone finished the episode. Play takes the
        # top of Up Next, never the finished one from the top.
        self.play_then_pause()
        run_bridge("stop")
        state = bridge.load_playback()
        state["atTop"] = False  # only the finished check can tell
        bridge.save_playback(state)
        self.other_device(EP_1, 30, bridge.STATUS_PLAYED)
        self.fake["upnext"] = [EP_2]
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_2)

    def test_play_never_restarts_a_finished_episode_still_on_top_of_up_next(self):
        # Finished on the phone, its removal from Up Next not through yet:
        # Play with nothing loaded takes what follows it, not it from the top.
        self.play_then_pause()
        run_bridge("stop")
        self.other_device(EP_1, 30, bridge.STATUS_PLAYED)
        self.fake["upnext"] = [EP_1, EP_2]
        before = len(self.pushes(EP_1))
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_2)
        self.assertEqual(self.pushes(EP_1)[before:], [])

    def test_resume_follows_a_rewind_on_another_device(self):
        # Rule 2 when Pocket Casts is behind this machine's last push: the
        # phone rewound on purpose, and its answer wins.
        self.other_device(EP_1, 40)
        self.play_then_pause()
        self.other_device(EP_1, 10)
        self.assertLess(run_bridge("resume")["data"]["position"], 15)

    def test_after_the_player_closed_a_rewind_on_another_device_wins(self):
        self.other_device(EP_1, 40)
        self.play_then_pause()
        run_bridge("stop")
        self.other_device(EP_1, 10)
        self.assertLess(run_bridge("toggle")["data"]["position"], 15)

    def test_after_the_player_closed_pocket_casts_further_on_wins(self):
        # Play after a stop or the idle unload loads the episode from where
        # Pocket Casts has it: the phone listened on, so not from here.
        self.play_then_pause()
        run_bridge("stop")
        self.other_device(EP_1, 60)
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertGreater(view["position"], 58)
        self.assertNotIn(True, [b["position"] < 58 for b in self.pushes(EP_1)[-1:]])  # nothing rewound

    def test_a_resume_with_no_other_device_carries_on_here(self):
        self.play_then_pause()
        paused_at = self.position()
        view = run_bridge("resume")["data"]
        self.assertTrue(view["playing"])
        self.assertLess(abs(view["position"] - paused_at), 2)

    def test_resume_seeks_to_where_another_device_left_off(self):
        self.play_then_pause()
        self.other_device(EP_1, 60)
        self.age_last_push(600)  # back here ten minutes later
        before = len(self.pushes(EP_1))
        view = run_bridge("resume")["data"]
        self.assertTrue(view["playing"])
        self.wait_for(lambda: self.position() >= 59)
        run_bridge("player")  # the next poll
        self.assertGreaterEqual(self.fake["progress"][EP_1], 59)
        self.assertTrue(all(body["position"] >= 59 for body in self.pushes(EP_1)[before:]))

    def test_a_media_key_resume_is_checked_too(self):
        self.play_then_pause()
        self.other_device(EP_1, 60)
        self.age_last_push(600)
        self.mpv_set_pause(False)
        self.wait_for(lambda: self.position() >= 59)
        self.assertGreaterEqual(self.fake["progress"][EP_1], 59)

    def test_media_key_pause_and_resume_are_checked(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: self.position() > 0.5)
        self.mpv_set_pause(True)
        run_bridge("player")  # a poll notices the pause
        self.other_device(EP_1, 60)
        self.mpv_set_pause(False)  # a minute later, not ten: no gap to go on
        self.wait_for(lambda: self.position() >= 59)
        self.assertGreaterEqual(self.fake["progress"][EP_1], 59)

    def test_waking_from_sleep_mid_episode_is_checked(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: self.position() > 0.5)
        # The machine slept while playing; the phone carried on from here.
        self.other_device(EP_1, 60)
        self.age_last_push(600)
        self.wait_for(lambda: self.position() >= 59)
        self.assertGreaterEqual(self.fake["progress"][EP_1], 59)

    def test_resume_follows_another_device_to_the_next_episode(self):
        self.play_then_pause()
        # On the phone: One played to its end, and Up Next moved on to Two.
        self.other_device(EP_1, 0, bridge.STATUS_PLAYED)
        self.fake["upnext"] = [EP_2]
        self.other_device(EP_2, 20)
        before = len(self.pushes(EP_1))
        view = run_bridge("resume")["data"]
        self.assertEqual(view["item"]["uuid"], EP_2)
        self.wait_for(lambda: self.position() >= 19)
        self.assertEqual(self.pushes(EP_1)[before:], [])
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"], [EP_2])

    def test_resume_follows_another_device_to_a_different_episode(self):
        self.play_then_pause()
        # On the phone: Three started part way through One.
        self.other_device(EP_1, 45)
        self.fake["upnext"] = [EP_3, EP_1, EP_2]
        self.other_device(EP_3, 30)
        before = len(self.pushes(EP_1))
        view = run_bridge("resume")["data"]
        self.assertEqual(view["item"]["uuid"], EP_3)
        self.wait_for(lambda: self.position() >= 29)
        self.assertEqual(self.pushes(EP_1)[before:], [])
        self.assertEqual(self.fake["progress"][EP_1], 45)

    def test_resume_when_another_device_finished_everything(self):
        self.play_then_pause()
        self.other_device(EP_1, 0, bridge.STATUS_PLAYED)
        self.fake["upnext"] = []
        result = run_bridge("resume")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "finished_elsewhere")
        self.wait_for(lambda: not self.mpv_running())
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        # Nor does playing again from nothing start it over.
        self.assertEqual(run_bridge("toggle")["code"], "nothing_queued")
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_stop_and_switching_leave_a_paused_position_alone(self):
        self.play_then_pause()
        self.other_device(EP_1, 60)
        run_bridge("play", EP_3, "--podcast", PODCAST_B)  # switch episodes here
        self.assertEqual(self.fake["progress"][EP_1], 60)
        self.wait_for(lambda: self.position() > 0.5)
        run_bridge("pause")
        self.other_device(EP_3, 30)
        run_bridge("pause")  # pausing what is already paused sends nothing
        self.assertEqual(self.fake["progress"][EP_3], 30)
        run_bridge("stop")
        self.assertEqual(self.fake["progress"][EP_3], 30)

    def test_a_paused_position_unsent_before_sleep_is_not_pushed_blind(self):
        self.play_then_pause()
        with bridge.Mpv.connect() as player:
            player.command("seek", 30, "absolute")  # moved while paused, never sent...
        state = bridge.load_playback()
        state["position"] = 30.0
        bridge.save_playback(state)
        self.age_last_push(600)                     # ...and then the machine slept
        self.other_device(EP_1, 60)
        before = len(self.pushes(EP_1))
        run_bridge("player")
        self.assertEqual(self.pushes(EP_1)[before:], [])
        self.assertEqual(self.fake["progress"][EP_1], 60)

    def test_a_skip_while_paused_never_pushes_an_old_position(self):
        self.play_then_pause()
        self.other_device(EP_1, 60)  # listened on, on the phone
        self.age_last_push(600)
        before = len(self.pushes(EP_1))
        run_bridge("seek", "--relative", "--", "-10")  # back here: skip back first
        self.assertEqual(self.pushes(EP_1)[before:], [])
        self.assertEqual(self.fake["progress"][EP_1], 60)
        run_bridge("resume")  # the resume asks, and the phone's place wins
        self.wait_for(lambda: self.position() >= 59)

    def test_a_skip_right_after_pausing_is_sent(self):
        self.play_then_pause()
        before = len(self.pushes(EP_1))
        run_bridge("seek", "20")
        sent = [b["position"] for b in self.pushes(EP_1)[before:]]
        self.assertEqual(len(sent), 1)
        self.assertIn(sent[0], (19, 20))  # mpv reads 19.98 right after the seek

    def test_stop_and_switching_never_push_a_position_unsent_before_sleep(self):
        self.play_then_pause()
        with bridge.Mpv.connect() as player:
            player.command("seek", 30, "absolute")  # moved while paused, never sent...
        self.age_last_push(600)                     # ...and then the machine slept
        self.other_device(EP_1, 60)
        before = len(self.pushes(EP_1))
        run_bridge("play", EP_3, "--podcast", PODCAST_B)
        run_bridge("stop")
        self.assertEqual(self.pushes(EP_1)[before:], [])
        self.assertEqual(self.fake["progress"][EP_1], 60)

    def test_pausing_a_resume_pocket_casts_never_confirmed_pushes_nothing(self):
        self.play_then_pause()
        self.age_last_push(600)
        self.fake["fail"] = {"/up_next/list": 1}  # the resume can't ask
        self.assertTrue(run_bridge("resume")["data"]["playing"])
        self.other_device(EP_1, 60)
        before = len(self.pushes(EP_1))
        run_bridge("pause")
        run_bridge("stop")
        self.assertEqual(self.pushes(EP_1)[before:], [])
        self.assertEqual(self.fake["progress"][EP_1], 60)

    def test_an_unconfirmed_resume_pushes_nothing_even_soon_after_a_pause(self):
        # Review finding: within 90 s of the last push, the paused rule let
        # a pause push a position Pocket Casts never confirmed.
        self.play_then_pause()
        self.fake["fail"] = {"/up_next/list": 1000}  # the network is down: nothing can ask
        start = self.position()
        self.assertTrue(run_bridge("resume")["data"]["playing"])
        self.wait_for(lambda: self.position() >= start + 1.5)  # it plays on here a little
        self.other_device(EP_1, 60)
        before = len(self.pushes(EP_1))
        run_bridge("pause")      # a pause soon after, by this panel
        self.mpv_set_pause(False)
        self.mpv_set_pause(True)  # and one by a media key
        run_bridge("player")
        run_bridge("stop")
        self.assertEqual([b for b in self.pushes(EP_1)[before:] if b["uuid"] == EP_1], [])
        self.assertEqual(self.fake["progress"][EP_1], 60)

    def test_a_hanging_network_holds_up_play_only_briefly(self):
        # Nine Point Labs' review of the same check upstream: two requests at
        # the full HTTP timeout could keep Play silent for 30 s. The check
        # gets its own short limit (cut to 1 s here; the answer takes 4).
        self.play_then_pause()
        self.fake["slow"] = {"/up_next/list": 4}
        usual = bridge.HTTP_TIMEOUT
        with mock.patch.object(bridge, "RESUME_CHECK_TIMEOUT", 1):
            started = time.monotonic()
            self.assertTrue(run_bridge("resume")["data"]["playing"])
            self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(bridge.load_playback().get("unconfirmed"))  # and nothing is pushed until it answers
        self.assertEqual(bridge.HTTP_TIMEOUT, usual)  # back to normal for everything else

    def test_both_of_plays_requests_are_held_to_the_short_limit(self):
        # Strict review 4: the episode's own record, the check's second
        # request, hanging too.
        self.play_then_pause()
        self.fake["slow"] = {"/user/episode": 4}
        with mock.patch.object(bridge, "RESUME_CHECK_TIMEOUT", 1):
            started = time.monotonic()
            self.assertTrue(run_bridge("resume")["data"]["playing"])
            self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(bridge.load_playback().get("unconfirmed"))

    def test_the_check_during_playback_waits_the_full_timeout(self):
        # Review finding: the short limit is for a press of Play only. A poll's
        # check (a media key resumed it) on a slow link must still get its
        # answer, or nothing is pushed for the whole session.
        self.play_then_pause()
        self.fake["slow"] = {"/up_next/list": 2}
        with mock.patch.object(bridge, "RESUME_CHECK_TIMEOUT", 1):
            self.mpv_set_pause(False)  # a media key
            run_bridge("player")
        state = bridge.load_playback()
        self.assertFalse(state.get("unconfirmed"))
        self.assertFalse(state.get("checkServer"))

    def test_a_sign_in_refresh_isnt_cut_short_by_the_quick_check(self):
        # Prediction of the marketplace reviewer: a token refresh inside the
        # short limit could be dropped after Pocket Casts already rotated the
        # refresh token. It runs first, at the usual timeout.
        self.play_then_pause()
        auth = bridge.load_auth()
        auth["expires_at"] = time.time() - 10  # due for a refresh
        bridge.save_auth(auth)
        self.fake["slow"] = {"/user/token": 2}
        with mock.patch.object(bridge, "RESUME_CHECK_TIMEOUT", 1):
            self.assertTrue(run_bridge("resume")["data"]["playing"])
        self.assertEqual(bridge.load_auth()["access_token"], "t2")
        self.assertFalse(bridge.load_playback().get("unconfirmed"))  # and the check got its answer

    def test_a_rejected_token_inside_the_quick_check_refreshes_at_full_time(self):
        # Strict review SR4: a 401 inside the short limit refreshed under it,
        # which could lose a rotated refresh token. The refresh has its own
        # timeout.
        self.play_then_pause()
        auth = bridge.load_auth()
        auth["access_token"] = "stale"  # not expired by the clock, refused by the server
        auth["expires_at"] = time.time() + 3000
        bridge.save_auth(auth)
        self.fake["slow"] = {"/user/token": 2}
        with mock.patch.object(bridge, "RESUME_CHECK_TIMEOUT", 1):
            self.assertTrue(run_bridge("resume")["data"]["playing"])
        self.assertEqual(bridge.load_auth()["access_token"], "t2")
        self.assertFalse(bridge.load_playback().get("unconfirmed"))

    def test_play_waits_five_seconds_at_most_per_request(self):
        self.assertLessEqual(bridge.RESUME_CHECK_TIMEOUT, 5)
        self.assertEqual(bridge.TOKEN_TIMEOUT, 15)  # a sign-in refresh is never cut short

    def test_once_pocket_casts_answers_pushes_resume(self):
        self.play_then_pause()
        self.fake["fail"] = {"/up_next/list": 1}
        run_bridge("resume")                      # unconfirmed...
        self.assertIs(bridge.load_playback().get("unconfirmed"), True)
        run_bridge("player")                      # ...the next poll asks, and it answers
        self.assertFalse(bridge.load_playback().get("unconfirmed"))
        before = len(self.pushes(EP_1))
        run_bridge("pause")
        self.assertEqual(len(self.pushes(EP_1)[before:]), 1)

    def test_a_seek_meant_for_another_episode_is_dropped(self):
        # Review finding: a gathered seek fired after Next landed on the
        # next episode. The panel names the episode; the bridge checks it.
        self.play_then_pause()
        at = self.position()
        before = len(self.pushes(EP_1))
        view = run_bridge("seek", "--episode", EP_2, "--relative", "--", "30")["data"]
        self.assertLess(abs(view["position"] - at), 1)
        self.assertEqual(self.pushes(EP_1)[before:], [])
        view = run_bridge("seek", "--episode", EP_1, "20")["data"]  # meant for this one: it lands
        self.assertGreaterEqual(view["position"], 19)

    def test_a_stopped_player_skips_an_episode_finished_elsewhere(self):
        self.play_then_pause()
        run_bridge("stop")
        self.other_device(EP_1, 0, bridge.STATUS_PLAYED)
        self.fake["upnext"] = [EP_2]
        self.other_device(EP_2, 20)
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_2)
        self.wait_for(lambda: self.position() >= 19)
        self.assertNotIn(EP_1, self.fake["upnext"])
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)


@NEEDS_PLAYER
class TrimSilence(PlayerTestCase):
    """Trim Silence cuts the pauses but keeps positions in the episode's own
    time, so what's pushed to Pocket Casts is still right."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.audio = make_gapped_audio()

    def setUp(self):
        super().setUp()
        for episode in self.fake["episodes"].values():
            episode["duration"] = 7

    def af(self):
        with bridge.Mpv.connect() as player:
            return [f.get("label") for f in (player.get("af") or [])]

    def test_mad_max_skips_the_gaps_and_keeps_episode_time(self):
        self.login()
        self.assertEqual(run_bridge("trim", "madmax")["data"]["trim"], "madmax")
        self.fake["upnext"] = [EP_1]
        started = time.monotonic()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertIn("trim", self.af())
        # Past the first gap in well under its real length: time jumped it.
        position = self.wait_for(lambda: (lambda v: v if v >= 3 else None)(run_bridge("player")["data"]["position"]))
        self.assertLess(time.monotonic() - started, 3.5)
        self.assertLessEqual(position, 7.2)
        # Played to its end (marked played) in far less than 7 s.
        # (The panel polls on mpv's end-of-file event; here the test polls.)
        self.wait_for(lambda: run_bridge("player") and self.fake["status"].get(EP_1) == bridge.STATUS_PLAYED)
        self.assertLess(time.monotonic() - started, 5.5)
        self.assertEqual(run_bridge("player")["data"]["trim"], "madmax")
        # The two 2 s gaps, cut: counted as Trim Silence's time saved.
        self.assertGreater(run_bridge("stats")["data"]["trim"], 2.5)

    def test_boost_toggles_live_and_stays_after_trim(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertTrue(run_bridge("boost", "toggle")["data"]["boost"])
        self.assertEqual(self.af(), ["boost"])
        run_bridge("trim", "mild")
        self.assertEqual(self.af(), ["trim", "boost"])  # trim judges silence before the boost
        run_bridge("trim", "madmax")
        self.assertEqual(self.af(), ["trim", "boost"])
        self.assertTrue(run_bridge("player")["data"]["boost"])
        self.assertFalse(run_bridge("boost", "off")["data"]["boost"])
        self.assertEqual(self.af(), ["trim"])
        self.assertIs(bridge.load_prefs()["boost"], False)

    def test_a_poll_puts_lost_filters_back(self):
        self.login()
        run_bridge("trim", "madmax")
        run_bridge("boost", "on")
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertEqual(self.af(), ["trim", "boost"])
        with bridge.Mpv.connect() as player:  # as an mpv key or a lost command might
            player.command("af", "remove", "@trim")
        self.assertEqual(self.af(), ["boost"])
        run_bridge("player")
        self.assertEqual(self.af(), ["trim", "boost"])

    def test_trim_changes_live_and_cycles(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertNotIn("trim", self.af())
        self.assertEqual(run_bridge("trim", "cycle")["data"]["trim"], "mild")
        self.assertIn("trim", self.af())
        self.assertEqual(run_bridge("trim", "cycle")["data"]["trim"], "medium")
        self.assertEqual(self.af().count("trim"), 1)  # swapped, not stacked
        run_bridge("trim", "cycle")
        self.assertEqual(run_bridge("trim", "cycle")["data"]["trim"], "off")
        self.assertNotIn("trim", self.af())
        self.assertFalse(run_bridge("trim", "loud")["ok"])
        self.assertEqual(bridge.load_prefs()["trim"], "off")


@NEEDS_PLAYER
class VideoWindow(PlayerTestCase):
    """The picture in picture, against mpv's null video output; the
    Hyprland calls are recorded, never sent."""

    AUDIO_SECONDS = 30

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.video = make_video(30)

    def setUp(self):
        super().setUp()
        self.fake["media"] = {EP_3: self.video}
        for episode in self.fake["episodes"].values():
            episode["duration"] = 30
        self.hypr = []
        for name, value in (("MPV_EXTRA_ARGS", ("--ao=null", "--vo=null")),
                            ("hyprctl", lambda *args: self.hypr.append(args) or "")):
            patcher = mock.patch.object(bridge, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def af(self):
        with bridge.Mpv.connect() as player:
            return [f.get("label") for f in (player.get("af") or [])]

    def test_video_choices_touch_hyprland_only_while_the_window_shows(self):
        # Strict review 11 (fit L2): the Settings page's switches sent the
        # window rules and the window.open hook with no window, no player.
        run_bridge("videotransparency", "30")
        run_bridge("videopin", "toggle")
        self.assertEqual(self.hypr, [])
        prefs = bridge.load_prefs()
        self.assertEqual((prefs["videoTransparency"], prefs["videoPinned"]), (30, False))  # kept for later

    def test_the_window_rule_goes_out_before_the_next_episode_loads(self):
        # Strict review 13 (fit B3): with the video on, mpv opens the next
        # episode's window by itself, and a Hyprland reload since drops the
        # runtime rules: they're sent again before each load.
        self.play(EP_3, PODCAST_B)
        self.assertTrue(run_bridge("video", "on")["ok"])
        self.hypr.clear()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        rules = [a for a in self.hypr if a[0] == "repl"]
        self.assertTrue(rules and 'class = "^legato-video$"' in rules[0][1], self.hypr)

    def test_polls_ask_hyprland_nothing_without_the_video(self):
        # Strict review 11 (fit L7): only a shown window's place is read.
        self.play(EP_1, PODCAST_A)
        self.hypr.clear()
        for _ in range(3):
            run_bridge("player")
        self.assertEqual([a for a in self.hypr if a[:1] == ("clients",)], [])

    def play(self, uuid, podcast):
        self.login()
        run_bridge("play", uuid, "--podcast", podcast)
        return self.wait_for(lambda: (lambda v: v if v["position"] > 0.3 else None)(run_bridge("player")["data"]))

    def test_show_and_hide_the_video_of_a_video_episode(self):
        run_bridge("trim", "mild")
        view = self.play(EP_3, PODCAST_B)
        self.assertTrue(view["hasVideo"])
        self.assertFalse(view["video"])
        self.assertIn("trim", self.af())

        shown = run_bridge("video", "on")
        self.assertTrue(shown["ok"], shown)
        self.assertTrue(shown["data"]["video"])
        self.assertTrue(shown["data"]["playing"])
        self.assertIn("trim", self.af())  # trimming carries on with the picture
        rule = [a for a in self.hypr if a[0] == "repl"]
        self.assertTrue(rule and 'class = "^legato-video$"' in rule[-1][1]
                        and 'name = "legato-video", float = true, pin = true' in rule[-1][1])
        self.assertEqual(run_bridge("trim", "medium")["data"]["trim"], "medium")
        self.assertIn("trim", self.af())
        with bridge.Mpv.connect() as player:
            self.assertFalse(player.get("osc"))  # just the picture, no controls

        hidden = run_bridge("video", "toggle")["data"]
        self.assertFalse(hidden["video"])
        self.assertTrue(hidden["playing"])
        self.assertIn("trim", self.af())
        self.assertIn(("clients", "-j"), self.hypr)  # where it was, for next time

        # Always on top, from the window's right-click menu (shown, then).
        hyprland = lambda: [a for a in self.hypr if a[0] in ("repl", "dispatch")]
        hidden = len(hyprland())
        run_bridge("videotransparency", "0")  # hidden: kept, no rules (they go out when it shows)
        run_bridge("videopin", "toggle")
        run_bridge("videopin", "toggle")
        self.assertEqual(len(hyprland()), hidden)
        run_bridge("video", "on")
        rules_before = len([a for a in self.hypr if a[0] == "repl"])
        self.assertFalse(run_bridge("videopin", "toggle")["data"]["videoPinned"])
        self.assertEqual(len([a for a in self.hypr if a[0] == "repl"]), rules_before + 1)  # the rules go out again
        self.assertIs(bridge.load_prefs()["videoPinned"], False)
        dispatch = [a for a in self.hypr if a[0] == "dispatch"][-1][1]
        self.assertEqual(dispatch, 'hl.dsp.window.pin({ action = "off", window = "class:^legato-video$" })')
        self.assertIn('float = true, pin = false', [a for a in self.hypr if a[0] == "repl"][-1][1])
        # The tag rules go out with it (they follow the window's real pin),
        # before the pin, so windows opened later have them already.
        self.assertIn('tag = "-skip-taskbar"', [a for a in self.hypr if a[0] == "repl"][-1][1])
        order = [a[0] for a in self.hypr if a[0] in ("repl", "dispatch")]
        self.assertEqual(order[-2:], ["repl", "dispatch"])
        with bridge.Mpv.connect() as player:
            self.assertEqual(player.get("menu-data")[0]["title"], "Always on top: Off")
        run_bridge("video", "on")
        self.assertIn('float = true, pin = false', [a for a in self.hypr if a[0] == "repl"][-1][1])
        self.assertIn('legato_video_alpha = "1.00"', [a for a in self.hypr if a[0] == "repl"][-1][1])

        # Transparency, from the menu or the Settings page.
        self.assertEqual(run_bridge("videotransparency", "30")["data"]["videoTransparency"], 30)
        self.assertEqual(bridge.load_prefs()["videoTransparency"], 30)
        self.assertIn('legato_video_alpha = "0.70"', [a for a in self.hypr if a[0] == "repl"][-1][1])
        with bridge.Mpv.connect() as player:
            menu = player.get("menu-data")
        self.assertEqual(menu[1]["title"], "Transparency: 30%")
        self.assertIn({"title": "30% (current)", "cmd": "script-message legato-video-transparency 30"},
                      menu[1]["submenu"])
        self.assertEqual(run_bridge("player")["data"]["videoTransparency"], 30)
        run_bridge("video", "off")
        run_bridge("video", "on")  # a new window opens see-through too
        self.assertIn('legato_video_alpha = "0.70"', [a for a in self.hypr if a[0] == "repl"][-1][1])
        with mock.patch.object(sys, "stderr", io.StringIO()):
            for bad in ("35", "90", "-10", "x"):
                with self.assertRaises(SystemExit):
                    run_bridge("videotransparency", bad)
        self.assertEqual(bridge.load_prefs()["videoTransparency"], 30)

    def test_a_window_that_missed_the_rule_is_not_remembered(self):
        prefs = {"videoGeometry": {"x": 924, "y": 630, "w": 274, "h": 144}}
        big = [{"class": "legato-video", "pinned": False, "at": [200, 130], "size": [768, 544]}]
        with mock.patch.object(bridge, "hyprctl", lambda *a: json.dumps(big)):
            bridge.remember_video_geometry(prefs)
        self.assertEqual(prefs["videoGeometry"]["w"], 274)
        moved = [{"class": "legato-video", "pinned": True, "at": [900, 600], "size": [300, 170]}]
        with mock.patch.object(bridge, "hyprctl", lambda *a: json.dumps(moved)):
            bridge.remember_video_geometry(prefs)
        self.assertEqual(prefs["videoGeometry"], {"x": 900, "y": 600, "w": 300, "h": 170})

    def test_closing_the_video_window_never_quits_the_player(self):
        self.play(EP_3, PODCAST_B)
        with bridge.Mpv.connect() as player:
            bindings = {b.get("key"): b.get("cmd") for b in (player.get("input-bindings") or [])
                        if b.get("section") == "default" and b.get("priority", 0) >= 0}
        for key in ("CLOSE_WIN", "q", "Q"):
            self.assertEqual(bindings.get(key), "set vid no", key)
        # Legato's keys, not mpv's, in the video window.
        self.assertEqual(bindings.get("SPACE"), "script-message legato-key playPause")
        self.assertEqual(bindings.get("p"), "script-message legato-key cycleSpeed")
        self.assertEqual(bindings.get("WHEEL_UP"), "script-message legato-key volumeUp")
        self.assertEqual(bindings.get("LEFT"), "script-message legato-key skipBack")
        with bridge.Mpv.connect() as player:
            self.assertIs(player.get("input-default-bindings"), False)
            speed, mute = player.get("speed"), player.get("mute")
            for key in ("]", "m", "i", "ESC"):  # mpv's: faster, mute, stats, fullscreen
                player.command("keypress", key)
            time.sleep(0.3)
            self.assertEqual((player.get("speed"), player.get("mute")), (speed, mute))
        # mpv's menu on Linux is its context_menu script; the context-menu
        # command only opens native menus (Windows, macOS) and did nothing.
        self.assertEqual(bindings.get("MBTN_RIGHT"), "script-message-to context_menu open")
        with bridge.Mpv.connect() as player:
            menu = player.get("menu-data")
        self.assertEqual(menu[0]["title"], "Always on top: On")
        self.assertEqual(menu[1]["title"], "Transparency: Off")
        self.assertEqual([i["title"] for i in menu[1]["submenu"]],
                         ["Off (current)", "10%", "20%", "30%", "40%", "50%", "60%", "70%", "80%"])
        with bridge.Mpv.connect() as player:
            self.assertFalse(player.get("osd-scale-by-window"))  # full-size text in a small window
        self.assertEqual(menu[0]["cmd"], "script-message legato-video-pin toggle")

    def test_a_key_in_the_video_window_reaches_legato(self):
        self.play(EP_3, PODCAST_B)
        listener = socket.socket(socket.AF_UNIX)
        listener.connect(bridge.socket_path())
        listener.settimeout(3)
        try:
            with bridge.Mpv.connect() as player:
                player.command("keypress", "SPACE")
            seen, buffer = None, b""
            deadline = time.monotonic() + 3
            while seen is None and time.monotonic() < deadline:
                buffer += listener.recv(65536)
                for line in buffer.split(b"\n"):
                    event = json.loads(line) if line.strip().startswith(b"{") else {}
                    if event.get("event") == "client-message":
                        seen = event.get("args")
            self.assertEqual(seen, ["legato-key", "playPause"])
            with bridge.Mpv.connect() as player:
                self.assertIs(player.get("pause"), False)  # only Legato pauses, through the bridge
        finally:
            listener.close()

    def test_an_audio_episode_has_no_video_to_show(self):
        view = self.play(EP_1, PODCAST_A)
        self.assertFalse(view["hasVideo"])
        result = run_bridge("video", "on")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "no_video")


@NEEDS_PLAYER
class ShowSkips(PlayerTestCase):
    """A show's skip-intro and skip-outro, set in any Pocket Casts app."""

    AUDIO_SECONDS = 30

    def setUp(self):
        super().setUp()
        for episode in self.fake["episodes"].values():
            episode["duration"] = 30

    def position(self):
        return run_bridge("player")["data"]["position"]

    def test_a_fresh_episode_starts_past_the_intro(self):
        self.fake["showSettings"] = {PODCAST_A: {"autoStartFrom": 12, "autoSkipLast": 0}}
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.assertGreaterEqual(self.wait_for(lambda: (lambda p: p if p >= 12 else None)(self.position())), 12)
        self.assertEqual(self.writes("/sync/update_episode")[-1]["position"], 12)
        self.assertEqual(run_bridge("stats")["data"]["intro"], 12)

    def test_an_episode_in_progress_resumes_where_it_was(self):
        self.fake["showSettings"] = {PODCAST_A: {"autoStartFrom": 12, "autoSkipLast": 0}}
        self.fake["progress"][EP_1] = 5
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: self.position() > 5.2)
        self.assertLess(self.position(), 11)
        self.assertEqual(run_bridge("stats")["data"]["intro"], 0)  # nothing skipped, nothing saved

    def test_play_from_start_means_the_start(self):
        self.fake["showSettings"] = {PODCAST_A: {"autoStartFrom": 12, "autoSkipLast": 0}}
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A, "--from-start")
        self.wait_for(lambda: self.position() > 0.3)
        self.assertLess(self.position(), 5)

    def test_the_outro_ends_an_episode_on_a_host_without_ranges_too(self):
        # Strict review 8: read straight through, the stop the outro makes
        # isn't at the size; it is the end.
        self.fake["noranges"] = {EP_1}
        self.fake["showSettings"] = {PODCAST_A: {"autoStartFrom": 0, "autoSkipLast": 22}}
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: (lambda v: v if v.get("streamBroke") or v.get("ended") or (v["item"] or {}).get("uuid") != EP_1
                                else None)(run_bridge("player")["data"]), timeout=30)
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_the_outro_is_skipped_and_the_episode_ends_there(self):
        self.fake["showSettings"] = {PODCAST_A: {"autoStartFrom": 0, "autoSkipLast": 26}}
        self.login()
        started = time.monotonic()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        # 30 s of audio, the last 26 skipped: over after about 4 s, marked
        # played, and Up Next moves on.
        view = self.wait_for(lambda: (lambda v: v if v["item"] and v["item"]["uuid"] == EP_2 else None)(run_bridge("player")["data"]))
        self.assertLess(time.monotonic() - started, 9)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)
        self.assertEqual(view["item"]["uuid"], EP_2)
        stats = run_bridge("stats")["data"]
        self.assertEqual((stats["outro"], stats["finished"]), (26, 1))


@NEEDS_PLAYER
class BrokenStream(PlayerTestCase):
    """The stream stops part way through an episode (the network went, the
    host hung up). mpv retries, gives up, and sits where it got to with
    `eof-reached` on, just as at a real end. That's not finishing it: it
    stays in progress and on Up Next, and the next play carries on."""

    AUDIO_SECONDS = 30

    def setUp(self):
        super().setUp()
        for episode in self.fake["episodes"].values():
            episode["duration"] = self.AUDIO_SECONDS

    def break_stream_and_wait(self, at=0.2):
        # A break at a fifth (about 6 s of 30) is also "far short of the
        # listed length" (end_unproven); tests of the break evidence itself
        # break past half, at double speed.
        if at > 0.5:
            bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.fake["cut"] = {EP_1: int(len(self.audio) * at)}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        return self.wait_for(lambda: (lambda v: v if v.get("streamBroke") or v.get("ended")
                                      or (v["item"] or {}).get("uuid") != EP_1 else None)(run_bridge("player")["data"]),
                             timeout=30)

    def test_a_stream_that_breaks_part_way_is_not_finished(self):
        view = self.break_stream_and_wait()
        self.assertTrue(view.get("streamBroke"))
        self.assertFalse(view["active"])
        self.assertFalse(self.mpv_running())
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)  # still on Up Next, and nothing else started
        pushed = [b for b in self.writes("/sync/update_episode") if b["uuid"] == EP_1]
        self.assertTrue(3 < pushed[-1]["position"] < 9)  # where it stopped, in progress
        self.assertEqual(pushed[-1]["status"], bridge.STATUS_IN_PROGRESS)
        self.assertFalse(view.get("nothingMore"))  # it got somewhere: no advice to mark it played
        self.assertFalse(bridge.load_playback().get("unsentPush"))  # Pocket Casts has it
        # Reported once; the next poll is quiet.
        self.assertFalse(run_bridge("player")["data"].get("streamBroke"))

    def playing_past(self, position):
        """A player that's really playing this episode, past `position` (not
        a closed one's stored position)."""
        return self.wait_for(lambda: (lambda v: v if v["active"] and v["playing"] and v["item"]["uuid"] == EP_1
                                      and v["position"] > position + 1 else None)(run_bridge("player")["data"]),
                             timeout=15)

    def test_play_after_a_broken_stream_carries_on_from_there(self):
        self.break_stream_and_wait()
        broke_at = bridge.load_playback()["position"]
        self.fake["cut"] = {}  # the network is back
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.playing_past(broke_at)
        self.assertTrue(self.mpv_running())

    def test_after_a_break_that_was_sent_a_rewind_on_the_phone_wins(self):
        # Rule 2 after a break whose push went through: Pocket Casts' answer
        # wins, even when it's behind (you went back on the phone).
        view = self.break_stream_and_wait()
        self.assertTrue(view.get("streamBroke"))
        self.fake["cut"] = {}
        self.fake["progress"][EP_1] = 2
        self.assertLess(run_bridge("toggle")["data"]["position"], 4)

    def error_page_break(self, code):
        # Strict review 4: the ordinary host (size, byte ranges), up but
        # failing: mpv's reconnect gets an error page, whose length FFmpeg
        # takes for the file's size. Not the end.
        self.fake["cutReply"] = code
        view = self.break_stream_and_wait(at=0.6)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)

    def test_a_break_answered_by_a_503_page_is_not_the_end(self):
        self.error_page_break(503)

    def test_a_break_answered_by_a_403_page_is_not_the_end(self):
        self.error_page_break(403)

    def load_at(self, position, seconds=40):
        self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=%d" % seconds, "-b:a", "320k"], ".mp3")}
        for episode in self.fake["episodes"].values():
            episode["duration"] = seconds
        self.fake["progress"][EP_1] = position
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: (lambda v: v if v["active"] and v["playing"] and v["position"] > position + 1 else None)(
            run_bridge("player")["data"]), timeout=20)

    def test_a_failed_seek_is_not_the_end(self):
        # Strict review 8: resumed at 30 s, nothing before it is cached; the
        # link expires (403) and you skip back: mpv's seek needs a new
        # request, which fails, and FFmpeg logs only "HTTP error 403".
        self.load_at(30)
        self.fake["expired"] = 403
        run_bridge("seek", "--episode", EP_1, "--relative", "--", "-8")
        time.sleep(3)
        for _ in range(3):
            run_bridge("player")
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertIn(EP_1, self.fake["upnext"])

    def test_a_failed_seek_from_the_resume_check_is_not_the_end(self):
        self.load_at(30)
        run_bridge("pause")
        self.fake["progress"][EP_1] = 24  # the phone went back
        self.fake["expired"] = 403
        run_bridge("toggle")
        time.sleep(3)
        for _ in range(3):
            run_bridge("player")
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_a_seek_within_whats_arrived_keeps_the_breaks_evidence(self):
        # The cut is logged as the cache fills; a seek back inside what has
        # arrived, then playback reaches the break: still a break.
        self.fake["cut"] = {EP_1: int(len(self.audio) * 0.6)}
        bridge.save_prefs({"volume": 0, "speed": 1.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        with bridge.Mpv.connect() as player:
            self.wait_for(lambda: isinstance((player.get("user-data/legato") or {}).get("cut"), (int, float)), timeout=20)
            self.wait_for(lambda: (player.get("time-pos") or 0) > 3, timeout=20)
            # FFmpeg has given up (its reconnects log the cut again while they
            # last, about 9 s here): from here only the watcher's record says
            # it broke. At 1x the cut (18 s in) is still ahead; at the cut mpv
            # would pause itself, and a seek back leaves it paused.
            self.wait_for(lambda: (player.get("demuxer-cache-state") or {}).get("eof") is True, timeout=30)
            self.assertFalse(player.get("eof-reached"), "playback reached the cut before FFmpeg gave up")
        run_bridge("seek", "--episode", EP_1, "--relative", "--", "-2")
        view = self.settled(EP_1)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_a_break_a_second_after_a_resume_says_stream_dropped(self):
        # Strict review 8: "Stream ends here: mark it played" is for the same
        # spot twice in a row, not a link that dropped right after a resume.
        blob = encode(["-f", "lavfi", "-i", "sine=duration=40", "-b:a", "320k"], ".mp3")
        for episode in self.fake["episodes"].values():
            episode["duration"] = 40
        self.fake["media"] = {EP_1: blob}
        self.fake["progress"][EP_1] = 30
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.fake["cut"] = {EP_1: int(len(blob) * 30.8 / 40)}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.settled(EP_1)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertFalse(view.get("nothingMore"))

    def test_an_hls_episode_whose_segments_stop_is_not_finished(self):
        # Strict review 7: a playlist of segments has no one stream to
        # measure; its playlist's exact durations judge it.
        self.fake["hls"] = make_hls(30)
        self.fake["hlsCutAt"] = 6  # about 18 s of 30 arrive: past half, so the length rule alone decides
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.fake["episodes"][EP_1]["url"] = self.base + "/hls/%s/out.m3u8" % EP_1
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.settled(EP_1, timeout=60)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_an_hls_episode_whose_segments_come_back_empty_is_not_finished(self):
        # No network error at all: only the playlist's exact length tells.
        self.fake["hls"] = make_hls(30)
        self.fake["hlsCutAt"] = 6
        self.fake["hlsEmpty"] = True
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.fake["episodes"][EP_1]["url"] = self.base + "/hls/%s/out.m3u8" % EP_1
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.settled(EP_1, timeout=60)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_an_hls_break_in_its_last_tenth_isnt_the_end(self):
        # Strict review 13 (L2): a playlist's durations are exact, so the
        # length rule's 10% margin (for misread MP3s) marked a break at 183 s
        # of 200 played everywhere.
        self.fake["hls"] = make_hls(200)
        self.fake["hlsCutAt"] = 61  # segments of 3 s: 183 s arrive
        self.fake["episodes"][EP_1].update(duration=200, url=self.base + "/hls/%s/out.m3u8" % EP_1)
        self.fake["progress"][EP_1] = 170
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.settled(EP_1, timeout=60)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_a_rewind_past_the_back_buffer_on_a_host_without_ranges_is_followed(self):
        # Strict review 13 (L1): the resume check's seek back to the phone's
        # place was refused (no byte ranges, and mpv no longer held it), mpv
        # played on from where it was, and the next push sent that over the
        # phone. Loaded again from Pocket Casts' place instead.
        extra = ("--ao=null", "--demuxer-max-back-bytes=4KiB", "--demuxer-max-bytes=64KiB")
        with mock.patch.object(bridge, "MPV_EXTRA_ARGS", extra):
            self.fake["noranges"] = {EP_1}
            self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=90", "-c:a", "libmp3lame",
                                                "-b:a", "64k"], ".mp3")}
            self.fake["episodes"][EP_1]["duration"] = 90
            self.login()
            self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
            self.wait_for(lambda: run_bridge("player")["data"]["position"] > 12, timeout=30)
            run_bridge("pause")
            self.fake["progress"][EP_1] = 2  # the phone went back, well behind
            state = bridge.load_playback()
            state["lastSyncAt"] -= 120
            bridge.save_playback(state)
            run_bridge("toggle")
            time.sleep(1.5)
            self.assertLess(run_bridge("player")["data"]["position"], 8)
            state = bridge.load_playback()
            state["lastSyncAt"] -= 31
            bridge.save_playback(state)
            run_bridge("player")  # the periodic push
            self.assertLess(self.fake["progress"][EP_1], 8, [b["position"] for b in self.pushes_of(EP_1)])

    def test_an_hls_episode_still_ends_properly(self):
        self.fake["hls"] = make_hls(30)
        self.fake["episodes"][EP_1]["url"] = self.base + "/hls/%s/out.m3u8" % EP_1
        self.fake["progress"][EP_1] = 26
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.settled(EP_1, timeout=60)
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_an_end_reached_at_once_proves_nothing(self):
        # Strict review 7: Pocket Casts' position is past the end of this
        # machine's copy (ad-stitched copies differ per request): it ends the
        # moment it loads. Not marked played; it says the stream ends there.
        self.fake["episodes"][EP_1]["duration"] = 40
        self.fake["progress"][EP_1] = 35
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.settled(EP_1)
        self.assertTrue(view.get("nothingMore"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)

    def test_an_end_far_short_of_the_listed_length_proves_nothing(self):
        # A placeholder clip from an expired feed: 30 s where Pocket Casts
        # lists ten minutes. Not played, and nothing autoplays through it.
        self.fake["episodes"][EP_1]["duration"] = 600
        bridge.save_prefs({"volume": 0, "speed": 3.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.settled(EP_1)
        self.assertTrue(view.get("nothingMore"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_failing_pushes_are_said_once(self):
        # Strict review 7: Pocket Casts down mid-episode: the polls answered
        # "ok" and nothing was ever shown.
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 1)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        said = []

        def poll(due):
            if due:
                state = bridge.load_playback()
                state["lastSyncAt"] = time.time() - 31
                bridge.save_playback(state)
            said.append(bool(run_bridge("player")["data"].get("syncFailed")))
        # Polls that push (and fail), and polls between them that don't push
        # (an mpv event's): said once, in the poll whose push made it two.
        for due in (True, False, True, False, False, True):
            poll(due)
        self.assertEqual(said, [False, False, True, False, False, False])
        # A push that works resets the count: the next run of failures is
        # said again.
        self.fake["fail"] = {}
        poll(True)
        self.fake["fail"] = {"/sync/update_episode": 1000}
        del said[:]
        for _ in range(2):
            time.sleep(1.2)  # a position that hasn't moved isn't pushed at all
            poll(True)
        self.assertEqual(said, [False, True])
        self.fake["fail"] = {}

    def test_a_notification_starting_with_a_dash_is_text(self):
        # Through the argument parser, as the panel sends it: after `--`.
        sent = []
        with mock.patch.object(bridge, "send_notification", lambda text: sent.append(text) or True):
            self.assertEqual(bridge.main(["notify", "--", "-x"]), 0)
        self.assertEqual(sent, ["-x"])

    def test_a_break_near_the_end_is_still_a_break(self):
        # Within the last tenth, where the episode's length alone would say
        # "the end": only the watcher's evidence tells the break.
        self.fake["cut"] = {EP_1: int(len(self.audio) * 0.92)}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.settled(EP_1)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertGreater(view["position"], 25)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)

    def test_a_break_on_a_sized_host_without_ranges_is_not_the_end(self):
        # Strict review 4: such a host keeps its size after a break (FFmpeg
        # can't reconnect), and an ad-stitched MP3's duration is misread.
        media = make_stitched_mp3()
        self.fake["media"] = {EP_1: media}
        self.fake["episodes"][EP_1]["duration"] = 60
        self.fake["noranges"] = {EP_1}
        self.fake["cut"] = {EP_1: int(len(media) * 0.75)}
        self.fake["rate"] = 40000
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.settled(EP_1, timeout=60)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)

    def test_an_ad_stitched_mp3_still_ends_properly(self):
        # The same misread file played to its real end: the end.
        self.fake["media"] = {EP_1: make_stitched_mp3()}
        self.fake["episodes"][EP_1]["duration"] = 60
        self.fake["progress"][EP_1] = 56
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.settled(EP_1, timeout=40)
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_a_break_past_the_listed_length_then_play_never_rewinds(self):
        # Strict review 4: files run longer than listed (ads inserted on the
        # fly). Play after a break past the listed length used to start from
        # the top ("at the end means from the top") and push 0 everywhere.
        media = make_audio(40)
        self.fake["media"] = {EP_1: media}
        self.fake["episodes"][EP_1]["duration"] = 30
        self.fake["progress"][EP_1] = 25
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.fake["cut"] = {EP_1: int(len(media) * 0.85)}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assertTrue(self.settled(EP_1, timeout=40).get("streamBroke"))
        self.fake["cut"] = {}  # the network is back
        view = run_bridge("toggle")["data"]
        self.assertGreater(view["position"], 30)
        time.sleep(1)
        self.assertGreater(self.fake["progress"][EP_1], 30)
        self.assertGreater(min(b["position"] for b in self.pushes_of(EP_1)), 24)

    def test_a_skip_outro_show_with_a_misread_mp3_plays_on(self):
        # Strict review 4 (and 1.0.2): the outro is counted back from mpv's
        # duration, misread at 18 s of 60: a 20 s outro ended it at once and
        # it was marked played, and so was the show's next episode; a 10 s one
        # would end it at 8 s. The outro isn't applied when mpv's duration
        # disagrees with Pocket Casts'.
        media = make_stitched_mp3()
        self.fake["media"] = {EP_1: media, EP_2: media}
        for uuid in (EP_1, EP_2):
            self.fake["episodes"][uuid]["duration"] = 60
        self.fake["showSettings"] = {PODCAST_A: {"autoStartFrom": 0, "autoSkipLast": 10}}
        self.fake["rate"] = 40000
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        for _ in range(12):
            view = run_bridge("player")["data"]
            time.sleep(0.25)
        self.assertEqual((view["item"] or {}).get("uuid"), EP_1)
        self.assertTrue(view["playing"])
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        with bridge.Mpv.connect() as player:
            self.assertEqual(player.get("file-local-options/end"), "none")

    def test_play_pressed_before_a_poll_saw_the_break_carries_on_too(self):
        # Play arrives while mpv sits at the break and no poll has run: it
        # must not be taken for an end and replayed from the top.
        self.fake["cut"] = {EP_1: int(len(self.audio) * 0.6)}  # past half: the break evidence alone decides
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        with bridge.Mpv.connect() as player:
            self.wait_for(lambda: player.get("eof-reached") is True, timeout=30)
            broke_at = player.get("time-pos")
        self.fake["cut"] = {}
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.playing_past(broke_at)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertNotIn(0, [b["position"] for b in self.writes("/sync/update_episode") if b["uuid"] == EP_1][1:])

    def test_play_before_a_poll_reads_the_watchers_evidence(self):
        # The cut past nine tenths: by length alone, about the end. Only the
        # watcher's record (in Play's full snapshot) says it broke.
        self.fake["cut"] = {EP_1: int(len(self.audio) * 0.93)}
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        with bridge.Mpv.connect() as player:
            self.wait_for(lambda: player.get("eof-reached") is True, timeout=30)
        self.fake["cut"] = {}
        run_bridge("toggle")
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_a_break_after_a_long_gap_pushes_nothing(self):
        # Review finding: the shell was down (or the machine slept unguarded)
        # while you carried on with the phone; the first poll afterwards sees
        # the break. Its position is old news: the next resume asks first.
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        with bridge.Mpv.connect() as player:
            self.wait_for(lambda: player.get("eof-reached") is True, timeout=30)
        state = bridge.load_playback()
        state["lastSyncAt"] = time.time() - 200
        bridge.save_playback(state)
        self.fake["progress"][EP_1] = 25  # the phone carried on
        before = len([b for b in self.writes("/sync/update_episode") if b["uuid"] == EP_1])
        self.assertTrue(run_bridge("player")["data"].get("streamBroke"))
        self.assertEqual(len([b for b in self.writes("/sync/update_episode") if b["uuid"] == EP_1]), before)
        self.assertEqual(self.fake["progress"][EP_1], 25)
        self.fake["cut"] = {}
        self.assertGreater(run_bridge("toggle")["data"]["position"], 24)  # Play follows the phone
        self.assertGreaterEqual(self.fake["progress"][EP_1], 25)

    def break_without_a_poll(self):
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        with bridge.Mpv.connect() as player:
            self.wait_for(lambda: player.get("eof-reached") is True, timeout=30)

    def break_with_flag_pushes_nothing(self, flag):
        # Rule 2: while Pocket Casts hasn't confirmed where to resume, this
        # machine's position isn't news; another device may be ahead.
        self.break_without_a_poll()
        state = bridge.load_playback()
        state[flag] = True
        bridge.save_playback(state)
        self.fake["progress"][EP_1] = 25  # the phone is ahead
        before = len([b for b in self.writes("/sync/update_episode") if b["uuid"] == EP_1])
        self.assertTrue(run_bridge("player")["data"].get("streamBroke"))
        self.assertEqual(len([b for b in self.writes("/sync/update_episode") if b["uuid"] == EP_1]), before)
        self.assertEqual(self.fake["progress"][EP_1], 25)

    def test_a_break_during_an_unconfirmed_resume_pushes_nothing(self):
        self.break_with_flag_pushes_nothing("unconfirmed")

    def test_a_break_before_the_resume_check_pushes_nothing(self):
        self.break_with_flag_pushes_nothing("checkServer")

    def test_a_second_break_near_the_first_is_still_a_break(self):
        # Strict review SR1: a flaky link breaking twice in the same place
        # was once taken for the end, marking an unfinished episode played
        # on every device (and Play then restarted it from 0:00).
        self.break_stream_and_wait()
        broke_at = bridge.load_playback()["position"]
        self.fake["cutServed"] = {}  # the same cut, again
        self.assertEqual(run_bridge("toggle")["data"]["item"]["uuid"], EP_1)
        view = self.wait_for(lambda: (lambda v: v if v.get("streamBroke") or v.get("ended")
                                      or (v["item"] or {}).get("uuid") != EP_1 else None)(run_bridge("player")["data"]),
                             timeout=30)
        self.assertTrue(view.get("streamBroke"))
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)
        pushed = [b for b in self.writes("/sync/update_episode") if b["uuid"] == EP_1]
        self.assertGreaterEqual(min(b["position"] for b in pushed[1:]), int(broke_at) - 1)  # never back to 0

    def quick_load_wait(self, seconds=0.3):
        """wait_for_load giving up sooner, so a slow host's load outlasts it."""
        real = bridge.Mpv.wait_for_load
        patcher = mock.patch.object(bridge.Mpv, "wait_for_load", lambda player, timeout=20.0: real(player, seconds))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_slow_load_still_tells_a_break_from_the_end(self):
        # Strict review SR15: a load slower than the wait stored no record of
        # the file, and a later break was taken for the end. Polls fill it in.
        self.quick_load_wait()
        self.fake["slowaudio"] = {EP_1: 1.0}
        self.assertEqual(self.break_stream_and_wait().get("streamBroke"), True)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)
        self.assertEqual(bridge.load_playback()["stream"]["size"], len(self.audio))  # learnt by a poll

    def test_a_slow_load_with_no_poll_before_the_break_is_still_a_break(self):
        # No poll learned the size: Pocket Casts' duration (30 s) says a stop
        # at about 6 s is no end.
        self.quick_load_wait()
        self.fake["slowaudio"] = {EP_1: 1.0}
        self.break_without_a_poll()
        self.assertTrue(run_bridge("player")["data"].get("streamBroke"))
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_a_host_without_a_size_breaks_and_ends_properly(self):
        # Strict review SR17: a host that sends no size, serving MP3. mpv's
        # duration is what has arrived; Pocket Casts' tells a break from the end.
        self.fake["nosize"] = {EP_1, EP_3}
        self.assertEqual(self.break_stream_and_wait().get("streamBroke"), True)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        # A whole, short episode from the same kind of host ends as it should.
        # (Such a host serves no ranges, so mpv can only play it from the top.)
        self.fake["media"] = {EP_3: make_audio(5)}
        self.fake["episodes"][EP_3]["duration"] = 5
        run_bridge("play", EP_3, "--podcast", PODCAST_B)
        self.wait_for(lambda: run_bridge("player") and self.fake["status"].get(EP_3) == bridge.STATUS_PLAYED or None,
                      timeout=20)

    def test_a_break_while_pocket_casts_is_down_carries_on_from_there(self):
        # Strict review SR18: the break's push failed, and Play went back to
        # where Pocket Casts last heard (here the start).
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {"/sync/update_episode": 1000}  # the network goes with the stream
        self.wait_for(lambda: (lambda v: v if v.get("streamBroke") else None)(run_bridge("player")["data"]), timeout=30)
        broke_at = bridge.load_playback()["position"]
        self.assertGreater(broke_at, 3)
        self.fake["fail"], self.fake["cut"] = {}, {}
        view = run_bridge("toggle")["data"]
        self.assertGreater(view["position"], broke_at - 1)
        self.playing_past(broke_at)

    def test_after_an_unsent_break_pocket_casts_further_on_wins(self):
        # The break's push failed at about 6 s; meanwhile the phone listened
        # on to 25 s: Pocket Casts' position wins.
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.wait_for(lambda: (lambda v: v if v.get("streamBroke") else None)(run_bridge("player")["data"]), timeout=30)
        self.assertTrue(bridge.load_playback().get("unsentPush"))
        self.fake["fail"], self.fake["cut"] = {}, {}
        self.fake["progress"][EP_1] = 25
        self.assertGreater(run_bridge("toggle")["data"]["position"], 24)

    def test_an_unsent_position_is_kept_for_an_hour_only(self):
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.fake["fail"] = {"/sync/update_episode": 1000}
        self.wait_for(lambda: (lambda v: v if v.get("streamBroke") else None)(run_bridge("player")["data"]), timeout=30)
        state = bridge.load_playback()
        state["unsentPush"]["at"] -= 2 * 3600  # long ago
        bridge.save_playback(state)
        self.fake["fail"], self.fake["cut"] = {}, {}
        view = run_bridge("toggle")["data"]
        self.assertLess(view["position"], 2)  # Pocket Casts' (the start), not the old local one

    def test_play_at_a_real_end_before_any_poll_finishes_it_first(self):
        # Play's own end check reads the file's size: a real end (read to its
        # end) isn't a break. Strict review 8: no poll has finished it yet, so
        # Play finishes it (marked played; playing it again from the top
        # pushed 0 over it); a second Play plays it again.
        self.fake["progress"][EP_1] = 26
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        with bridge.Mpv.connect() as player:
            self.wait_for(lambda: player.get("eof-reached") is True, timeout=15)
            pid, _ = player.peer_pid()
        seen = []
        judge = bridge.stream_broke
        with mock.patch.object(bridge, "stream_broke", lambda snap, state: seen.append(dict(snap)) or judge(snap, state)):
            view = run_bridge("toggle")["data"]
        self.assertTrue(seen and {"path", "stream-end", "stream-pos"} <= set(seen[0]), seen)
        self.assertFalse(view.get("streamBroke"))
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertNotIn(0, [b["position"] for b in self.pushes_of(EP_1)])
        view = run_bridge("toggle")["data"]
        self.assertLess(view["position"], 5)
        self.assertTrue(view["playing"])
        with bridge.Mpv.connect() as player:
            self.assertEqual(player.peer_pid()[0], pid)  # the same player, from the top: not closed as a break

    def settled(self, uuid, timeout=40):
        return self.wait_for(lambda: (lambda v: v if v.get("streamBroke") or v.get("ended")
                                      or (v["item"] or {}).get("uuid") != uuid else None)(run_bridge("player")["data"]),
                             timeout=timeout)

    def test_an_m4a_with_its_index_after_the_audio_ends_properly(self):
        # Strict review SR23: FFmpeg writes an M4A's index (moov) after its
        # audio unless told otherwise; mpv never reads it at the end, so the
        # file looked "much unread", and its real end a break.
        self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=600", "-c:a", "aac", "-b:a", "32k"], ".m4a")}
        self.fake["episodes"][EP_1].update(duration=600, url=self.base + "/audio/%s.m4a" % EP_1)
        self.fake["progress"][EP_1] = 595
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.settled(EP_1)
        self.assertFalse(view.get("streamBroke"))
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_a_skip_outro_show_listed_longer_than_its_file_ends_properly(self):
        # Strict review SR24: Pocket Casts lists 132 s for a file of 120 (ads
        # inserted on the fly); the show skips the last 20 s.
        self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=120", "-c:a", "libmp3lame", "-b:a", "128k"], ".mp3")}
        self.fake["episodes"][EP_1]["duration"] = 132
        self.fake["showSettings"] = {PODCAST_A: {"autoStartFrom": 0, "autoSkipLast": 20}}
        self.fake["progress"][EP_1] = 94
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assertFalse(self.settled(EP_1).get("streamBroke"))
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_a_host_without_ranges_never_rewinds_the_others(self):
        # Strict review SR25: such a host can't start part way, so mpv plays
        # from the top; the next push would have rewound every device there.
        self.fake["nosize"] = {EP_1}
        self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=90", "-c:a", "libmp3lame", "-b:a", "64k"], ".mp3")}
        self.fake["episodes"][EP_1]["duration"] = 90
        self.fake["progress"][EP_1] = 60
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        time.sleep(2)
        told = run_bridge("player")["data"].get("startedFromTop")
        self.assertFalse(run_bridge("player")["data"].get("startedFromTop"))  # said once
        state = bridge.load_playback()
        state["lastSyncAt"] = time.time() - 31  # a periodic push is due
        bridge.save_playback(state)
        run_bridge("player")
        run_bridge("pause")
        run_bridge("stop")
        self.assertGreaterEqual(self.fake["progress"][EP_1], 60)
        self.assertTrue(told)

    def slow_host_without_ranges(self, at=60):
        self.fake["nosize"] = {EP_1}
        self.fake["rate"] = 20000
        self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=90", "-c:a", "libmp3lame", "-b:a", "64k"], ".mp3")}
        self.fake["episodes"][EP_1]["duration"] = 90
        self.fake["progress"][EP_1] = at
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()

    def test_a_seek_on_a_host_without_ranges_never_rewinds_the_others(self):
        # Strict review 4: on a real (slow) host without ranges, a seek beyond
        # what has arrived doesn't land; lifting the floor on any seek of
        # yours pushed the from-the-top position at once.
        self.slow_host_without_ranges(60)
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 1)
        run_bridge("seek", "60", "--episode", EP_1)  # the slider dragged to where you were
        time.sleep(2)  # mpv gives up the seek and plays on near the top
        self.assertLess(run_bridge("player")["data"]["position"], 30)
        self.push_due()
        run_bridge("player")
        self.assertGreaterEqual(self.fake["progress"][EP_1], 60)
        run_bridge("seek", "15", "--relative", "--episode", EP_1)  # and a skip forward
        time.sleep(1)
        run_bridge("pause")
        self.assertGreaterEqual(self.fake["progress"][EP_1], 60)

    def push_due(self):
        state = bridge.load_playback()
        state["lastSyncAt"] = time.time() - 31  # a periodic push is due
        bridge.save_playback(state)

    def test_a_seek_back_from_a_start_that_was_honoured_syncs(self):
        # On a host that did start where asked, a seek back before any poll
        # lifted the floor is yours: it syncs.
        self.fake["progress"][EP_1] = 20
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 20.5)
        state = bridge.load_playback()
        state["stream"]["asked"] = 20  # as if no poll had seen it start there yet
        bridge.save_playback(state)
        run_bridge("seek", "8", "--episode", EP_1)
        run_bridge("pause")
        self.assertLess(self.fake["progress"][EP_1], 12)

    def test_the_resume_checks_seek_on_a_host_without_ranges_never_rewinds(self):
        # Strict review 4: paused here near the top, the phone moved on to
        # 60; Play seeks there, which such a host can't do: mpv plays on from
        # the old spot, and the next push used to send it.
        self.slow_host_without_ranges(0)
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 1)
        run_bridge("pause")
        self.fake["progress"][EP_1] = 60  # the phone listened on
        state = bridge.load_playback()
        state["lastSyncAt"] = time.time() - 120  # the pause was a while ago
        bridge.save_playback(state)
        run_bridge("toggle")
        time.sleep(2)  # mpv gives up the seek and plays on from the old spot
        self.assertLess(run_bridge("player")["data"]["position"], 30)
        self.push_due()
        run_bridge("player")
        run_bridge("pause")
        self.assertGreaterEqual(self.fake["progress"][EP_1], 60)

    def test_a_break_behind_where_the_load_began_isnt_nothing_more(self):
        # Loaded at 30:00, skipped back, the link drops at 29:55: not "nothing
        # more of it arrives" (that's for a reload that got nowhere).
        url = self.base + "/audio/%s.mp3" % EP_1
        state = {"episode": {"uuid": EP_1, "url": url}, "stream": {"url": url, "begun": 1800.0}}
        strike = {"uuid": EP_1, "at": 1795.0}  # it stopped here before
        with mock.patch.object(bridge, "push_position"):
            self.assertFalse(bridge.stream_stopped(dict(state, lastSyncAt=time.time(), breakStrike=strike), {}, 1795.0)
                             .get("nothingMore"))
            # A reload that stopped where it began, the second time there.
            strike = {"uuid": EP_1, "at": 1800.0}
            self.assertTrue(bridge.stream_stopped(dict(state, lastSyncAt=time.time(), breakStrike=strike), {}, 1800.5)
                            .get("nothingMore"))
            # The first time there: just dropped.
            self.assertFalse(bridge.stream_stopped(dict(state, lastSyncAt=time.time()), {}, 1800.5).get("nothingMore"))
            # The same spot again, but after playing 5 s from the load's start:
            # it got somewhere.
            strike = {"uuid": EP_1, "at": 1805.0}
            self.assertFalse(bridge.stream_stopped(dict(state, lastSyncAt=time.time(), breakStrike=strike), {}, 1805.0)
                             .get("nothingMore"))

    def test_after_a_seek_a_reload_that_breaks_isnt_nothing_more(self):
        # Loaded at 20, a seek of yours back to 20, and the link drops at
        # 21.5: it got somewhere after your seek, not "nothing more arrives".
        self.fake["progress"][EP_1] = 20
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.fake["cut"] = {EP_1: int(len(self.audio) * 21.5 / 30)}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        state = bridge.load_playback()
        state["breakStrike"] = {"uuid": EP_1, "at": 21.4}  # it broke there before, too
        bridge.save_playback(state)
        run_bridge("seek", "20", "--episode", EP_1)
        view = self.settled(EP_1)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertFalse(view.get("nothingMore"))

    def test_a_break_below_the_start_pushes_nothing(self):
        # The break's own push respects the floor too (a host without ranges).
        url = self.base + "/audio/%s.mp3" % EP_1
        state = {"episode": {"uuid": EP_1, "url": url}, "lastSyncAt": time.time(),
                 "stream": {"url": url, "asked": 60}}
        with mock.patch.object(bridge, "push_position") as push:
            bridge.stream_stopped(state, {}, 10.0)
        push.assert_not_called()

    def test_a_reload_that_gets_nothing_says_how_to_mark_it_played(self):
        # Strict review SR28: the same stop again, at once: nothing more
        # arrives. Said, never marked played by itself.
        self.break_stream_and_wait()
        self.fake["cutServed"] = {}  # the same cut again
        run_bridge("toggle")
        view = self.settled(EP_1)
        self.assertTrue(view.get("streamBroke"))
        self.assertTrue(view.get("nothingMore"))
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_plays_break_check_is_for_the_recorded_episode_only(self):
        # Strict review SR27: as the poll does, Play's own check judges only
        # the episode Legato loaded.
        self.break_without_a_poll()
        state = bridge.load_playback()
        state["episode"]["url"] += "?another"
        bridge.save_playback(state)
        seen = []
        judge = bridge.stream_broke
        with mock.patch.object(bridge, "stream_broke", lambda snap, st: seen.append(1) or judge(snap, st)):
            run_bridge("toggle")
        self.assertEqual(seen, [])

    def test_a_real_end_is_still_the_end(self):
        self.fake["progress"][EP_1] = 25  # the last 5 s of 30
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: (lambda v: v if (v["item"] or {}).get("uuid") == EP_2 else None)(run_bridge("player")["data"]), timeout=20)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_how_a_break_is_told_from_the_end(self):
        url = "http://example.com/a.mp3"
        watching = {"watching": True}
        def snap(**kw):
            base = {"eof-reached": True, "path": url, "time-pos": 1800.0, "duration": 3600.0,
                    "stream-pos": None, "stream-end": None, "file-local-options/end": "none",
                    "user-data/legato": watching, "seekable": True,
                    "mpv-version": "mpv 0.41.0", "ffmpeg-version": "n9.0"}
            base.update(kw)
            return base
        def state(size=None, duration=None, listed=None):
            st = {"stream": {"url": url, "size": size, "duration": duration}}
            if listed:
                st["episode"] = {"uuid": EP_1, "url": url, "duration": listed}
            return st
        cut = {"user-data/legato": {"watching": True, "cut": 40_000_000}}
        # 1. The watcher saw FFmpeg's "Stream ends prematurely at N": a break,
        #    whatever the size reads now (an error page's 70 bytes) or the
        #    durations say (a misread MP3 "ending" at 23 s of 18.4).
        self.assertTrue(bridge.stream_broke(snap(**cut, **{"stream-pos": 40_000_000}), {}))
        self.assertTrue(bridge.stream_broke(snap(**cut, **{"stream-end": 70, "stream-pos": 39_990_000}), state(size=100_000_000)))
        self.assertTrue(bridge.stream_broke(snap(**cut, **{"stream-end": 100_000_000, "time-pos": 23.0, "duration": 18.4}), {}))
        self.assertTrue(bridge.stream_broke(snap(**cut, **{"time-pos": 3599.0, "stream-end": 100_000_000,
                                                           "stream-pos": 40_000_000}), {}))  # at "the end" by its duration
        # With no size from the host a reconnect proves nothing (some log one
        # at a real end): the length rule decides.
        self.assertFalse(bridge.stream_broke(snap(**cut, **{"time-pos": 3599.0}), {}))
        #    ...unless mpv read on past it (a reconnect that worked), to a real end:
        self.assertFalse(bridge.stream_broke(snap(**cut, **{"stream-end": 100_000_000, "stream-pos": 99_999_000}), {}))
        # 2. No such line and the host gave a size: the end, whatever mpv's
        #    estimates say (an M4A's index left unread, a misread MP3, an outro).
        self.assertFalse(bridge.stream_broke(snap(**{"stream-end": 100_000_000, "stream-pos": 40_000_000}), {}))
        #    Unless mpv's version can't be read: no self-check verdict can be
        #    matched then, so the length judges (strict review 22, L2).
        self.assertTrue(bridge.stream_broke(snap(**{"stream-end": 100_000_000, "stream-pos": 40_000_000,
                                                    "mpv-version": None}), {}))
        self.assertFalse(bridge.stream_broke(snap(**{"time-pos": 23.0, "duration": 18.4}), state(size=1_000_000, listed=60)))
        self.assertFalse(bridge.stream_broke(snap(**{"stream-end": 5000, "time-pos": 0.0, "file-local-options/end": "-20"}),
                                             state(listed=60)))
        #    ...an error page's length (70) read for the size, with the load's
        #    size unknown: mpv read past it, so not "to the end".
        self.assertTrue(bridge.stream_broke(snap(**cut, **{"stream-end": 70, "stream-pos": 39_990_000}), {}))
        # 2b. A host without ranges (not seekable): read straight through, the
        #     end only if mpv read to the size; nothing read at all is a break.
        unseekable = {"seekable": False, "stream-end": 120_270}
        self.assertFalse(bridge.stream_broke(snap(**unseekable, **{"stream-pos": 120_166}), {}))
        self.assertTrue(bridge.stream_broke(snap(**unseekable, **{"stream-pos": 23_966}), {}))
        self.assertTrue(bridge.stream_broke(snap(**unseekable, **{"stream-pos": None, "time-pos": 0.0}), {}))
        # 3. No size from the host, or a player without the watcher: against
        #    the longest duration given, with a 10% margin (or 10 s), the
        #    skip-outro allowed for. A no-size MP3's mpv duration is what arrived.
        self.assertTrue(bridge.stream_broke(snap(**{"time-pos": 6.0, "duration": 6.0}), state(duration=1.1, listed=30)))
        self.assertFalse(bridge.stream_broke(snap(**{"time-pos": 28.0, "duration": 28.0}), state(duration=1.1, listed=30)))
        self.assertFalse(bridge.stream_broke(snap(**{"time-pos": 3300.0}), state(listed=3600)))  # 300 s short of 3600: within 10%
        self.assertTrue(bridge.stream_broke(snap(**{"time-pos": 3200.0}), state(listed=3600)))   # 400 s short: a break
        self.assertFalse(bridge.stream_broke(snap(**{"time-pos": 2950.0, "file-local-options/end": "-300"}), state(listed=3600)))
        self.assertTrue(bridge.stream_broke(snap(**{"time-pos": 2850.0, "file-local-options/end": "-300"}), state(listed=3600)))
        old = {"user-data/legato": None, "stream-end": 100_000_000, "stream-pos": 40_000_000}
        self.assertTrue(bridge.stream_broke(snap(**old, **{"time-pos": 6.0, "duration": 6.0}), {"episode": {"duration": 30}}))
        self.assertFalse(bridge.stream_broke(snap(**old, **{"time-pos": 29.0, "duration": 30.0}), {}))
        # 4. Nothing to judge by: the end, as before 1.1.
        self.assertFalse(bridge.stream_broke({"eof-reached": True, "path": url, "time-pos": 50.0}, {}))
        # Another file's record doesn't count; not at an end, nothing to judge.
        self.assertTrue(bridge.stream_broke(snap(**{"time-pos": 6.0, "duration": 6.0}),
                                            {"stream": {"url": "http://other/b.mp3", "size": 5}, "episode": {"duration": 30}}))
        self.assertFalse(bridge.stream_broke(snap(**{"eof-reached": False}), state(size=100)))
        # What the poll reads includes the watcher's record (every poll: it
        # times stalls too), and at an end where mpv read to and whether it
        # could seek.
        self.assertIn("user-data/legato", bridge.MPV_PROPERTIES)
        self.assertIn("stream-pos", bridge.END_PROPERTIES)
        self.assertIn("seekable", bridge.END_PROPERTIES)

    def test_the_watcher_records_a_cut_short_stream(self):
        # The watcher itself, in mpv's own Lua: FFmpeg's short-end line for a
        # sized stream and its reconnect lines (an https drop, a timeout) are
        # recorded (the latest), the short-end line for a host that gave no
        # size isn't, other components' aren't, and a new file starts clean.
        lua = shutil.which("lua5.1") or shutil.which("luajit")
        if not lua:
            self.skipTest("no Lua 5.1 to run mpv's script in")
        harness = r"""
            local props, handlers, observed = {}, {}, {}
            mp = { set_property_native = function(name, value) props[name] = value end,
                   register_event = function(name, fn) handlers[name] = fn end,
                   observe_property = function(name, kind, fn) observed[name] = fn end,
                   enable_messages = function(level) props.level = level end }
            dofile(os.getenv("WATCH"))
            local function show() local d = props["user-data/legato"] io.write(tostring(d.watching), " ", tostring(d.cut), ";") end
            show()
            handlers["log-message"]({ prefix = "ffmpeg", level = "error", text = "http: Stream ends prematurely at 24054, should be 120270\n" })
            show()
            handlers["log-message"]({ prefix = "ffmpeg", level = "error", text = "http: Stream ends prematurely at 99, should be 18446744073709551615\n" })
            handlers["log-message"]({ prefix = "cplayer", level = "error", text = "Stream ends prematurely at 5, should be 9" })
            show()
            handlers["log-message"]({ prefix = "ffmpeg", level = "error", text = "http: Stream ends prematurely at 30000, should be 120270" })
            show()
            handlers["log-message"]({ prefix = "ffmpeg", level = "warn", text = "https: Will reconnect at 41000 in 0 second(s), error=Input/output error.\n" })
            show()
            handlers["log-message"]({ prefix = "ffmpeg", level = "warn", text = "http: Will reconnect at 52000 in 1 second(s), error=Connection timed out.\n" })
            show()
            handlers["log-message"]({ prefix = "ffmpeg", level = "warn", text = "http: HTTP error 403 Forbidden" })
            io.write(tostring(props["user-data/legato"].failed), tostring(props["user-data/legato"].seen.error), ";")
            handlers["log-message"]({ prefix = "ffmpeg", level = "warn", text = "https: Will reconnect at 61000 in 0 second(s)" })
            io.write(tostring(props["user-data/legato"].failed), ";")
            handlers["log-message"]({ prefix = "ffmpeg", level = "error", text = "tls: Error in the pull function." })
            handlers["seek"]({})
            io.write(tostring(props["user-data/legato"].failed), ";")
            handlers["log-message"]({ prefix = "ffmpeg", level = "error", text = "http: Stream ends prematurely at 99, should be 18446744073709551615" })
            io.write(tostring(props["user-data/legato"].failed), ";")
            observed["paused-for-cache"]("paused-for-cache", true)
            local d = props["user-data/legato"]
            io.write(tostring(type(d.stallSince) == "number"), ";")
            observed["paused-for-cache"]("paused-for-cache", true)  -- still the same stall
            local since = d.stallSince
            observed["paused-for-cache"]("paused-for-cache", false)
            d = props["user-data/legato"]
            local last = d.stalls[#d.stalls]
            io.write(tostring(d.stallSince), " ", tostring(last.since == since and last.ended >= since), ";")
            handlers["start-file"]({})
            show()
            io.write(props.level)
        """
        done = subprocess.run([lua, "-e", harness], capture_output=True, text=True, timeout=10,
                              env={"WATCH": str(ROOT / "bin" / "legato-watch.lua"), "PATH": "/usr/bin"})
        self.assertEqual(done.stdout, "true nil;true 24054;true 24054;true 30000;true 41000;true 52000;truetrue;nil;nil;nil;"
                                      "true;nil true;true nil;warn", done.stderr)

    def test_polls_fill_in_what_a_slow_load_missed(self):
        url = "http://example.com/a.mp3"
        state = {"episode": {"uuid": EP_1, "url": url}, "stream": {"url": url, "size": None, "duration": None}}
        bridge.learn_stream(state, {"path": url, "stream-end": 5000, "duration": 18.4})
        self.assertEqual(state["stream"], {"url": url, "size": 5000, "duration": 18.4})
        bridge.learn_stream(state, {"path": url, "stream-end": None, "duration": 60.0})  # mpv corrected its estimate
        self.assertEqual(state["stream"], {"url": url, "size": 5000, "duration": 60.0})
        bridge.learn_stream(state, {"path": url, "stream-end": None, "duration": 30.0})  # never shrinks
        self.assertEqual(state["stream"]["duration"], 60.0)
        bridge.learn_stream(state, {"path": url, "stream-end": None, "duration": 6.0, "eof-reached": True})  # not at an end
        self.assertEqual(state["stream"]["duration"], 60.0)
        # A start that couldn't be honoured is forgotten once playback passes
        # it, and said once while it's below.
        floor = {"episode": {"uuid": EP_1, "url": url}, "stream": {"url": url, "asked": 60}}
        bridge.learn_stream(floor, {"path": url, "time-pos": 3.0})
        bridge.learn_stream(floor, {"path": url, "time-pos": 4.0})
        self.assertTrue(floor.pop("tellStart"))
        bridge.learn_stream(floor, {"path": url, "time-pos": 5.0})
        self.assertNotIn("tellStart", floor)
        self.assertTrue(bridge.below_start(floor, 5.0))
        bridge.learn_stream(floor, {"path": url, "time-pos": 58.0})
        self.assertIsNone(floor["stream"]["asked"])
        self.assertFalse(bridge.below_start(floor, 5.0))
        old = {"episode": {"uuid": EP_1, "url": url}}  # a player an older Legato loaded
        bridge.learn_stream(old, {"path": url, "stream-end": 7000, "duration": 30.0})
        self.assertEqual(old["stream"], {"url": url, "size": 7000, "duration": 30.0})
        other = {"episode": {"uuid": EP_1, "url": url}}
        bridge.learn_stream(other, {"path": "http://other/b.mp3", "stream-end": 1, "duration": 1.0})
        self.assertNotIn("stream", other)

    def test_a_load_records_what_mpv_knew_of_the_file(self):
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        stream = bridge.load_playback()["stream"]
        self.assertEqual(stream["size"], len(self.audio))
        self.assertAlmostEqual(stream["duration"], self.AUDIO_SECONDS, delta=0.5)
        self.assertTrue(stream["url"].endswith(EP_1 + ".mp3"))


class ListeningCount(TempHome):
    """The listening stats' arithmetic, with the clock under the test's control."""

    URL = "http://example.com/a.mp3"

    def count(self, state, at, position, speed=1.5, trim="madmax", seeked=False, pause=False):
        snap = {"path": self.URL, "pause": pause, "time-pos": position, "speed": speed, "eof-reached": False}
        with mock.patch.object(bridge.time, "monotonic", return_value=at):
            bridge.count_listening(state, snap, {"trim": trim}, seeked)

    def fresh(self):
        return {"episode": {"uuid": EP_1, "url": self.URL}}

    def test_speed_and_trim_split_the_time_saved(self):
        state = self.fresh()
        self.count(state, 100.0, 10.0)
        self.count(state, 130.0, 60.0)
        stats = bridge.load_stats()
        # 30 s listened; at 1.5x that's 45 s of episode, and it moved 50:
        # 15 s saved by the speed, 5 cut by Trim Silence.
        self.assertAlmostEqual(stats["listened"], 30)
        self.assertAlmostEqual(stats["speed"], 15)
        self.assertAlmostEqual(stats["trim"], 5)
        self.assertGreater(stats["since"], 0)

    def test_without_trim_nothing_is_put_down_to_it(self):
        state = self.fresh()
        self.count(state, 100.0, 10.0, trim="off")
        self.count(state, 130.0, 55.2, trim="off")
        stats = bridge.load_stats()
        self.assertNotIn("trim", stats)
        self.assertAlmostEqual(stats["speed"], 15.2)

    def test_a_jump_or_a_stall_isnt_counted(self):
        # 30 s at 1.5x: 75 s is a seek without trim, 190 a jump even Mad Max
        # can't explain, and 5 s a stall.
        for trim, moved in (("off", 75.0), ("madmax", 190.0), ("off", 5.0), ("madmax", 5.0)):
            state = self.fresh()
            self.count(state, 100.0, 10.0, trim=trim)
            self.count(state, 130.0, 10.0 + moved, trim=trim)
        self.assertEqual(bridge.load_stats(), {})
        # The same stretch, played: counted.
        state = self.fresh()
        self.count(state, 100.0, 10.0, trim="off")
        self.count(state, 130.0, 55.0, trim="off")
        self.assertAlmostEqual(bridge.load_stats()["listened"], 30)

    def test_after_a_seek_from_elsewhere_only_the_speed_counts(self):
        state = self.fresh()
        self.count(state, 100.0, 10.0)
        self.count(state, 130.0, 70.0, seeked=True)  # a media widget skipped 15 s in there
        stats = bridge.load_stats()
        self.assertAlmostEqual(stats["listened"], 30)
        self.assertAlmostEqual(stats["speed"], 15)
        self.assertNotIn("trim", stats)

    def test_paused_time_and_long_gaps_arent_listening(self):
        state = self.fresh()
        self.count(state, 100.0, 10.0, pause=True)   # paused: no count starts
        self.count(state, 200.0, 10.0)
        self.assertEqual(bridge.load_stats(), {})
        self.count(state, 900.0, 600.0)               # 700 s later (the shell was down): not counted
        self.assertEqual(bridge.load_stats(), {})
        state["episode"] = {"uuid": EP_2, "url": self.URL}
        self.count(state, 910.0, 615.0)               # another episode: a new count, nothing added
        self.assertEqual(bridge.load_stats(), {})

    def test_after_a_seek_from_elsewhere_only_a_playing_poll_length_counts(self):
        # Strict review SR5: the seek flag once skipped every check, so a
        # stall or a pause up to 300 s counted as listening.
        state = self.fresh()
        self.count(state, 100.0, 10.0)
        self.count(state, 200.0, 70.0, seeked=True)  # 100 s: longer than any poll's stretch
        self.assertEqual(bridge.load_stats(), {})
        state = self.fresh()
        self.count(state, 100.0, 10.0)
        with mock.patch.object(bridge.time, "monotonic", return_value=130.0):
            bridge.count_listening(state, {"path": self.URL, "pause": False, "time-pos": 85.5, "speed": 1.5,
                                           "eof-reached": False, "paused-for-cache": True}, {"trim": "madmax"}, True)
        self.assertEqual(bridge.load_stats(), {})  # it ended stalled
        state = self.fresh()
        self.count(state, 100.0, 10.0)
        self.count(state, 130.0, 70.0, seeked=True, pause=True)  # it ended paused
        self.assertEqual(bridge.load_stats(), {})
        state = self.fresh()
        self.count(state, 100.0, 10.0)
        self.count(state, 130.0, 70.0, seeked=True)  # a poll's stretch, playing: counted
        self.assertAlmostEqual(bridge.load_stats()["listened"], 30)

    def test_a_pause_ends_the_count(self):
        # Paused, no count runs: after a 30 s pause and a seek from a media
        # widget (which skips the motion check), the pause isn't listening.
        state = self.fresh()
        self.count(state, 100.0, 10.0, pause=True)
        self.assertEqual(state["listening"], {})
        self.count(state, 130.0, 10.5, seeked=True)
        self.assertEqual(bridge.load_stats(), {})

    def test_a_long_stretch_isnt_listening_even_at_a_plausible_pace(self):
        # LISTEN_GAP_MAX on its own: 400 s that moved exactly at 1.5x.
        state = self.fresh()
        self.count(state, 100.0, 10.0)
        self.count(state, 500.0, 610.0)
        self.assertEqual(bridge.load_stats(), {})

    def test_a_count_that_starts_buffering_or_on_another_file_counts_nothing(self):
        state = self.fresh()
        with mock.patch.object(bridge.time, "monotonic", return_value=100.0):
            bridge.count_listening(state, {"path": self.URL, "pause": False, "time-pos": 10.0, "speed": 1.5,
                                           "eof-reached": False, "paused-for-cache": True}, {"trim": "madmax"})
        self.assertEqual(state["listening"], {})  # still loading: no count starts
        self.count(state, 130.0, 55.0)
        self.assertEqual(bridge.load_stats(), {})
        state = self.fresh()
        self.count(state, 100.0, 10.0)
        with mock.patch.object(bridge.time, "monotonic", return_value=130.0):
            bridge.count_listening(state, {"path": "http://other/b.mp3", "pause": False, "time-pos": 55.0,
                                           "speed": 1.5, "eof-reached": False}, {"trim": "madmax"})
        self.assertEqual(bridge.load_stats(), {})  # mpv is playing something else

    def test_the_bounds_are_tight(self):
        # Without Trim, 5 s further than the speed allows in 30 s is a jump
        # (a widget's small skip), and 3 s short a stall: neither counts.
        for moved in (45.0 + 5, 45.0 - 1.5 * 3):
            state = self.fresh()
            self.count(state, 100.0, 10.0, trim="off")
            self.count(state, 130.0, 10.0 + moved, trim="off")
        self.assertEqual(bridge.load_stats(), {})

    def test_since_is_the_first_count_and_stays(self):
        with mock.patch.object(bridge.time, "time", return_value=1_700_000_000):
            bridge.add_stats(listened=10)
        with mock.patch.object(bridge.time, "time", return_value=1_800_000_000):
            bridge.add_stats(listened=10)
        self.assertEqual(bridge.load_stats()["since"], 1_700_000_000)
        self.assertEqual(run_bridge("stats")["data"]["since"], 1_700_000_000)  # what the page shows

    def test_a_speed_change_mid_stretch_drops_that_stretch(self):
        state = self.fresh()
        self.count(state, 100.0, 10.0, speed=1.5)
        self.count(state, 130.0, 40.0, speed=1.0)
        self.assertEqual(bridge.load_stats(), {})

    def test_a_trim_change_mid_stretch_drops_that_stretch(self):
        state = self.fresh()
        self.count(state, 100.0, 10.0, trim="off")
        self.count(state, 130.0, 60.0, trim="madmax")
        self.assertEqual(bridge.load_stats(), {})

    def test_stats_never_break_a_poll(self):
        # Strict review SR6: a damaged stats.json, or anything else going
        # wrong in the stats, must not cost a push or a finish.
        with bridge.state_dir(create=True) as held:
            bridge.write_file_at(held, "stats.json", b"[1, 2, 3]", 0o600)
        bridge.add_stats(listened=60)
        self.assertEqual(bridge.load_stats()["listened"], 60)  # started over
        state = self.fresh()
        with mock.patch.object(bridge, "add_stats", mock.Mock(side_effect=RuntimeError("boom"))):
            self.count(state, 100.0, 10.0)
            self.count(state, 130.0, 55.0)  # would raise into the poll
        self.assertEqual(state["listening"], {})

    def test_counting_can_be_turned_off_and_cleared(self):
        # For people who'd rather nothing was kept: a player choice (it
        # survives the plugin being disabled), and a clear that deletes the file.
        bridge.add_stats(listened=60)
        self.assertFalse(run_bridge("stats", "off")["data"]["counting"])
        self.assertIs(bridge.load_prefs()["stats"], False)
        state = self.fresh()
        self.count(state, 100.0, 10.0)
        self.count(state, 130.0, 60.0)
        bridge.add_stats(intro=12, finished=1)
        self.assertEqual(bridge.load_stats().get("listened"), 60)  # nothing added while off
        self.assertNotIn("intro", bridge.load_stats())
        cleared = run_bridge("stats", "clear")["data"]
        self.assertEqual((cleared["listened"], cleared["since"], cleared["counting"]), (0.0, 0, False))
        self.assertFalse(os.path.exists(os.path.join(os.environ["XDG_STATE_HOME"], "omarchy-legato", "stats.json")))
        self.assertTrue(run_bridge("stats", "on")["data"]["counting"])
        bridge.add_stats(intro=12)
        self.assertEqual(bridge.load_stats()["intro"], 12)
        self.assertTrue(bridge.player_view({}, {}, {})["statsCounting"])
        self.assertFalse(bridge.player_view({}, {}, {"stats": False})["statsCounting"])

    def test_clear_waits_for_a_poll_counting_at_that_moment(self):
        # Clear holds the state lock, so a poll mid-count can't write the
        # old numbers back after it.
        bridge.add_stats(listened=60)
        quick = functools.partial(bridge.StateLock, timeout=0.3)
        with bridge.StateLock(), mock.patch.object(bridge, "StateLock", quick):
            self.assertEqual(run_bridge("stats", "clear")["code"], "busy")
        self.assertEqual(bridge.load_stats()["listened"], 60)  # not cleared behind the poll's back

    def test_stats_read_while_a_poll_holds_the_lock(self):
        # Review finding: behind a slow poll the page failed with "busy".
        bridge.add_stats(listened=60)
        with bridge.StateLock():
            started = time.monotonic()
            self.assertEqual(run_bridge("stats")["data"]["listened"], 60.0)
            self.assertLess(time.monotonic() - started, 2)

    def test_the_stats_command_reads_them_back(self):
        self.assertEqual(run_bridge("stats")["data"], {"listened": 0.0, "speed": 0.0, "trim": 0.0, "skipping": 0.0,
                                                       "intro": 0.0, "outro": 0.0, "finished": 0, "since": 0,
                                                       "counting": True})
        bridge.add_stats(listened=60, intro=12)
        bridge.add_stats(finished=1)
        data = run_bridge("stats")["data"]
        self.assertEqual((data["listened"], data["intro"], data["finished"]), (60.0, 12.0, 1))
        self.assertEqual(mode_of(os.path.join(os.environ["XDG_STATE_HOME"], "omarchy-legato", "stats.json")), 0o600)


@NEEDS_PLAYER
class ListeningStats(PlayerTestCase):
    """The listening stats from a real (muted) mpv: speed, pauses, skips."""

    AUDIO_SECONDS = 30

    def setUp(self):
        super().setUp()
        for episode in self.fake["episodes"].values():
            episode["duration"] = 30

    def stats(self):
        return run_bridge("stats")["data"]

    def play_for(self, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            time.sleep(0.5)
            run_bridge("player")

    def start(self, speed=None):
        self.login()
        if speed:
            run_bridge("speed", speed)
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: run_bridge("player")["data"]["position"] > 0.3)

    def test_listening_at_double_speed_saves_a_second_a_second(self):
        self.start("2.0")
        self.play_for(3)
        stats = self.stats()
        self.assertGreater(stats["listened"], 2.5)
        self.assertAlmostEqual(stats["speed"], stats["listened"], delta=0.5)
        self.assertEqual(stats["trim"], 0)

    def test_paused_time_isnt_listening(self):
        self.start()
        self.play_for(1.5)
        run_bridge("pause")
        run_bridge("player")
        time.sleep(2)
        run_bridge("player")
        self.assertLess(self.stats()["listened"], 2.5)

    def test_skipping_forward_counts_what_it_skipped_and_back_doesnt(self):
        self.start()
        self.play_for(1)
        run_bridge("seek", "10", "--relative", "--episode", EP_1)
        run_bridge("seek", "-4", "--relative", "--episode", EP_1)
        self.play_for(1)
        stats = self.stats()
        self.assertAlmostEqual(stats["skipping"], 10, delta=0.3)
        self.assertLess(stats["speed"], 1)  # the jumps aren't time saved by the speed

    def test_with_trim_on_a_skip_isnt_counted_as_trimmed_too(self):
        # Review finding: the jump right after a skip passed as Trim
        # Silence (up to 30 s in a moment), on top of the skip itself.
        self.login()
        run_bridge("trim", "madmax")
        self.start()
        self.play_for(1)
        run_bridge("seek", "10", "--relative", "--episode", EP_1)
        self.play_for(1)
        stats = self.stats()
        self.assertAlmostEqual(stats["skipping"], 10, delta=0.3)
        self.assertLess(stats["trim"], 1)  # a plain tone: nothing to trim

    def test_a_seek_from_a_media_widget_isnt_time_saved(self):
        # With Trim on, an unflagged jump this size would pass as trimmed
        # silence; the service's flag is what keeps it out.
        self.login()
        run_bridge("trim", "madmax")
        self.start()
        self.play_for(1)
        with bridge.Mpv.connect() as player:  # what mpv-mpris does for a widget's seek
            player.command("seek", 12, "relative")
        time.sleep(0.5)
        run_bridge("player", "--seeked")  # the service saw mpv's playback-restart
        stats = self.stats()
        self.assertLess(stats["speed"], 1)
        self.assertLess(stats["trim"], 1)
        self.assertEqual(stats["skipping"], 0)

    def test_a_pause_counts_up_to_the_pause_however_late_the_poll(self):
        # Strict review SR9: the stretch before a pause from the panel used to
        # vanish when the poll that saw the pause came more than a second late.
        self.start()
        time.sleep(3)
        run_bridge("pause")
        time.sleep(1.5)
        run_bridge("player")
        self.assertGreater(self.stats()["listened"], 2.5)

    def test_a_speed_or_trim_change_counts_what_came_before(self):
        self.start()
        time.sleep(3)
        run_bridge("speed", "1.5")
        time.sleep(1)
        run_bridge("player")
        self.assertGreater(self.stats()["listened"], 3)
        time.sleep(2)
        run_bridge("player")  # and what came after: a fresh count at the new speed
        self.assertGreater(self.stats()["listened"], 5.6)
        time.sleep(2)
        run_bridge("trim", "mild")
        time.sleep(1)
        run_bridge("player")
        self.assertGreater(self.stats()["listened"], 5)

    def test_next_and_switching_count_up_to_the_change(self):
        self.start()
        time.sleep(2)
        run_bridge("next")
        self.assertGreater(self.stats()["listened"], 1.5)
        run_bridge("player")  # the service polls after Next (mpv's events)
        time.sleep(2)
        run_bridge("play", EP_3, "--podcast", PODCAST_B)
        self.assertGreater(self.stats()["listened"], 3.5)

    def test_a_skip_counts_the_listening_before_it(self):
        self.start()
        time.sleep(3)
        run_bridge("seek", "5", "--relative", "--episode", EP_1)
        self.assertGreater(self.stats()["listened"], 2.5)

    def test_a_skip_counts_how_far_it_went(self):
        # Near the end a 30 s skip goes only as far as the end.
        self.fake["progress"][EP_1] = 20
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.start()
        before = run_bridge("player")["data"]["position"]
        run_bridge("seek", "30", "--relative", "--episode", EP_1)
        self.assertLess(self.stats()["skipping"], 30 - before + 1)
        self.assertGreater(self.stats()["skipping"], 30 - before - 3)

    def test_a_speed_change_never_waits_long_for_the_stats(self):
        # listening_change waits half a second at most for the state lock; a
        # speed change isn't held behind a slow poll for the stats' sake.
        self.start()
        with bridge.StateLock():
            started = time.monotonic()
            self.assertTrue(run_bridge("speed", "1.5")["ok"])
            self.assertLess(time.monotonic() - started, 2)

    def test_a_jump_forward_on_the_slider_isnt_skipping(self):
        self.start()
        run_bridge("seek", "20", "--episode", EP_1)  # absolute: the slider
        self.assertEqual(self.stats()["skipping"], 0)

    def test_the_tests_players_stay_off_the_session_bus(self):
        # Strict review SR11: a test player with mpv-mpris joined the real
        # session bus, a media player on the developer's desktop.
        self.start()
        with bridge.Mpv.connect() as player:
            pid, _ = player.peer_pid()
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            self.assertNotIn(b"mpris", fh.read())

    def test_stopping_counts_up_to_the_stop(self):
        self.start()
        time.sleep(2)
        run_bridge("stop")
        self.assertGreater(self.stats()["listened"], 1.5)


@unittest.skipUnless(os.path.exists("/usr/lib/qt6/bin/qml"), "needs Qt's qml tool")
class QmlPages(unittest.TestCase):
    """The QML offscreen, with stand-ins for Omarchy's components and
    Quickshell's processes (tests/qml): the Settings and Stats pages fit the
    panel and behave (pages.qml); the real Panel and Service work together
    (panel.qml)."""

    def run_qml(self, name):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QML_XHR_ALLOW_FILE_READ="1",
                   QT_FORCE_STDERR_LOGGING="1", QT_QPA_PLATFORMTHEME="")  # no desktop theme (gtk3 needs a display)
        for display in ("WAYLAND_DISPLAY", "DISPLAY"):
            env.pop(display, None)
        here = pathlib.Path(__file__).resolve().parent
        done = subprocess.run(["/usr/lib/qt6/bin/qml", "-I", str(here / "qml" / "imports"), str(here / "qml" / name)],
                              env=env, capture_output=True, text=True, timeout=60)
        lines = [l.split("qml: ", 1)[-1] for l in (done.stdout + done.stderr).splitlines() if "qml: " in l]
        failures = [l for l in lines if l.startswith("FAIL")]
        # A script error in Legato's QML is a failure too, even when no check
        # notices it (a call to a function a service doesn't have, say).
        failures += [l for l in (done.stdout + done.stderr).splitlines()
                     if ("TypeError" in l or "non-existent property" in l or "is not a function" in l
                         or "ReferenceError" in l or "Unable to assign" in l) and "/tests/qml/" not in l.split(": ")[0]]
        self.assertEqual(failures, [])
        self.assertGreater(len([l for l in lines if l.startswith("ok ")]), 10, "\n".join(lines) or done.stderr)
        self.assertEqual(done.returncode, 0)

    def test_pages(self):
        self.run_qml("pages.qml")

    def test_the_real_panel_and_service(self):
        # Panel.qml and Service.qml themselves (tests/qml/panel.qml): pages,
        # keys, the Stats page's reads and errors, the seek flag.
        self.run_qml("panel.qml")

    def test_the_chip(self):
        # The real BarWidget with its Panel and the shell's Service
        # (tests/qml/chip.qml): the bar handed over after loading wakes the
        # service; clicks, the wheel and the title setting; the service's
        # sleep-guard switch and back-off, skip lengths, socket retries.
        self.run_qml("chip.qml")

    def test_one_live_service_and_settings_that_outlive_the_bar_entry(self):
        # SR63 and SR86 (tests/qml/service.qml): the shell's copy dormant
        # until a panel claims it, a replacement bar's panel running its own;
        # settings from settings.json, the bar entry copied in once.
        self.run_qml("service.qml")


class RealQuickshell(unittest.TestCase):
    """What the stand-ins can't model, on the real Quickshell, offscreen, in
    a private runtime folder (no IPC reaches it; no bridge runs): Service.qml's
    own sleep-guard block, sliced from the file as it is, with a command that
    can't start. A Process that never starts reads `running` false there and
    sends nothing (strict review 21, fit F1: the watchdog, armed on
    `running`, never counted it; the stand-in had said it did)."""

    SHELL = """import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
  Item {
    id: root
    property bool active: true
    property bool pauseOnSleep: true
    property bool playerActive: true
    property int startWatchdogMs: 400
    property string python: "/usr/bin/python3"
    property string bridge: "/nonexistent/legato-bridge"
    readonly property var bridgeEnvironment: ({ PATH: "/usr/bin" })
    property int reports: 0
    function settle() {}
    function reportError(text) { reports++; console.warn("REPORT " + text) }
%s
    Component.onCompleted: guardRetryBaseMs = 50
    Timer {
      interval: 6000; running: true
      onTriggered: {
        console.warn("RESULT failures=" + root._guardFailures + " reports=" + root.reports)
        root.playerActive = false  // the episode unloaded: the count starts over
        console.warn("RESET failures=" + root._guardFailures)
        Qt.quit()
      }
    }
  }
}
"""

    def run_guard_block(self, shell_text, command):
        """Service.qml's guard block, `command` its guard, in `shell_text`'s
        shell on the real Quickshell: what it printed."""
        quickshell = shutil.which("quickshell")
        if not quickshell:
            self.skipTest("no quickshell")
        here = pathlib.Path(__file__).resolve().parent
        service = (here.parent / "Service.qml").read_text()
        block = service[service.index("  // ---- Before sleep."):service.index("  function unloadPlayer()")]
        line = 'readonly property var sleepGuardCommand: python === "" ? [] : Model.sleepGuardCommand(python, bridge)'
        self.assertEqual(block.count(line), 1)
        block = block.replace(line, "readonly property var sleepGuardCommand: " + json.dumps(command))
        with tempfile.TemporaryDirectory(prefix="legato-qs-", dir=short_temp_dir()) as tmp:
            shell = pathlib.Path(tmp) / "shell"
            shell.mkdir()
            (shell / "shell.qml").write_text(shell_text.replace("%BLOCK%", block))
            env = {"PATH": "/usr/bin", "HOME": tmp, "XDG_RUNTIME_DIR": tmp, "XDG_CACHE_HOME": tmp + "/cache",
                   "XDG_STATE_HOME": tmp + "/state", "XDG_DATA_HOME": tmp + "/data", "XDG_CONFIG_HOME": tmp + "/config",
                   "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": ""}
            done = subprocess.run([quickshell, "-p", str(shell)], env=env, capture_output=True, text=True, timeout=30)
        out = done.stdout + done.stderr
        for pid in re.findall(r"GUARD PID (\d+)", out):  # (none should outlive the shell: setpriv --pdeathsig)
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        return out

    def test_a_sleep_guard_killed_by_someone_else_is_counted_and_comes_back(self):
        # Strict review 22 (fit F2): a SIGTERM from outside (a kill of
        # systemd-inhibit) was taken for Legato's own stop: not counted, no
        # restart, pause before sleep off for the rest of the episode.
        shell = self.SHELL.replace("%s", "%BLOCK%").replace(
            "    Component.onCompleted: guardRetryBaseMs = 50", """    Component.onCompleted: { guardRetryBaseMs = 50; startWatchdogMs = 3000 }
    property var firstPid: null
    Process { id: killer; command: ["/usr/bin/kill", "-TERM", String(root.firstPid)] }
    Connections {
      target: sleepGuard
      function onStarted() { console.warn("GUARD PID " + sleepGuard.processId) }
    }
    Timer {
      interval: 800; running: true
      onTriggered: { root.firstPid = sleepGuard.processId; killer.running = true }
    }""").replace("interval: 6000; running: true", "interval: 2500; running: true").replace(
            'console.warn("RESULT failures=" + root._guardFailures + " reports=" + root.reports)',
            'console.warn("RESULT failures=" + root._guardFailures + " again=" + (sleepGuard.processId !== null && sleepGuard.processId !== root.firstPid))')
        out = self.run_guard_block(shell, ["/usr/bin/setpriv", "--pdeathsig", "KILL", "/usr/bin/sleep", "30"])
        self.assertIn("RESULT failures=1 again=true", out, out[-2000:])

    def test_a_sleep_guard_that_never_starts_is_counted_and_said(self):
        out = self.run_guard_block(self.SHELL.replace("%s", "%BLOCK%"), ["/nonexistent/legato-guard-probe"])
        result = re.search(r"RESULT failures=(\d+) reports=(\d+)", out)
        self.assertIsNotNone(result, out[-2000:])
        # Five tries (waits of 50 ms doubling, 400 ms each to be judged), then
        # said once and no more tries.
        self.assertEqual(result.groups(), ("5", "1"), out[-2000:])
        self.assertIn("RESET failures=0", out)
        self.assertEqual(out.count("REPORT Couldn't set up pause-before-sleep"), 1)


class PrefsLock(TempHome):
    """prefs.json is changed from several processes at once (a click, the
    bar's poll); none may undo another's change."""

    def test_learning_the_window_spot_never_undoes_a_toggle(self):
        stale = bridge.load_prefs()   # a poll read prefs...
        run_bridge("boost", "on")     # ...a toggle landed meanwhile...
        moved = [{"class": "legato-video", "pinned": True, "at": [900, 600], "size": [300, 170]}]
        with mock.patch.object(bridge, "hyprctl", lambda *a: json.dumps(moved)):
            bridge.remember_video_geometry(stale)  # ...and the poll saves where the window went
        prefs = bridge.load_prefs()
        self.assertIs(prefs["boost"], True)
        self.assertEqual(prefs["videoGeometry"], {"x": 900, "y": 600, "w": 300, "h": 170})

    def test_changes_wait_for_each_other(self):
        done = []
        with bridge.StateLock(name="prefs.lock"):
            worker = threading.Thread(target=lambda: done.append(run_bridge("trim", "mild")))
            worker.start()
            time.sleep(0.3)
            self.assertTrue(worker.is_alive())  # waiting its turn, not writing over
        worker.join(5)
        self.assertEqual(done[0]["data"]["trim"], "mild")
        self.assertEqual(bridge.load_prefs()["trim"], "mild")


class SettingsFile(TempHome):
    """The Settings page's settings live in settings.json in the state folder
    (SR86): Omarchy deletes the widget's bar entry, where they used to be,
    whenever the plugin is turned off. The entry is copied in once; a file
    that can't be read is never saved over."""

    def path(self):
        return os.path.join(self.home, ".local/state/omarchy-legato/settings.json")

    def write(self, text, mode=0o600):
        os.makedirs(os.path.dirname(self.path()), mode=0o700, exist_ok=True)
        with open(self.path(), "w") as f:
            f.write(text)
        os.chmod(self.path(), mode)

    def saved(self):
        with open(self.path()) as f:
            return json.load(f)

    def test_the_schema_is_the_manifests_and_its_defaults_are_valid(self):
        schema = bridge.settings_schema()
        manifest = json.loads((ROOT / "manifest.json").read_text())["legatoSettings"]
        self.assertEqual([e["key"] for e in schema], [e["key"] for e in manifest["schema"]])
        for entry in schema:
            self.assertEqual(bridge.setting_value(entry, entry["defaultValue"]), entry["defaultValue"], entry["key"])
            self.assertEqual(manifest["defaults"][entry["key"]], entry["defaultValue"], entry["key"])
        self.assertEqual(set(bridge.SETTINGS_SAFE) - {e["key"] for e in schema}, set())

    def test_no_file_reads_the_defaults(self):
        # Before the old bar entry has been copied in, the two that act stay
        # off (a 1.0 user's "autoplay off" may be on its way: strict review
        # 11); once it has, no file means the defaults.
        view = run_bridge("settings")["data"]
        self.assertEqual((view["values"]["autoplay"], view["values"]["unloadAfterMinutes"]), (False, 0))
        self.assertEqual(view["values"]["skipForward"], 30)
        self.assertEqual((view["stored"], view["writable"], view["problem"]), (False, True, ""))
        self.assertEqual(view["path"], "~/.local/state/omarchy-legato/settings.json")
        self.assertFalse(os.path.exists(self.path()))  # reading writes nothing
        self.assertEqual(run_bridge("status")["data"]["settings"], view)
        self.assertIsNone(bridge.setting_now("autoplay"))  # before the import, the caller's choice decides
        run_bridge("settings", "import", "--", "{}")
        os.remove(self.path())
        view = run_bridge("settings")["data"]
        self.assertEqual((view["values"]["autoplay"], view["values"]["unloadAfterMinutes"]), (True, 15))

    def test_the_bar_entry_is_copied_once(self):
        entry = {"id": "io.github.cwilliams5.legato", "autoplay": False, "skipBack": 20, "maxLabelWidth": 5000,
                 "defaultTab": "nowhere", "junk": 1}
        view = run_bridge("settings", "import", "--", json.dumps(entry))["data"]
        # Settings only, and valid (a number past the range at its end: round 16).
        self.assertEqual(self.saved(), {"autoplay": False, "skipBack": 20, "maxLabelWidth": 600})
        self.assertEqual((view["values"]["autoplay"], view["values"]["skipBack"], view["stored"]), (False, 20, True))
        self.assertEqual(oct(os.stat(self.path()).st_mode & 0o777), "0o600")
        run_bridge("settings", "import", "--", json.dumps({"autoplay": True, "skipBack": 30}))
        self.assertEqual(self.saved(), {"autoplay": False, "skipBack": 20, "maxLabelWidth": 600})  # a second start changes nothing
        # Deleted later (to reset, or a broken one): the old entry is never
        # copied in again (strict review 10); the defaults hold.
        os.remove(self.path())
        view = run_bridge("settings", "import", "--", json.dumps({"autoplay": False}))["data"]
        self.assertFalse(os.path.exists(self.path()))
        self.assertIs(view["stored"], True)
        self.assertIs(view["values"]["autoplay"], True)

    def test_an_import_never_overwrites_a_file_made_first(self):
        run_bridge("settings", "set", "--", "skipBack", "20")  # a script got there first
        run_bridge("settings", "import", "--", json.dumps({"skipBack": 30, "autoplay": False}))
        self.assertEqual(self.saved(), {"skipBack": 20})

    def test_1_0s_text_values_are_imported(self):
        # Strict review 11 (L1): `omarchy bar set` without --json stores text,
        # and 1.0 read numbers from it; the import dropped them.
        run_bridge("settings", "import", "--", json.dumps({"unloadAfterMinutes": "0", "skipBack": "15",
                                                           "autoplay": "false", "showTitle": "true", "maxLabelWidth": "x"}))
        self.assertEqual(self.saved(), {"unloadAfterMinutes": 0, "skipBack": 15, "autoplay": False, "showTitle": True})

    def test_1_0s_values_outside_the_range_are_brought_to_its_ends(self):
        # Strict review 16 (L5): 1.0 used any number the bar entry held; the
        # import dropped them for the defaults, silently.
        run_bridge("settings", "import", "--", json.dumps({"skipBack": 3, "maxLabelWidth": 1000}))
        schema = {e["key"]: e for e in bridge.settings_schema()}
        self.assertEqual(self.saved(), {"skipBack": schema["skipBack"]["min"], "maxLabelWidth": schema["maxLabelWidth"]["max"]})

    def test_a_fresh_entry_still_creates_the_file(self):
        run_bridge("settings", "import", "--", json.dumps({"id": "io.github.cwilliams5.legato"}))
        self.assertEqual(self.saved(), {})
        self.assertIs(run_bridge("settings")["data"]["stored"], True)

    def test_a_change_is_checked_and_keeps_the_rest(self):
        self.write(json.dumps({"skipBack": 20, "note": "mine", "autoplay": "yes"}), 0o644)  # an editor's 0644 is fine
        view = run_bridge("settings")["data"]
        self.assertTrue(view["writable"])
        self.assertIs(view["values"]["autoplay"], False)  # not valid: off, never on by a typo...
        self.assertIn("autoplay", view["problem"])         # ...and said
        self.assertIn("note not a setting", view["problem"])  # a key it doesn't know: said, kept
        self.assertEqual(view["values"]["skipBack"], 20)
        view = run_bridge("settings", "set", "--", "skipForward", "45")["data"]
        self.assertEqual(self.saved(), {"skipBack": 20, "note": "mine", "autoplay": "yes", "skipForward": 45})
        self.assertEqual(view["values"]["skipForward"], 45)
        for key, value in (("skipForward", "4"), ("skipForward", "301"), ("skipForward", "true"), ("unloadAfterMinutes", "true"), ("skipForward", "\"30\""),
                           ("autoplay", "1"), ("defaultTab", "\"nowhere\""), ("nope", "1"), ("skipBack", "{")):
            result = run_bridge("settings", "set", "--", key, value)
            self.assertFalse(result["ok"], (key, value))
        self.assertEqual(self.saved()["skipForward"], 45)
        self.assertFalse(run_bridge("settings", "set", "--", "skipBack")["ok"])
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            run_bridge("settings", "nonsense")  # argparse refuses it, as any unknown subcommand word
        run_bridge("settings", "set", "--", "maxLabelWidth", "240.0")  # a whole number written as a float
        self.assertEqual(self.saved()["maxLabelWidth"], 240)

    def test_a_file_that_cant_be_read_is_never_saved_over(self):
        for text in ("{bad", "[1, 2]", "\xff"):
            with self.subTest(text=text):
                self.write(text)
                view = run_bridge("settings")["data"]
                self.assertFalse(view["writable"])
                self.assertTrue(view["stored"])
                self.assertIn("settings.json", view["problem"])
                self.assertEqual((view["values"]["autoplay"], view["values"]["unloadAfterMinutes"]), (False, 0))
                self.assertEqual(view["values"]["pauseOnSleep"], True)
                result = run_bridge("settings", "set", "--", "skipBack", "20")
                self.assertEqual(result["code"], "settings_unreadable")
                run_bridge("settings", "import", "--", json.dumps({"skipBack": 20}))
                with open(self.path(), encoding="utf-8", errors="replace") as f:
                    self.assertEqual(f.read(), text.encode("utf-8").decode("utf-8", "replace"))
        self.write("{}", 0o666)  # others can write it: not trusted
        self.assertFalse(run_bridge("settings")["data"]["writable"])
        os.remove(self.path())
        os.symlink("/etc/hostname", self.path())
        view = run_bridge("settings")["data"]
        self.assertFalse(view["writable"])
        self.assertIn("symbolic link", view["problem"])

    def test_an_empty_show_list_isnt_kept(self):
        # Strict review 12 (L2): cached ten minutes, it said "not followed"
        # for every show.
        with mock.patch.object(bridge, "api", lambda path, body=None: {"podcasts": []}):
            self.assertEqual(bridge.subscriptions(force=True), [])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local/state/omarchy-legato/podcasts-cache.json")))
        self.assertLess(bridge.MPV_PROPERTIES.index("time-pos"), bridge.MPV_PROPERTIES.index("path"))  # L5

    def test_the_bridge_acts_on_the_safe_value_when_it_cant_tell(self):
        with mock.patch.object(bridge, "settings_schema", side_effect=OSError("gone")):
            self.assertIs(bridge.setting_now("autoplay"), False)
            self.assertEqual(bridge.setting_now("unloadAfterMinutes"), 0)
            self.assertIsNone(bridge.setting_now("pauseOnSleep"))  # not False: the guard still pauses

    def test_status_answers_even_without_the_schema(self):
        with mock.patch.object(bridge, "settings_schema", side_effect=OSError("gone")):
            view = run_bridge("status")["data"]["settings"]
        self.assertFalse(view["writable"])
        self.assertEqual(view["values"], bridge.SETTINGS_SAFE)

    def test_changes_wait_for_each_other(self):
        done = []
        with bridge.StateLock(name="settings.lock"):
            worker = threading.Thread(target=lambda: done.append(run_bridge("settings", "set", "--", "skipBack", "20")))
            worker.start()
            time.sleep(0.3)
            self.assertTrue(worker.is_alive())
            self.write(json.dumps({"skipForward": 45}))  # another change, saved meanwhile
        worker.join(5)
        self.assertTrue(done[0]["ok"])
        self.assertEqual(self.saved(), {"skipForward": 45, "skipBack": 20})  # read again under the lock


REAL_FEED_ADDRESS_ALLOWED = bridge.feed_address_allowed


class FeedProxyRules(TempHome):
    """Feeds can't point mpv at this computer, or (unless allowed) at the
    local network: checked by the proxy at every connection."""

    def test_which_addresses_may_be_fetched(self):
        allowed = REAL_FEED_ADDRESS_ALLOWED
        for address in ("8.8.8.8", "2606:4700::1111", "151.101.1.1"):
            self.assertTrue(allowed(address, False), address)
        for address in ("192.168.1.5", "10.0.0.2", "172.16.0.1", "100.101.102.103", "fd7a:115c:a1e0::1",
                        "::ffff:192.168.1.1"):
            self.assertFalse(allowed(address, False), address)
            self.assertTrue(allowed(address, True), address)  # a home server, when allowed
        for address in ("127.0.0.1", "::1", "169.254.169.254", "fe80::1", "0.0.0.0", "224.0.0.1",
                        "255.255.255.255", "not an address"):
            self.assertFalse(allowed(address, True), address)  # never, even when allowed

    def ask(self, proxy, request):
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=3) as sock:
            sock.sendall(request.encode())
            return sock.recv(512).decode("latin-1")

    def test_the_proxy_wants_its_password_and_refuses_this_computer(self):
        proxy = bridge.FeedProxy("cd" * 16, allow_local=lambda: True)  # the real address rules
        stop_r, stop_w = os.pipe()
        threading.Thread(target=proxy.serve, kwargs={"stop_fd": stop_r}, daemon=True).start()
        self.addCleanup(os.write, stop_w, b"x")
        auth = "Proxy-Authorization: Basic %s\r\n" % base64.b64encode(("legato:" + "cd" * 16).encode()).decode()
        target = socket.socket()
        target.bind(("127.0.0.1", 0))
        target.listen(1)
        self.addCleanup(target.close)
        port = target.getsockname()[1]
        self.assertTrue(self.ask(proxy, "CONNECT 127.0.0.1:%d HTTP/1.1\r\n\r\n" % port).startswith("HTTP/1.1 407"))
        self.assertTrue(self.ask(proxy, "CONNECT 127.0.0.1:%d HTTP/1.1\r\n%s\r\n" % (port, auth)).startswith("HTTP/1.1 403"))
        self.assertTrue(self.ask(proxy, "GET http://localhost:%d/x HTTP/1.1\r\n%s\r\n" % (port, auth)).startswith("HTTP/1.1 403"))
        self.assertTrue(self.ask(proxy, "LEGATO-PING / HTTP/1.1\r\n%s\r\n" % auth).startswith("HTTP/1.1 204"))
        self.assertTrue(bridge.proxy_alive(proxy.url()))
        self.assertFalse(bridge.proxy_alive(proxy.url().replace("cd" * 16, "ef" * 16)))

    def test_the_proxy_never_reaches_this_computer_by_its_other_addresses(self):
        # Strict review 15 (M2): with local network feeds on, this computer's
        # own Wi-Fi, docker and tailnet addresses were "the local network",
        # and a feed (or a redirect in its chain) reached services listening
        # here. A connection to oneself shows one address at both ends.
        data = json.loads(subprocess.run(["/usr/bin/ip", "-4", "-j", "addr", "show", "scope", "global"],
                                         capture_output=True, text=True, timeout=5).stdout or "[]")
        addrs = [a["local"] for link in data for a in link.get("addr_info", []) if a.get("family") == "inet"]
        if not addrs:
            self.skipTest("no address here but loopback")
        listener = socket.socket()
        listener.bind(("0.0.0.0", 0))
        listener.listen(8)
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]
        for addr in addrs:
            self.assertTrue(bridge.feed_address_allowed(addr, True), addr)  # (the class alone allows it)
            with self.assertRaises(bridge.FeedRefused, msg=addr):
                bridge.connect_feed_host(addr, port, True).close()
        self.assertTrue(bridge.same_address("fe80::1%wlan0", "fe80::1"))
        self.assertFalse(bridge.same_address("192.168.1.2", "192.168.1.3"))

    def test_the_proxy_process_ends_with_its_player(self):
        player = subprocess.Popen(["sleep", "60"])
        self.addCleanup(player.kill)
        url = bridge.start_feed_proxy(player.pid)
        self.assertTrue(bridge.proxy_alive(url))
        self.assertNotIn(url.split("@")[0].split(":")[-1], " ".join(open("/proc/%d/cmdline" % player.pid).read()))
        player.kill()
        player.wait()
        deadline = time.monotonic() + 3
        while bridge.proxy_alive(url) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(bridge.proxy_alive(url))

    def test_a_local_episode_says_why_it_wont_play(self):
        def resolving(address):
            return lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]
        with mock.patch.object(bridge, "resolve_feed_host", resolving("100.101.102.103")):
            with self.assertRaises(bridge.ApiError) as raised:
                bridge.check_feed_host("http://server.tailnet.example:8585/a.mp3", {})
            self.assertIn("local network", raised.exception.message)
            bridge.check_feed_host("http://server.tailnet.example:8585/a.mp3", {"localFeeds": True})  # allowed
        with mock.patch.object(bridge, "resolve_feed_host", resolving("127.0.0.1")):
            with self.assertRaises(bridge.ApiError) as raised:
                bridge.check_feed_host("http://localhost/a.mp3", {"localFeeds": True})
            self.assertIn("this computer", raised.exception.message)
        with mock.patch.object(bridge, "resolve_feed_host", resolving("151.101.1.1")):
            bridge.check_feed_host("https://cdn.example/a.mp3", {})

    def test_the_setting_is_kept_with_the_players_choices(self):
        self.assertFalse(bridge.local_feeds_allowed(bridge.load_prefs()))
        self.assertTrue(run_bridge("localfeeds", "on")["data"]["localFeeds"])
        self.assertIs(bridge.load_prefs()["localFeeds"], True)
        self.assertFalse(run_bridge("localfeeds", "toggle")["data"]["localFeeds"])


class Paste(TempHome):
    """The sign-in fields' paste (legato-bridge paste): bounded in size and
    time, and nothing of wl-paste's left running afterwards."""

    def fake_wl_paste(self, body):
        path = os.path.join(self.home, "wl-paste")
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def paste(self, body, *args):
        tool = self.fake_wl_paste(body)
        before = signal.getsignal(signal.SIGTERM)
        try:
            with mock.patch.object(bridge, "trusted_tool", lambda name: tool if name == "wl-paste" else ""):
                return run_bridge("paste", *args)
        finally:
            signal.signal(signal.SIGTERM, before)

    def survivors(self, *commands):
        # Exact command lines: a looser pattern also matches whatever shell
        # happens to have that text in its own command line.
        found = []
        for command in commands:
            found += subprocess.run(["pgrep", "-x", "-f", command], capture_output=True, text=True).stdout.split()
        return found

    def test_text_comes_back_on_one_line(self):
        result = self.paste("printf 'me@example.com\\n'")
        self.assertEqual(result["data"]["text"], "me@example.com")
        self.assertEqual(self.paste("printf ' pass word '")["data"]["text"], " pass word ")  # spaces are kept

    def test_too_much_is_refused(self):
        result = self.paste("head -c 5000 /dev/zero | tr '\\0' a")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "paste_too_long")

    def test_a_clipboard_that_never_answers_times_out_and_leaves_nothing_behind(self):
        child, waiter = "sleep %d.%03d" % (40 + os.getpid() % 50, os.getpid() % 997), "sleep 99.%03d" % (os.getpid() % 997)
        started = time.monotonic()
        # Like wl-paste forking cat: a child holding the pipe open, then a wait.
        result = self.paste("%s & %s" % (child, waiter))
        self.assertLess(time.monotonic() - started, bridge.PASTE_TIMEOUT + 2)
        self.assertEqual(result["code"], "paste_timeout")
        time.sleep(0.2)
        self.assertEqual(self.survivors(child, waiter), [])

    def test_primary_selection_is_asked_for_on_middle_click(self):
        result = self.paste('for a in "$@"; do [ "$a" = --primary ] && printf primary && exit; done; printf clipboard', "--primary")
        self.assertEqual(result["data"]["text"], "primary")


class CoverArt(TempHome):
    def test_only_real_images_are_cached(self):
        url = bridge.podcast_art("11111111-1111-1111-1111-111111111111")
        self.assertTrue(bridge.art_url_allowed(url))
        with mock.patch.object(bridge, "http_raw", lambda *a, **k: (200, b"<html>not a cover</html>", {})):
            self.assertEqual(bridge.cache_one(url), "")
        jpeg = b"\xff\xd8\xff\xe0" + b"\0" * 64
        with mock.patch.object(bridge, "http_raw", lambda *a, **k: (200, jpeg, {})):
            path = bridge.cache_one(url)
        self.assertTrue(path.endswith(".jpg"))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), jpeg)
        self.assertLessEqual(bridge.ART_MAX_BYTES, 1024 * 1024)


class Deadline(TempHome):
    def test_a_stuck_call_ends_with_an_error_and_lets_go(self):
        # Review finding: no overall deadline. A call waiting (here on the
        # state lock another call holds) gives up after BRIDGE_DEADLINE.
        with mock.patch.object(bridge, "BRIDGE_DEADLINE", 1), bridge.StateLock():
            started = time.monotonic()
            result = run_bridge("seek", "10")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "timeout")
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(signal.alarm(0), 0)  # nothing left armed

    def test_the_deadline_isnt_swallowed_by_handlers_that_shrug_off_errors(self):
        self.assertFalse(issubclass(bridge.DeadlinePassed, Exception))


class AboutTests(TempHome):
    """The About page's privacy statement (About.js) has to name every host the
    plugin can reach, so adding one without saying so fails here."""

    # URLs that appear in shipped code but are never requested by the plugin.
    NOT_CONTACTED = {
        "github.com": "the User-Agent string, and About's Report button (opens the browser; the plugin sends nothing)",
        "www.w3.org": "the SVG namespace in the logo files; never fetched",
    }

    def privacy(self):
        # The statement is a run of "..." + "..." literals; join them back up.
        about = (ROOT / "About.js").read_text(encoding="utf-8")
        block = about[about.index("var PRIVACY"):about.index("function manifestVersion")]
        block = block[:block.index("\n\n")]
        return "".join(json.loads(lit) for lit in re.findall(r'"(?:[^"\\]|\\.)*"', block))

    def test_privacy_names_the_bridge_hosts(self):
        privacy = self.privacy()
        for url in (bridge.API, bridge.PODCAST_API, bridge.ART_BASE):
            self.assertIn(urllib.parse.urlsplit(url).hostname, privacy)
        self.assertIn(bridge.API_HOST, privacy)
        for host in bridge.SHOW_HOSTS:
            self.assertIn(host, privacy)
        # ART_HOST_RE is one exact host, written as a regex.
        self.assertRegex(bridge.ART_HOST_RE.pattern, r"^\^[a-z\\.]+\$$")
        self.assertIn(bridge.ART_HOST_RE.pattern[1:-1].replace("\\.", "."), privacy)
        # Audio is the one thing fetched from elsewhere: by mpv, from the feed.
        self.assertIn("each podcast's own server", privacy)
        self.assertIn("No telemetry", privacy)

    def test_privacy_names_every_url_in_shipped_code(self):
        privacy = self.privacy()
        hosts = set()
        for path in sorted(ROOT.rglob("*")):
            rel = str(path.relative_to(ROOT))
            if not path.is_file() or rel.startswith((".git", "tests/")) or path.suffix in (".png", ".md"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            hosts.update(re.findall(r"https?://([A-Za-z0-9.-]+)", text))
        self.assertIn("api.pocketcasts.com", hosts)
        for host in sorted(hosts):
            if host in self.NOT_CONTACTED:
                continue
            self.assertIn(host, privacy, "%s is reachable but not named in About.js PRIVACY" % host)

    def test_privacy_matches_what_is_kept_and_synced(self):
        privacy = self.privacy()
        self.assertIn("~/.local/state/omarchy-legato/auth.json", privacy)
        self.assertIn("0600", privacy)
        self.assertIn("~/.cache/omarchy-legato/art", privacy)
        self.assertIn("your settings", privacy)  # settings.json, beside auth.json
        self.assertNotIn("shell.json", privacy)  # no longer kept in the bar entry (SR86)
        self.assertIn("password is never stored", privacy)
        self.assertIn("every %d seconds" % bridge.SYNC_INTERVAL, privacy)
        # The show list is reused for PODCASTS_CACHE_SECONDS but kept however old
        # (cached_subscriptions: the fallback for an empty list, strict review 22).
        self.assertIn("the last list of your shows that loaded", privacy)
        self.assertNotIn("%d-minute" % (bridge.PODCASTS_CACHE_SECONDS // 60), privacy)

    def test_status_reports_the_python_version(self):
        result = run_bridge("status")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["python"], "%d.%d.%d" % sys.version_info[:3])


def make_cert(folder):
    """A certificate for 127.0.0.1, for the TLS host (mpv verifies it against
    this file: --tls-ca-file, verification stays on)."""
    key, cert = os.path.join(folder, "key.pem"), os.path.join(folder, "cert.pem")
    subprocess.run(["/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key,
                    "-out", cert, "-days", "2", "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1"],
                   check=True, capture_output=True)
    return key, cert


@NEEDS_PLAYER
@unittest.skipUnless(os.path.exists("/usr/bin/openssl"), "needs openssl for the TLS host")
class HttpsStreams(PlayerTestCase):
    """Strict review 5: the ordinary podcast host is https. A connection that
    drops without TLS's close_notify (a network, a CDN edge going) or a link
    that goes silent never logs FFmpeg's "Stream ends prematurely" line;
    both log "Will reconnect at N". The same fake host, behind TLS."""

    AUDIO_SECONDS = 30

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tls_dir = tempfile.mkdtemp(prefix="legato-tls-")
        key, cls.cert = make_cert(cls.tls_dir)
        cls.tls = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakePocketCasts)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cls.cert, key)
        cls.tls.socket = context.wrap_socket(cls.tls.socket, server_side=True)
        threading.Thread(target=cls.tls.serve_forever, daemon=True).start()
        cls.tls_base = "https://127.0.0.1:%d" % cls.tls.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.tls.shutdown()
        cls.tls.server_close()
        shutil.rmtree(cls.tls_dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        for uuid, episode in self.fake["episodes"].items():
            episode["duration"] = self.AUDIO_SECONDS
            episode["url"] = self.tls_base + "/audio/%s.mp3" % uuid
        patcher = mock.patch.object(bridge, "MPV_EXTRA_ARGS", ("--ao=null", "--tls-ca-file=" + self.cert))
        patcher.start()
        self.addCleanup(patcher.stop)

    def settled(self, uuid=EP_1, timeout=60):
        return self.wait_for(lambda: (lambda v: v if v.get("streamBroke") or v.get("ended")
                                      or (v["item"] or {}).get("uuid") != uuid else None)(run_bridge("player")["data"]),
                             timeout=timeout)

    def test_pocket_casts_https_sends_nothing_across_a_suspend(self):
        # Strict review 14 (F3): Pocket Casts is https; the suite's API runs
        # over plain http, so the https connection's own suspend check never
        # ran. The production opener (https only), against a TLS host: sent
        # normally; a call that slept sends nothing.
        real = ssl.create_default_context
        with mock.patch.object(bridge.ssl, "create_default_context", lambda *a, **k: real(cafile=self.cert)):
            opener = bridge.build_opener()

        def push():
            request = urllib.request.Request(self.tls_base + "/sync/update_episode", data=b'{"uuid": "x"}',
                                             method="POST", headers={"Content-Type": "application/json"})
            try:
                opener.open(request, timeout=5).close()
            except urllib.error.HTTPError:
                pass  # (the fake refuses it unsigned: it was sent all the same)
        push()
        self.assertEqual(len(self.writes("/sync/update_episode")), 1)
        with mock.patch.object(bridge, "sleep_offset", lambda: bridge._SLEEP_BASE + 600):
            with self.assertRaises(bridge.ApiError) as ctx:
                push()
        self.assertEqual(ctx.exception.code, "slept")
        self.assertEqual(len(self.writes("/sync/update_episode")), 1)

    def assert_broke(self, view):
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)

    def test_an_https_stream_that_drops_part_way_is_not_finished(self):
        self.fake["cut"] = {EP_1: int(len(self.audio) * 0.6)}  # past half  # closed without close_notify
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assert_broke(self.settled())

    def test_an_https_stream_whose_reconnect_gets_a_503_is_not_finished(self):
        self.fake["cut"] = {EP_1: int(len(self.audio) * 0.6)}  # past half
        self.fake["cutReply"] = 503
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assert_broke(self.settled())

    def test_an_https_stream_that_stalls_then_closes_is_not_finished(self):
        self.fake["hang"] = {EP_1: len(self.audio) // 5}
        self.fake["hangFor"] = 8
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assert_broke(self.settled())

    def test_an_https_stream_played_to_its_end_is_finished(self):
        self.fake["progress"][EP_1] = 25
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.settled()
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_an_https_m4a_with_its_index_at_the_back_ends_properly(self):
        # Several range requests (the index at the back first): none of them
        # a failure, so a real end.
        self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=600", "-c:a", "aac", "-b:a", "32k"], ".m4a")}
        self.fake["episodes"][EP_1].update(duration=600, url=self.tls_base + "/audio/%s.m4a" % EP_1)
        self.fake["progress"][EP_1] = 595
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.settled()
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_play_after_an_https_break_never_pushes_zero(self):
        self.fake["upnext"] = [EP_1]  # nothing to autoplay
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.settled()
        self.fake["cut"] = {}  # the network is back
        before = len(self.writes("/sync/update_episode"))
        run_bridge("toggle")
        self.assertNotIn(0, [b["position"] for b in self.writes("/sync/update_episode")[before:] if b["uuid"] == EP_1])

    def test_an_https_stream_from_a_host_without_ranges_that_drops_is_not_finished(self):
        # Strict review 6: FFmpeg can't reconnect such a stream, and an https
        # drop logs no short-end line: judged by how far mpv read.
        self.fake["noranges"] = {EP_1}
        self.fake["cut"] = {EP_1: int(len(self.audio) * 0.6)}  # past half
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assert_broke(self.settled())

    def test_an_https_stream_from_a_host_without_ranges_that_stalls_is_not_finished(self):
        self.fake["hang"] = {EP_1: int(len(self.audio) * 0.6)}  # past half
        self.fake["hangNoRanges"] = True
        self.fake["hangFor"] = 8
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assert_broke(self.settled())

    def test_an_https_host_without_ranges_still_ends_properly(self):
        self.fake["noranges"] = {EP_1}
        bridge.save_prefs({"volume": 0, "speed": 3.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.settled()
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_an_m4a_that_cant_play_without_ranges_is_never_marked_played(self):
        # Its index is at the back, and the host can't seek there: mpv stops
        # at 0:00 having read nothing. Not the end.
        self.fake["noranges"] = {EP_1}
        self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=60", "-c:a", "aac", "-b:a", "32k"], ".m4a")}
        self.fake["episodes"][EP_1].update(duration=60, url=self.tls_base + "/audio/%s.m4a" % EP_1)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assert_broke(self.settled())

    def test_a_reconnect_that_works_plays_on_to_a_real_end(self):
        # The link drops and comes back: FFmpeg's reconnect reads on, so the
        # line it logged is old news and the real end is the end.
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
        self.fake["cutHeal"] = True
        bridge.save_prefs({"volume": 0, "speed": 3.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.settled()
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_an_m4a_with_its_index_at_the_back_ends_after_a_drop_that_recovered(self):
        # Strict review 9: the drop's TLS error set `failed`, nothing cleared
        # it, and mpv never reads such a file to its size: never finished.
        self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=600", "-c:a", "aac", "-b:a", "32k"], ".m4a")}
        self.fake["episodes"][EP_1].update(duration=600, url=self.tls_base + "/audio/%s.m4a" % EP_1)
        blob = self.fake["media"][EP_1]
        # The audio ends about 96% in (the index fills the rest): the link
        # drops at 92.5%, about 0:09:39, and comes back.
        self.fake["progress"][EP_1] = 570
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.fake["cut"] = {EP_1: int(len(blob) * 0.925)}
        self.fake["cutHeal"] = True
        bridge.save_prefs({"volume": 0, "speed": 3.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.settled()
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_a_failed_seek_over_https_is_not_the_end(self):
        self.fake["media"] = {EP_1: encode(["-f", "lavfi", "-i", "sine=duration=40", "-b:a", "320k"], ".mp3")}
        for episode in self.fake["episodes"].values():
            episode["duration"] = 40
        self.fake["progress"][EP_1] = 30
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: (lambda v: v if v["playing"] and v["position"] > 31 else None)(run_bridge("player")["data"]),
                      timeout=20)
        self.fake["expired"] = 403
        run_bridge("seek", "--episode", EP_1, "--relative", "--", "-10")
        time.sleep(3)
        for _ in range(2):
            run_bridge("player")
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_a_reconnect_that_works_near_the_end_plays_on_to_it(self):
        self.fake["cut"] = {EP_1: len(self.audio) - 20000}  # within READ_PAST_CUT of the end
        self.fake["cutHeal"] = True
        self.fake["progress"][EP_1] = 24
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.settled()
        self.assertEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def stall_then_phone(self, **hang):
        self.fake["hang"] = {EP_1: len(self.audio) // 5}
        self.fake.update(hang)
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: (lambda v: v if v["buffering"] and v["position"] > 3 else None)(run_bridge("player")["data"]),
                      timeout=40)
        time.sleep(3)  # stuck longer than STALL_AFTER (2 s here)
        self.fake["progress"][EP_1] = 25  # you carried on with the phone

    def test_pausing_a_stalled_stream_never_rewinds_the_phone(self):
        # Strict review 6: the pause (and Stop, Next, a switch, the sleep
        # guard) pushed where the stalled stream got stuck. Review 7: and the
        # poll the pause sets off.
        with mock.patch.object(bridge, "STALL_AFTER", 2):
            self.stall_then_phone(hangFor=60)
            run_bridge("pause")
            run_bridge("player")  # the poll mpv's pause event brings
            self.assertEqual(self.fake["progress"][EP_1], 25)
            run_bridge("stop")
            self.assertEqual(self.fake["progress"][EP_1], 25)

    def test_a_pause_after_a_stall_heals_pushes_nothing_unasked(self):
        # Strict review 7: the stall ends, you pause before any poll asked:
        # the poll the pause brings pushed the stale place.
        with mock.patch.object(bridge, "STALL_AFTER", 2):
            self.stall_then_phone(hangFor=12, hangResume=True)
            with bridge.Mpv.connect() as player:
                self.wait_for(lambda: player.get("paused-for-cache") is False, timeout=30)
            run_bridge("pause")
            run_bridge("player")
            self.assertEqual(self.fake["progress"][EP_1], 25)

    def test_after_a_stall_heals_pocket_casts_is_asked_first(self):
        with mock.patch.object(bridge, "STALL_AFTER", 2):
            self.stall_then_phone(hangFor=12, hangResume=True)  # longer than the 6 s cached
            view = self.wait_for(lambda: (lambda v: v if not v["buffering"] and v["playing"] else None)(run_bridge("player")["data"]),
                                 timeout=30)
            run_bridge("player")
            self.assertGreater(run_bridge("player")["data"]["position"], 24)  # it followed the phone
            # Asked once: from then on it syncs as usual.
            self.wait_for(lambda: (lambda v: v if v["playing"] and v["position"] > 26.5 else None)(run_bridge("player")["data"]))
            state = bridge.load_playback()
            state["lastSyncAt"] = time.time() - 31
            bridge.save_playback(state)
            before = len(self.pushes_of(EP_1))
            run_bridge("player")
            state = bridge.load_playback()
            self.assertEqual(len(self.pushes_of(EP_1)), before + 1,
                             {k: state.get(k) for k in ("checkServer", "unconfirmed", "stallHandled", "position", "lastSyncPos")})
            run_bridge("pause")
            self.assertGreaterEqual(self.fake["progress"][EP_1], 25)

    def test_a_media_key_pause_after_a_stall_heals_pushes_nothing_unasked(self):
        # The pause comes straight to mpv (no sync_now): only the poll knows
        # the place is unconfirmed after the stall.
        with mock.patch.object(bridge, "STALL_AFTER", 2):
            self.stall_then_phone(hangFor=12, hangResume=True)
            with bridge.Mpv.connect() as player:
                self.wait_for(lambda: player.get("paused-for-cache") is False, timeout=30)
                player.set("pause", True)
            run_bridge("player")
            run_bridge("player")
            self.assertEqual(self.fake["progress"][EP_1], 25)

    def test_after_a_stall_a_rewind_on_the_phone_wins(self):
        # Strict review 9: the stuck place counted as a local one Pocket Casts
        # never got, and beat the phone's deliberate rewind.
        with mock.patch.object(bridge, "STALL_AFTER", 2):
            self.fake["hang"] = {EP_1: int(len(self.audio) * 0.6)}
            self.fake["hangFor"] = 22
            self.fake["hangResume"] = True
            self.login()
            self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
            self.wait_for(lambda: (lambda v: v if v["buffering"] and v["position"] > 15 else None)(run_bridge("player")["data"]),
                          timeout=40)
            time.sleep(3)
            self.fake["progress"][EP_1] = 5  # you went back, on the phone
            view = self.wait_for(lambda: (lambda v: v if not v["buffering"] and v["playing"] else None)(run_bridge("player")["data"]),
                                 timeout=40)
            run_bridge("player")
            self.assertLess(run_bridge("player")["data"]["position"], 10)

    def test_a_break_after_a_long_stall_pushes_nothing(self):
        # No poll sees the stall (it falls between two): the break's own push
        # must still know the position is stale.
        with mock.patch.object(bridge, "STALL_AFTER", 2):
            self.fake["hang"] = {EP_1: len(self.audio) // 5}
            self.fake["hangFor"] = 12
            self.login()
            self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
            with bridge.Mpv.connect() as player:
                self.wait_for(lambda: player.get("paused-for-cache") is True, timeout=30)
                time.sleep(3)
                self.fake["progress"][EP_1] = 25  # you carried on with the phone
                self.wait_for(lambda: player.get("eof-reached") is True, timeout=40)
            self.assert_broke(self.settled())
            self.assertEqual(self.fake["progress"][EP_1], 25)

    def test_a_stalled_https_stream_never_rewinds_the_phone(self):
        # The host stops sending and keeps the connection open: mpv waits.
        # You carry on with the phone; the laptop used to push the stall
        # every 30 s.
        self.fake["hang"] = {EP_1: len(self.audio) // 5}
        self.fake["hangFor"] = 90
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.wait_for(lambda: (lambda v: v if v["buffering"] and v["position"] > 3 else None)(run_bridge("player")["data"]),
                      timeout=40)
        time.sleep(3)
        self.fake["progress"][EP_1] = 25  # the phone listened on
        state = bridge.load_playback()
        state["lastSyncAt"] = time.time() - 31  # the 30 s push is due
        bridge.save_playback(state)
        run_bridge("player")
        self.assertGreaterEqual(self.fake["progress"][EP_1], 25)


@NEEDS_PLAYER
class StalledStream(PlayerTestCase):
    """Plain http; the link stalls part way and the reconnects get nothing.
    mpv's network timeout cut from Legato's 30 s to 3 s."""

    AUDIO_SECONDS = 30

    def setUp(self):
        super().setUp()
        for episode in self.fake["episodes"].values():
            episode["duration"] = self.AUDIO_SECONDS
        patcher = mock.patch.object(bridge, "MPV_EXTRA_ARGS", ("--ao=null", "--network-timeout=3"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_host_without_ranges_that_goes_silent_is_not_finished(self):
        # Strict review 6: no reconnect, and a timeout logs no short-end line.
        self.fake["hang"] = {EP_1: int(len(self.audio) * 0.6)}  # past half
        self.fake["hangNoRanges"] = True
        bridge.save_prefs({"volume": 0, "speed": 2.0})
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.wait_for(lambda: (lambda v: v if v.get("streamBroke") or v.get("ended")
                                      or (v["item"] or {}).get("uuid") != EP_1 else None)(run_bridge("player")["data"]),
                             timeout=90)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)

    def test_a_stream_that_stalls_part_way_is_not_finished(self):
        self.fake["hang"] = {EP_1: len(self.audio) // 5}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.wait_for(lambda: (lambda v: v if v.get("streamBroke") or v.get("ended")
                                      or (v["item"] or {}).get("uuid") != EP_1 else None)(run_bridge("player")["data"]),
                             timeout=90)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)


class Deadlines(TempHome):
    def run_slowly(self, argv, name):
        said = []

        def slow(args):
            time.sleep(1.5)
            bridge.out({"done": True})
        with mock.patch.object(bridge, "BRIDGE_DEADLINE", 1), mock.patch.object(bridge, name, slow), \
                mock.patch.object(bridge, "out", said.append), mock.patch.object(bridge, "fail", lambda code, *rest: said.append(code)):
            bridge.main(argv)
        return said

    def test_the_sleep_guard_and_the_feed_proxy_outlive_the_call_deadline(self):
        # Strict review 16 (M1): both run for as long as an episode is loaded;
        # under the deadline the guard restarted every two minutes (then gave
        # up: no pause before sleep) and the proxy died mid-episode.
        self.assertEqual(self.run_slowly(["sleepguard"], "cmd_sleepguard"), [{"done": True}])
        self.assertEqual(self.run_slowly(["proxy", "--watch-pid", "1"], "cmd_proxy"), [{"done": True}])
        self.assertEqual(self.run_slowly(["status"], "cmd_status"), ["timeout"])  # every other call has one


class PositionsThatArent(unittest.TestCase):
    def test_a_position_that_isnt_a_finite_number_from_0_is_no_answer(self):
        # Strict review 15 (N2): NaN (Python's json reads it) and negatives
        # passed as numbers and were read as "at 0".
        for bad in (float("nan"), float("inf"), -1, -0.5, True, "12", None):
            self.assertFalse(bridge.a_place(bad), bad)
        for good in (0, 0.0, 12, 3600.5):
            self.assertTrue(bridge.a_place(good), good)
        self.assertFalse(bridge.number(float("nan")))
        state = {"lastSyncPos": float("nan"), "position": 5}
        bridge.clean_playback(state)
        self.assertNotIn("lastSyncPos", state)

    def test_a_sync_time_in_the_future_is_a_gap_not_fresh(self):
        # Strict review 21 (L3): the wall clock stepped back (NTP correcting
        # one that ran ahead) read as fresh until it caught up.
        self.assertGreaterEqual(bridge.sync_age({"lastSyncAt": time.time() + 600}), bridge.RECHECK_AFTER)
        self.assertLess(bridge.sync_age({"lastSyncAt": time.time() - 5}), bridge.RECHECK_AFTER)


class Round5Units(TempHome):
    """Strict review 5's smaller findings and the guards its mutants slipped past."""

    def test_the_watcher_is_loaded_only_from_a_folder_nobody_else_writes(self):
        with tempfile.TemporaryDirectory() as plugin:
            folder = os.path.join(plugin, "bin")
            os.mkdir(folder, 0o755)
            with open(os.path.join(folder, "legato-watch.lua"), "w") as fh:
                fh.write("-- watcher")
            os.chmod(plugin, 0o755)
            with mock.patch.object(bridge, "__file__", os.path.join(folder, "legato-bridge")):
                self.assertEqual(bridge.watch_script(), os.path.join(os.path.realpath(folder), "legato-watch.lua"))
                os.chmod(folder, 0o775)  # group-writable: refused (the length rule then decides)
                self.assertEqual(bridge.watch_script(), "")

    def test_feed_connections_notice_a_dead_link(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        try:
            with mock.patch.object(bridge, "feed_address_allowed", lambda address, allow_local: True), \
                    mock.patch.object(bridge, "same_address", lambda a, b: False):  # (a connection to oneself)
                sock = bridge.connect_feed_host("127.0.0.1", server.getsockname()[1], False)
            with sock:
                self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE), 1)
                # A dead path fails within about a minute.
                idle, interval, count = (sock.getsockopt(socket.IPPROTO_TCP, getattr(socket, name))
                                         for name in ("TCP_KEEPIDLE", "TCP_KEEPINTVL", "TCP_KEEPCNT"))
                self.assertLessEqual(idle + interval * count, 75)
                self.assertGreaterEqual(idle, 15)  # and not a probe every few seconds on an idle (paused) stream
        finally:
            server.close()

    def test_the_sleep_guard_never_waits_for_the_auth_lock(self):
        # Another call refreshing on a slow link holds the auth lock: the
        # guard, which may not refresh anyway, doesn't wait for it (logind
        # waits 15 s at most).
        bridge.save_auth({"access_token": "old", "refresh_token": "r1", "expires_at": 0, "uuid": "u"})
        other = bridge.auth_lock()
        other.__enter__()
        try:
            with mock.patch.object(bridge, "REFRESH_ALLOWED", False):
                started = time.monotonic()
                with self.assertRaises(bridge.ApiError):
                    bridge.access_token(bridge.load_auth())
                self.assertLess(time.monotonic() - started, 2)
        finally:
            other.__exit__(None, None, None)

    def test_the_sleep_guard_gives_up_within_its_deadline(self):
        class Monitor:
            stdout = iter(())
            def terminate(self):
                pass
        alarm, term = signal.getsignal(signal.SIGALRM), signal.getsignal(signal.SIGTERM)
        try:
            with mock.patch.object(bridge, "trusted_tool", lambda name: "/usr/bin/true"), \
                    mock.patch.object(bridge.subprocess, "Popen", lambda *a, **k: Monitor()), \
                    mock.patch.object(bridge, "wait_for_sleep", lambda lines: True), \
                    mock.patch.object(bridge, "pause_for_sleep", lambda: time.sleep(5)), \
                    mock.patch.object(bridge, "SLEEP_GUARD_DEADLINE", 1):
                started = time.monotonic()
                with self.assertRaises(bridge.ApiError) as ctx:
                    bridge.cmd_sleepguard(None)
                self.assertEqual(ctx.exception.code, "sleepguard")
                self.assertLess(time.monotonic() - started, 3)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, alarm)
            signal.signal(signal.SIGTERM, term)

    def test_a_stale_call_never_flags_a_new_session_expired(self):
        # A call still holding the old session's tokens, after you signed out
        # and in again: its failed refresh mustn't mark the new one expired.
        bridge.save_auth({"access_token": "a2", "refresh_token": "r2", "expires_at": time.time() + 3600, "uuid": "u"})
        with self.assertRaises(bridge.ApiError):
            bridge.mark_needs_reauth({"access_token": "a1", "refresh_token": "r1", "uuid": "u"})
        self.assertNotIn("needs_reauth", bridge.load_auth())
        with self.assertRaises(bridge.ApiError):
            bridge.mark_needs_reauth(bridge.load_auth())
        self.assertTrue(bridge.load_auth()["needs_reauth"])

    def test_a_notification_carries_the_text_as_text(self):
        # Omarchy's OSD refuses a third-party plugin: errors with the panel
        # closed go out as desktop notifications. The text is one argument
        # after `--` (one beginning with a dash is still text), capped.
        sent = []
        with mock.patch.object(bridge, "trusted_tool", lambda name: "/usr/bin/" + name), \
                mock.patch.object(bridge.subprocess, "run", lambda argv, **kw: sent.append(argv)), \
                mock.patch.object(bridge, "out", lambda data: None):
            bridge.cmd_notify(argparse.Namespace(text="--exec rm  -rf\nnow"))
            bridge.cmd_notify(argparse.Namespace(text="x" * 1000))
            bridge.cmd_notify(argparse.Namespace(text="<a href='https://x.example'>Fix</a> & <b>now</b>"))
        self.assertEqual(sent[0], ["/usr/bin/notify-send", "--app-name=Legato", "--urgency=normal", "--", "Legato",
                                   "--exec rm -rf now"])
        self.assertEqual(len(sent[1][-1]), bridge.NOTIFY_MAX)
        # The body is markup to the notification daemon: shown as text.
        self.assertEqual(sent[2][-1], "&lt;a href='https://x.example'&gt;Fix&lt;/a&gt; &amp; &lt;b&gt;now&lt;/b&gt;")

    def test_stats_never_get_in_the_way(self):
        # A stats file that can't be written (a folder in its place) is left
        # alone; counting off writes nothing at all.
        bridge.save_prefs({"stats": False})
        bridge.add_stats(listened=10)
        stats_file = os.path.join(os.environ["XDG_STATE_HOME"], "omarchy-legato", "stats.json")
        self.assertFalse(os.path.exists(stats_file))
        bridge.save_prefs({"stats": True})
        os.makedirs(stats_file)
        bridge.add_stats(finished=1)  # raises nothing

    def test_the_limits_that_matter(self):
        self.assertLess(bridge.SLEEP_GUARD_DEADLINE, 15)  # logind waits 15 s at most here
        self.assertLessEqual(bridge.READ_TO_END, 8192)    # a break that close to the end would count as it

    def test_a_long_stall_isnt_hidden_by_a_short_one(self):
        # Strict review 7: the watcher kept only the latest stall, so a short
        # hiccup after a long stall (before any poll) hid it.
        now = time.time()
        long_then_short = {"stalls": [{"since": now - 40, "ended": now - 20}, {"since": now - 5, "ended": now - 4}]}
        self.assertEqual(bridge.stall_seen(long_then_short, {}), "ended")
        self.assertEqual(bridge.stalls_ended_by(long_then_short), now - 4)
        self.assertIsNone(bridge.stall_seen(long_then_short, {"stallHandled": now - 4}))  # handled
        self.assertEqual(bridge.stall_seen({"stallSince": now - 20}, {}), "now")
        self.assertIsNone(bridge.stall_seen({"stallSince": now - 3}, {}))  # a hiccup
        self.assertIsNone(bridge.stall_seen({"stalls": [{"since": now - 6, "ended": now - 4}]}, {}))

    def test_no_outro_without_a_listed_length(self):
        # Pocket Casts lists no duration: mpv's can't be checked, so the
        # outro stays off (the episode plays to its end) rather than risk a
        # misread one ending it at once.
        self.assertFalse(bridge.outro_applies(0, 1800.0, 0, 30))
        self.assertTrue(bridge.outro_applies(1800, 1795.0, 0, 30))
        self.assertTrue(bridge.outro_applies(1800, 1900.0, 0, 30))   # longer than listed: ads
        self.assertFalse(bridge.outro_applies(1800, 1500.0, 0, 30))  # far short: misread
        self.assertFalse(bridge.outro_applies(1800, 1795.0, 1780, 30))  # starts inside the outro
        self.assertFalse(bridge.outro_applies(1800, None, 0, 30))


@NEEDS_PLAYER
class FfmpegSelfCheck(TempHome):
    """The watcher reads two FFmpeg log lines; an FFmpeg update could reword
    them, and then every dropped stream on a host with ranges would look like
    the end again, silently. The self-check catches that, once per FFmpeg."""

    def run_check(self):
        said, notified = [], []
        with mock.patch.object(bridge, "out", said.append), \
                mock.patch.object(bridge, "send_notification", lambda text: notified.append(text) or True):
            bridge.cmd_watchcheck(argparse.Namespace())
        return said[0], notified

    def test_this_ffmpeg_passes(self):
        real = bridge.tempfile.TemporaryDirectory
        folders = []

        def recorded(*args, **kwargs):
            folder = real(*args, **kwargs)
            folders.append(folder.name)
            return folder
        with mock.patch.object(bridge.tempfile, "TemporaryDirectory", recorded):
            verdict, notified = self.run_check()
        # Strict review 15 (L3): its folder is in Legato's private runtime
        # folder, not /tmp, and it's gone afterwards.
        runtime = os.path.join(os.environ["XDG_RUNTIME_DIR"], "omarchy-legato")
        self.assertTrue(folders and all(f.startswith(runtime + "/legato-check-") for f in folders), folders)
        self.assertFalse(any(os.path.exists(f) for f in folders))
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual(verdict["seen"], ["error", "reconnect", "short"])
        self.assertIn(" / ", verdict["ffmpeg"])  # mpv's version and FFmpeg's
        saved = bridge.load_state(bridge.WATCH_CHECK)
        self.assertEqual((saved["ffmpeg"], saved["ok"]), (verdict["ffmpeg"], True))
        self.assertTrue(saved["ffmpeg"])
        self.assertEqual(notified, [])
        self.assertFalse(bridge.watch_check_due(saved["ffmpeg"]))

    def watcher_with(self, old, new):
        with open(bridge.watch_script()) as fh:
            lua = fh.read()
        self.assertIn(old, lua)
        folder = tempfile.mkdtemp(dir=os.environ["HOME"])
        os.chmod(folder, 0o700)
        changed = os.path.join(folder, "legato-watch.lua")
        with open(changed, "w") as fh:
            fh.write(lua.replace(old, new))
        return changed

    def test_its_player_is_hardened(self):
        # Strict review 9: the main player's flags, no display (mpv 0.41
        # reads the clipboard at start-up through Wayland), and it dies with
        # the check.
        started = []
        real = subprocess.Popen

        def spy(argv, **kwargs):
            started.append((list(argv), dict(kwargs.get("env") or {})))
            return real(argv, **kwargs)
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-9"}), \
                mock.patch.object(bridge.subprocess, "Popen", spy):
            self.run_check()
        argv, env = next((a, e) for a, e in started if any(str(w).endswith("/mpv") for w in a))
        for flag in ("--no-config", "--ytdl=no", "--clipboard-backends-clr", "--no-video", "--ao=null"):
            self.assertIn(flag, argv)
        self.assertNotIn("WAYLAND_DISPLAY", env)
        if bridge.trusted_tool("setpriv"):
            self.assertEqual(argv[1:3], ["--pdeathsig", "KILL"])

    def test_the_two_lines_reworded_still_pass(self):
        # The break is still caught (`failed`, any network-layer line): no
        # alarm for a harmless rewording.
        changed = self.watcher_with('"Will reconnect at (%d+)"', '"Reconnecting at (%d+)"')
        changed2 = changed.replace("legato-watch.lua", "legato-watch2.lua")
        with open(changed) as fh:
            lua = fh.read().replace('"Stream ends prematurely at (%d+), should be (%d+)"', '"Cut short at (%d+) of (%d+)"')
        with open(changed2, "w") as fh:
            fh.write(lua)
        with mock.patch.object(bridge, "watch_script", lambda: changed2):
            verdict, notified = self.run_check()
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual(verdict["seen"], ["error"])
        self.assertEqual(notified, [])

    def test_a_reworded_ffmpeg_fails_loudly(self):
        # As if mpv's log events (or FFmpeg's "layer: " prefix) changed: the
        # watcher hears nothing, the check fails, a notification says so, and
        # breaks on hosts with ranges are judged by their length from then on.
        with open(bridge.watch_script()) as fh:
            lua = fh.read().replace('mp.enable_messages("warn")', 'mp.enable_messages("fatal")')
        folder = tempfile.mkdtemp(dir=os.environ["HOME"])
        os.chmod(folder, 0o700)
        reworded = os.path.join(folder, "legato-watch.lua")
        with open(reworded, "w") as fh:
            fh.write(lua)
        with mock.patch.object(bridge, "watch_script", lambda: reworded):
            verdict, notified = self.run_check()
        self.assertFalse(verdict["ok"], verdict)
        self.assertEqual(len(notified), 1)
        self.assertIn(verdict["ffmpeg"], notified[0])
        self.assertFalse(bridge.ffmpeg_lines_trusted(verdict["ffmpeg"]))
        self.assertTrue(bridge.ffmpeg_lines_trusted("another version"))


class FfmpegSelfCheckUse(TempHome):
    def test_a_failed_check_means_judging_by_length(self):
        bridge.save_state(bridge.WATCH_CHECK, {"ffmpeg": "mpv 1 / n99", "ok": False, "at": int(time.time())})
        url = "http://example.com/a.mp3"
        snap = {"eof-reached": True, "path": url, "time-pos": 1200.0, "duration": 3600.0, "seekable": True,
                "stream-end": 100_000_000, "stream-pos": 40_000_000, "file-local-options/end": "none",
                "user-data/legato": {"watching": True}, "mpv-version": "mpv 1"}
        self.assertTrue(bridge.stream_broke(dict(snap, **{"ffmpeg-version": "n99"}), {}))   # judged by length: a break
        self.assertFalse(bridge.stream_broke(dict(snap, **{"ffmpeg-version": "n98"}), {}))  # not checked: trusted
        self.assertFalse(bridge.stream_broke(dict(snap, **{"ffmpeg-version": "n99", "time-pos": 3590.0}), {}))
        self.assertFalse(bridge.stream_broke(dict(snap, **{"ffmpeg-version": "n99", "mpv-version": "mpv 2"}), {}))
        # A check that never finished, after ten minutes: not trusted.
        bridge.save_state(bridge.WATCH_CHECK, {"ffmpeg": "mpv 1 / n99", "ok": None, "at": int(time.time()) - 700})
        self.assertTrue(bridge.stream_broke(dict(snap, **{"ffmpeg-version": "n99"}), {}))
        # Nor one under way (strict review 18, L1: a check that crashed left
        # silence trusted for ten minutes, right after an update).
        bridge.save_state(bridge.WATCH_CHECK, {"ffmpeg": "mpv 1 / n99", "ok": None, "at": int(time.time()) - 300})
        self.assertFalse(bridge.ffmpeg_lines_trusted("mpv 1 / n99"))

    def test_a_verdict_file_that_cant_be_trusted_means_judging_by_length(self):
        # Strict review 13 (R3): a watchcheck.json that isn't safe to read (a
        # symlink here) is no verdict to trust FFmpeg's silence on.
        bridge.save_state("settings.json", {})  # (the state folder)
        os.symlink("/dev/null", os.path.join(self.state, bridge.WATCH_CHECK))
        snap = {"eof-reached": True, "path": "http://example.com/a.mp3", "time-pos": 1200.0, "duration": 3600.0,
                "seekable": True, "stream-end": 100_000_000, "stream-pos": 40_000_000, "file-local-options/end": "none",
                "user-data/legato": {"watching": True}, "mpv-version": "mpv 1", "ffmpeg-version": "n99"}
        self.assertFalse(bridge.ffmpeg_lines_trusted("mpv 1 / n99"))
        self.assertTrue(bridge.stream_broke(snap, {}))

    def test_the_check_runs_once_per_ffmpeg(self):
        self.assertTrue(bridge.watch_check_due("n9"))
        self.assertFalse(bridge.watch_check_due(""))
        with mock.patch.object(bridge.subprocess, "Popen") as spawn:
            bridge.start_watch_check("n9")
        self.assertEqual(spawn.call_args[0][0][-1], "watchcheck")
        self.assertFalse(bridge.watch_check_due("n9"))  # under way
        bridge.save_state(bridge.WATCH_CHECK, {"ffmpeg": "n9", "ok": None, "at": int(time.time()) - 700})
        self.assertTrue(bridge.watch_check_due("n9"))   # it never finished: again
        bridge.save_state(bridge.WATCH_CHECK, {"ffmpeg": "n9", "ok": True, "at": int(time.time()) - 7000})
        self.assertFalse(bridge.watch_check_due("n9"))
        self.assertTrue(bridge.watch_check_due("n10"))  # an update
        bridge.save_state(bridge.WATCH_CHECK, {"ffmpeg": "n9", "ok": False, "at": int(time.time()) - 3600})
        self.assertFalse(bridge.watch_check_due("n9"))  # failed an hour ago
        bridge.save_state(bridge.WATCH_CHECK, {"ffmpeg": "n9", "ok": False, "at": int(time.time()) - 90000})
        self.assertTrue(bridge.watch_check_due("n9"))   # failed yesterday: once more


if __name__ == "__main__":
    unittest.main()
