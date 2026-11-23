"""Tests for bin/legato-bridge: private state files, input validation,
bounded and host-checked HTTP, token refresh, and an end-to-end run of the
player against a fake Pocket Casts server with a real mpv — play, pause,
position sync, the end of an episode, mark-played and autoplay.

Run with tests/run, or directly:

    /usr/bin/python3 -I -B -m unittest discover -s tests -v
"""

import base64
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
        self.assertEqual(bridge.start_position({"playedUpTo": 99, "duration": 100, "status": 2}), 0)
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

    def test_video_window_rule_and_geometry(self):
        default = bridge.video_rule_lua(None)
        self.assertIn('o.window("^legato-video$", r)', default)  # Omarchy's floating mode leaves it alone
        self.assertIn('match = { class = "^legato-video$" }', default)  # without Omarchy
        self.assertIn('name = "legato-video", float = true, pin = true, no_initial_focus = true', default)
        self.assertIn('["hyprbars:no_bar"] = true', default)
        self.assertIn("monitor_w*7/25", default)
        self.assertIn("pin = false", bridge.video_rule_lua(None, pinned=False))
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

        def fake_post(path, body, token=""):
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

    def do_GET(self):
        s = self.state
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/audio/"):
            # Byte ranges, as real podcast hosts serve them, so mpv can start
            # a freshly loaded episode part way through.
            name = path.rsplit("/", 1)[1].split(".")[0]
            blob = s.get("media", {}).get(name, s["audio"])
            cut = s.get("cut", {}).get(name)
            if cut is not None and s.setdefault("cutServed", {}).get(name):
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
                self.wfile.write(blob[first:min(cut, last + 1)])
                self.close_connection = True
                return
            self.wfile.write(blob[first:last + 1])
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
        self.assertFalse(run_bridge("player")["data"]["playing"])
        self.assertEqual(len(self.writes("/sync/update_episode")), before + 1)
        self.assertTrue(bridge.load_playback()["checkServer"])  # the next resume asks first
        # Already paused: nothing to do, nothing sent.
        self.assertFalse(bridge.pause_for_sleep())
        self.assertEqual(len(self.writes("/sync/update_episode")), before + 1)

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

    def test_a_sign_out_during_a_token_refresh_stays_signed_out(self):
        # Marketplace review (#15655): a list call refreshing an expired token
        # while you sign out used to save the old account's tokens again.
        self.login()
        self.expire_tokens()
        real_post = bridge.post_json
        logout = {}

        def post_json(path, body, token=""):
            if path == "/user/token" and not logout:
                # Sign out from another process while the refresh is in flight.
                logout["proc"] = subprocess.Popen([sys.executable, "-I", "-B", str(BRIDGE), "logout"],
                                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                try:
                    logout["proc"].wait(timeout=1.5)  # done at once, unless it waits for this refresh
                except subprocess.TimeoutExpired:
                    pass
            return real_post(path, body, token)

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
        with mock.patch.object(bridge, "post_json", lambda path, body, token="": (401, {})):
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
        self.assertTrue(rule and 'class = "^legato-video$"' in rule[-1][1] and "pin = true" in rule[-1][1])
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
        self.assertFalse(run_bridge("videopin", "toggle")["data"]["videoPinned"])
        self.assertIs(bridge.load_prefs()["videoPinned"], False)
        dispatch = [a for a in self.hypr if a[0] == "dispatch"][-1][1]
        self.assertEqual(dispatch, 'hl.dsp.window.pin({ action = "off", window = "class:^legato-video$" })')
        self.assertIn("pin = false", [a for a in self.hypr if a[0] == "repl"][-1][1])
        with bridge.Mpv.connect() as player:
            self.assertEqual(player.get("menu-data")[0]["title"], "Always on top: Off")
        run_bridge("video", "on")
        self.assertIn("pin = false", [a for a in self.hypr if a[0] == "repl"][-1][1])
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
        # Reported once; the next poll is quiet.
        self.assertFalse(run_bridge("player")["data"].get("streamBroke"))

    def test_play_after_a_broken_stream_carries_on_from_there(self):
        self.break_stream_and_wait()
        self.fake["cut"] = {}  # the network is back
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertGreater(self.wait_for(lambda: (lambda p: p if p > 2 else None)(run_bridge("player")["data"]["position"])), 2)

    def test_play_pressed_before_a_poll_saw_the_break_carries_on_too(self):
        # Play arrives while mpv sits at the break and no poll has run: it
        # must not be taken for an end and replayed from the top.
        self.fake["cut"] = {EP_1: len(self.audio) // 5}
        self.login()
        self.assertTrue(run_bridge("play", EP_1, "--podcast", PODCAST_A)["ok"])
        with bridge.Mpv.connect() as player:
            self.wait_for(lambda: player.get("eof-reached") is True, timeout=30)
        self.fake["cut"] = {}
        view = run_bridge("toggle")["data"]
        self.assertEqual(view["item"]["uuid"], EP_1)
        self.assertGreater(self.wait_for(lambda: (lambda p: p if p > 2 else None)(run_bridge("player")["data"]["position"])), 2)
        self.assertNotEqual(self.fake["status"].get(EP_1), bridge.STATUS_PLAYED)
        self.assertNotIn(0, [b["position"] for b in self.writes("/sync/update_episode") if b["uuid"] == EP_1][1:])

    def test_a_real_end_is_still_the_end(self):
        self.fake["progress"][EP_1] = 25  # the last 5 s of 30
        self.fake["status"][EP_1] = bridge.STATUS_IN_PROGRESS
        self.login()
        run_bridge("play", EP_1, "--podcast", PODCAST_A)
        self.wait_for(lambda: (lambda v: v if (v["item"] or {}).get("uuid") == EP_2 else None)(run_bridge("player")["data"]), timeout=20)
        self.assertEqual(self.fake["status"][EP_1], bridge.STATUS_PLAYED)

    def test_a_long_duration_estimate_with_the_whole_file_read_is_the_end(self):
        snap = {"eof-reached": True, "time-pos": 3500.0, "duration": 3600.0,
                "stream-pos": 99_900_000, "stream-end": 100_000_000, "file-local-options/end": "none"}
        self.assertFalse(bridge.stream_broke(snap, {}))
        snap["stream-pos"] = 40_000_000
        self.assertTrue(bridge.stream_broke(snap, {}))
        snap["file-local-options/end"] = "-105"  # the show's skip-outro: that's where it ends
        self.assertFalse(bridge.stream_broke(snap, {}))
        self.assertFalse(bridge.stream_broke({"eof-reached": True, "time-pos": 50.0}, {}))  # no duration: the end


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

    def test_the_stats_command_reads_them_back(self):
        self.assertEqual(run_bridge("stats")["data"], {"listened": 0.0, "speed": 0.0, "trim": 0.0, "skipping": 0.0,
                                                       "intro": 0.0, "outro": 0.0, "finished": 0, "since": 0})
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

    def test_a_seek_from_a_media_widget_isnt_time_saved(self):
        self.start()
        self.play_for(1)
        with bridge.Mpv.connect() as player:  # what mpv-mpris does for a widget's seek
            player.command("seek", 12, "relative")
        time.sleep(0.5)
        run_bridge("player", "--seeked")  # the service saw mpv's playback-restart
        stats = self.stats()
        self.assertLess(stats["speed"], 1)
        self.assertEqual(stats["skipping"], 0)

    def test_stopping_counts_up_to_the_stop(self):
        self.start()
        time.sleep(2)
        run_bridge("stop")
        self.assertGreater(self.stats()["listened"], 1.5)


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


if __name__ == "__main__":
    unittest.main()
