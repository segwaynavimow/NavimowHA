# State freshness regressions

These tests exercise the real Home Assistant coordinator/entities and the
`navimow-sdk` MQTT parser, cache and callbacks. Cloud API calls are mocked and
the SDK network constructor is skipped; no commands are sent to a real mower.

Run from the repository root in an environment with Home Assistant and
`navimow-sdk` installed:

```sh
python -m unittest discover -s tests -v
python -m compileall -q custom_components/navimow tests
git diff --check
```

Validated with Python 3.13.3, Home Assistant 2026.2.3 and navimow-sdk 0.1.2.
The tests use Python's standard `unittest` library.

## Bug-51087

An unchanged MQTT cache (15%, docked) previously replaced a newer HTTP result
(80%, mowing) on the next 30-second update. The SDK cache is now used only
before the coordinator has its first state. Subsequent MQTT callbacks still
apply incoming states immediately. A state push received while HTTP is in
flight takes priority over that HTTP response; attribute-only pushes do not
suppress fallback.

The same 12 tests yield three failures on upstream commit `76fa64d` and all
pass with the fix. They cover repeated polling, HTTP failure retention,
startup cache fallback, MQTT state/attribute handling, HTTP/MQTT ordering,
device isolation, authentication and start/pause/dock/resume command ordering.

The runtime change is confined to `coordinator.py`. Authentication, MQTT
connection setup, control commands, state mapping, polling intervals, runtime
dependencies and release workflows are unchanged from that upstream commit.
This addresses a reproducible local state rollback; it does not establish why
the affected user's MQTT pushes stopped. Acceptance still requires a real HA
installation to check battery/activity over multiple fallback intervals and
MQTT disconnect/reconnect cycles.
