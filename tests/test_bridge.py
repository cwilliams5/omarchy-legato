"""Tests for bin/legato-bridge: private state files, input validation,
bounded and host-checked HTTP, token refresh, and an end-to-end run of the
player against a fake Pocket Casts server with a real mpv — play, pause,
position sync, the end of an episode, mark-played and autoplay.

Run with tests/run, or directly:

    /usr/bin/python3 -I -B -m unittest discover -s tests -v
"""

import base64
import functools
import gzip
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
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
import urllib.parse
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "bin" / "legato-bridge"

sys.dont_write_bytecode = True
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
PASSWORD = "correct horse battery staple"


def mode_of(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


class TempHome(unittest.TestCase):
    """A private throwaway $HOME with every XDG directory pointed inside it."""

    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="pc-bridge-"))
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
    out = io.StringIO()
    fake_stdin = io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8")), encoding="utf-8")
    with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stdin", fake_stdin), \
            mock.patch.object(bridge, "scrub_environment", lambda: None):
        bridge._AUTH = None
        bridge.main(list(argv))
    return json.loads(out.getvalue())


# --------------------------------------------------------------- unit tests

class Validation(unittest.TestCase):
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
        if path.startswith("/audio/"):
            # Byte ranges, as real podcast hosts serve them, so mpv can start
            # a freshly loaded episode part way through.
            name = path.rsplit("/", 1)[1].split(".")[0]
            blob = s.get("media", {}).get(name, s["audio"])
            cut = s.get("cut", {}).get(name)
            if s.get("slowaudio", {}).get(name):  # a slow host: the first byte takes a while
                time.sleep(s["slowaudio"][name])
            if name in s.get("hang", {}):
                # The link stalls part way: the first `hang` bytes, then
                # nothing for `hangFor` seconds with the connection open, then
                # it closes; reconnects get nothing.
                if s.setdefault("hangServed", {}).get(name):
                    self.close_connection = True
                    return
                s["hangServed"][name] = True
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob[:s["hang"][name]])
                self.wfile.flush()
                time.sleep(s.get("hangFor", 60))
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
        fails = s.setdefault("fail", {})
        if fails.get(path, 0) > 0:  # a dropped request, as when the network goes
            fails[path] -= 1
            self.reply(503, {})
            return
        token = (self.headers.get("Authorization") or "").replace("Bearer ", "")
        if path == "/user/login_pocket_casts":
            if body.get("password") == PASSWORD:
                self.reply(200, {"email": body["email"], "uuid": "u", "accessToken": "t1", "tokenType": "Bearer",
                                 "expiresIn": 3600, "refreshToken": "r1"})
            else:
                self.reply(401, {"errorMessage": "Wrong password", "errorMessageId": "login_password_incorrect"})
            return
        if path == "/user/token":
            self.reply(200, {"email": "me@example.com", "uuid": "u", "accessToken": "t2", "expiresIn": 3600, "refreshToken": "r2"})
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
            self.reply(200, {"podcasts": [show(u, v) for u, v in s["shows"].items()]})
        elif path == "/up_next/list":
            self.reply(200, {"serverModified": 1, "episodes": [
                {"uuid": u, "title": eps[u]["title"], "url": eps[u]["url"], "podcast": eps[u]["podcast"],
                 "published": eps[u]["published"]} for u in s["upnext"]],
                "episodeSync": [{"uuid": u, "playedUpTo": s["progress"].get(u, 0), "duration": eps[u]["duration"]} for u in s["upnext"]]})
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
            self.reply(200, {})
        elif path == "/user/episode":
            e = dict(eps[body["uuid"]])
            e.update({"podcastUuid": e.pop("podcast"), "playedUpTo": s["progress"].get(body["uuid"], 0),
                      "playingStatus": s["status"].get(body["uuid"], 1)})
            self.reply(200, e)
        elif path in ("/user/in_progress", "/user/new_releases"):
            self.reply(200, {"episodes": [dict(eps[u], podcastUuid=eps[u]["podcast"], playedUpTo=s["progress"].get(u, 0))
                                          for u in eps]})
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
        self.end_without_autoplay()
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
        state = bridge.load_playback()
        state["lastSyncAt"] = float(state.get("lastSyncAt") or time.time()) - seconds
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

        # Always on top, from the window's right-click menu.
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

    def break_stream_and_wait(self):
        self.fake["cut"] = {EP_1: len(self.audio) // 5}  # about 6 s of 30
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
        self.assertFalse(bridge.load_playback().get("unsentBreak"))  # Pocket Casts has it
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
        view = self.break_stream_and_wait()
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)

    def test_a_break_answered_by_a_503_page_is_not_the_end(self):
        self.error_page_break(503)

    def test_a_break_answered_by_a_403_page_is_not_the_end(self):
        self.error_page_break(403)

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

    def pushes_of(self, uuid):
        return [b for b in self.writes("/sync/update_episode") if b["uuid"] == uuid]

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
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
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
        self.assertTrue(bridge.load_playback().get("unsentBreak"))
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
        state["unsentBreak"]["at"] -= 2 * 3600  # long ago
        bridge.save_playback(state)
        self.fake["fail"], self.fake["cut"] = {}, {}
        view = run_bridge("toggle")["data"]
        self.assertLess(view["position"], 2)  # Pocket Casts' (the start), not the old local one

    def test_play_at_a_real_end_before_any_poll_plays_it_again(self):
        # Play's own end check reads the file's size: a real end (read to its
        # end) isn't a break, so Play plays it again from the top.
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
        with mock.patch.object(bridge, "push_position"):
            self.assertFalse(bridge.stream_stopped(dict(state, lastSyncAt=time.time()), {}, 1795.0).get("nothingMore"))
            self.assertTrue(bridge.stream_stopped(dict(state, lastSyncAt=time.time()), {}, 1800.5).get("nothingMore"))

    def test_after_a_seek_a_reload_that_breaks_isnt_nothing_more(self):
        # Loaded at 20, a seek of yours back to 20, and the link drops at
        # 21.5: it got somewhere after your seek, not "nothing more arrives".
        self.fake["progress"][EP_1] = 20
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.fake["cut"] = {EP_1: int(len(self.audio) * 21.5 / 30)}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
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
                    "user-data/legato": watching}
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
        self.assertTrue(bridge.stream_broke(snap(**cut, **{"time-pos": 3599.0}), {}))  # at "the end" by every number
        #    ...unless mpv read on past it (a reconnect that worked), to a real end:
        self.assertFalse(bridge.stream_broke(snap(**cut, **{"stream-end": 100_000_000, "stream-pos": 99_999_000}), {}))
        # 2. No such line and the host gave a size: the end, whatever mpv's
        #    estimates say (an M4A's index left unread, a misread MP3, an outro).
        self.assertFalse(bridge.stream_broke(snap(**{"stream-end": 100_000_000, "stream-pos": 40_000_000}), {}))
        self.assertFalse(bridge.stream_broke(snap(**{"time-pos": 23.0, "duration": 18.4}), state(size=1_000_000, listed=60)))
        self.assertFalse(bridge.stream_broke(snap(**{"stream-end": 5000, "time-pos": 0.0, "file-local-options/end": "-20"}),
                                             state(listed=60)))
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
        # What the poll reads includes the watcher's record, at an end.
        self.assertIn("user-data/legato", bridge.END_PROPERTIES)
        self.assertIn("stream-pos", bridge.END_PROPERTIES)

    def test_the_watcher_records_a_cut_short_stream(self):
        # The watcher itself, in mpv's own Lua: FFmpeg's short-end line for a
        # sized stream and its reconnect lines (an https drop, a timeout) are
        # recorded (the latest), the short-end line for a host that gave no
        # size isn't, other components' aren't, and a new file starts clean.
        lua = shutil.which("lua5.1") or shutil.which("luajit")
        if not lua:
            self.skipTest("no Lua 5.1 to run mpv's script in")
        harness = r"""
            local props, handlers = {}, {}
            mp = { set_property_native = function(name, value) props[name] = value end,
                   register_event = function(name, fn) handlers[name] = fn end,
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
            handlers["start-file"]({})
            show()
            io.write(props.level)
        """
        done = subprocess.run([lua, "-e", harness], capture_output=True, text=True, timeout=10,
                              env={"WATCH": str(ROOT / "bin" / "legato-watch.lua"), "PATH": "/usr/bin"})
        self.assertEqual(done.stdout, "true nil;true 24054;true 24054;true 30000;true 41000;true 52000;true nil;warn",
                         done.stderr)

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
                   QT_FORCE_STDERR_LOGGING="1")
        here = pathlib.Path(__file__).resolve().parent
        done = subprocess.run(["/usr/lib/qt6/bin/qml", "-I", str(here / "qml" / "imports"), str(here / "qml" / name)],
                              env=env, capture_output=True, text=True, timeout=60)
        lines = [l.split("qml: ", 1)[-1] for l in (done.stdout + done.stderr).splitlines() if "qml: " in l]
        failures = [l for l in lines if l.startswith("FAIL")]
        self.assertEqual(failures, [])
        self.assertGreater(len([l for l in lines if l.startswith("ok ")]), 10, "\n".join(lines) or done.stderr)
        self.assertEqual(done.returncode, 0)

    def test_pages(self):
        self.run_qml("pages.qml")

    def test_the_real_panel_and_service(self):
        # Panel.qml and Service.qml themselves (tests/qml/panel.qml): pages,
        # keys, the Stats page's reads and errors, the seek flag.
        self.run_qml("panel.qml")


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
        self.assertIn("~/.config/omarchy/shell.json", privacy)
        self.assertIn("password is never stored", privacy)
        self.assertIn("every %d seconds" % bridge.SYNC_INTERVAL, privacy)
        self.assertIn("%d-minute" % (bridge.PODCASTS_CACHE_SECONDS // 60), privacy)

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

    def assert_broke(self, view):
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertEqual(self.fake["upnext"][0], EP_1)

    def test_an_https_stream_that_drops_part_way_is_not_finished(self):
        self.fake["cut"] = {EP_1: len(self.audio) // 5}  # closed without close_notify
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        self.assert_broke(self.settled())

    def test_an_https_stream_whose_reconnect_gets_a_503_is_not_finished(self):
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
        self.fake["cutReply"] = 503
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

    def test_a_stream_that_stalls_part_way_is_not_finished(self):
        self.fake["hang"] = {EP_1: len(self.audio) // 5}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        view = self.wait_for(lambda: (lambda v: v if v.get("streamBroke") or v.get("ended")
                                      or (v["item"] or {}).get("uuid") != EP_1 else None)(run_bridge("player")["data"]),
                             timeout=90)
        self.assertTrue(view.get("streamBroke"), view)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)


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
            with mock.patch.object(bridge, "feed_address_allowed", lambda address, allow_local: True):
                sock = bridge.connect_feed_host("127.0.0.1", server.getsockname()[1], False)
            with sock:
                self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE), 1)
                self.assertLessEqual(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE), 30)
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


if __name__ == "__main__":
    unittest.main()
