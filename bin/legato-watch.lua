-- Legato's stream watcher, loaded into Legato's own mpv only (--script).
-- It tells the bridge whether the file playing now stopped because its
-- stream broke off, which mpv itself can't say: at a real end and at a break
-- it sits at "end of file" just the same (stream_broke in legato-bridge).
--
-- FFmpeg's http layer logs, for a stream that fails part way:
--   "Will reconnect at N in S second(s), error=..." whenever a read fails
--     before the end it expects: a dropped connection, an HTTPS one closed
--     without TLS's close_notify, a link gone silent past the timeout;
--   "Stream ends prematurely at N, should be M" when a read ends cleanly
--     short of the size M the host gave.
-- A real end logs neither. With no size from the host, the second comes at
-- every end, break or not (M reads 18446744073709551615, unknown), so that
-- one is ignored.
--
-- On a host without byte ranges FFmpeg can't reconnect, and an https drop or
-- a timeout logs neither line; the bridge judges those by how far mpv read.
--
-- It also times stalls: mpv waiting for data while it should be playing
-- (`paused-for-cache`), as seen when the property changes (no timer). A long
-- one is an interruption to the bridge, like a pause.
--
-- `user-data/legato` holds, for the current file: `watching` (this script
-- runs; a player started by an older Legato has nothing), `cut` (the byte
-- offset N of the latest such line), `failed` (any other warning or error
-- from FFmpeg's network layers since the last seek), `seen` (which of the
-- two lines came:
-- `reconnect`, `short`; the bridge's self-check runs this script against a
-- break it makes, to know these lines still read as written), `stallSince`
-- (when the stall now under way began, os.time()) and `stalls` ({since,
-- ended} of the last few, newest last: a long one is still there after a
-- short one follows). It is reset at the start of each file. Nothing else
-- is read or changed.

local UNKNOWN = "18446744073709551615"
-- FFmpeg's network layers, as they name themselves at the start of a line.
local NETWORK = { http = true, https = true, tls = true, tcp = true, httpproxy = true }
local state = { watching = true }

local function publish()
  mp.set_property_native("user-data/legato", state)
end

local function failed_at(text)
  local at = string.match(text, "Will reconnect at (%d+)")
  if at then
    return at, "reconnect"
  end
  local short, want = string.match(text, "Stream ends prematurely at (%d+), should be (%d+)")
  if short and want ~= UNKNOWN then
    return short, "short"
  end
  return nil
end

mp.register_event("start-file", function()
  state = { watching = true }
  publish()
end)

-- A seek starts a new read: a failure before it says nothing about after.
mp.register_event("seek", function()
  if state.failed then
    state.failed = nil
    publish()
  end
end)

mp.observe_property("paused-for-cache", "bool", function(_, waiting)
  if waiting and not state.stallSince then
    state.stallSince = os.time()
    publish()
  elseif not waiting and state.stallSince then
    local stalls = state.stalls or {}
    table.insert(stalls, { since = state.stallSince, ended = os.time() })
    if #stalls > 8 then
      table.remove(stalls, 1)
    end
    state.stalls = stalls
    state.stallSince = nil
    publish()
  end
end)

mp.enable_messages("warn")
mp.register_event("log-message", function(event)
  if event.prefix ~= "ffmpeg" then
    return
  end
  local text = event.text or ""
  local at, kind = failed_at(text)
  if at then
    state.cut = tonumber(at)
    state.seen = state.seen or {}
    state.seen[kind] = true  -- which line it was (the bridge's self-check)
    publish()
  end
  -- Any other warning or error from the network layers since the last seek
  -- (a seek's request refused: "http: HTTP error 403"; a TLS error; whatever
  -- a later FFmpeg calls them): `failed`. Not the two lines above (their
  -- offset says whether mpv read on past them), nor the short-end line of a
  -- host that gave no size, which comes at every end there.
  local layer = string.match(text, "^(%a+): ")
  if not at and layer and NETWORK[layer] and not string.find(text, UNKNOWN, 1, true) then
    state.failed = true
    publish()
  end
end)

publish()
