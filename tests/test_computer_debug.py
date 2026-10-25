"""PC debug tests: local HTTP, synthetic data, mocks. NO board/Arduino access."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from urllib.request import urlopen, Request

from apd_runtime.computer_debug import (DebugState, TelemetryTail, validate_heartbeat,
    demo_rows, make_server, main, run_preview)
from apd_runtime.tracking_offline import load_workshop_config, replay_tracking


def heartbeat(seq=1):
    return dict(schema_version=1, kind='BOARD_HEARTBEAT', seq=seq, uptime_seconds=seq*1.0,
                thermal_zone0_raw=54000, thermal_zone0_type='soc-thermal', probe_only=True,
                ai_running=False, hardware_outputs_enabled=False)


class DebugStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.state = DebugState('PROBE_ONLY', clock=lambda: self.now)

    def test_probes_never_enable_hardware_ai_or_certify_thermal_safety(self):
        self.state.accept_heartbeat(heartbeat())
        out = self.state.snapshot()
        self.assertFalse(out['hardware_outputs_enabled'])
        self.assertFalse(out['arduino_connected_by_app'])
        self.assertFalse(out['ai_running'])
        self.assertFalse(out['board']['thermal_safety_verified'])
        self.assertEqual(out['camera']['status'], 'NOT_REQUESTED')
        self.assertIsNone(out['report'])

    def test_missing_thermal_sensor_allowed_but_not_safe(self):
        row = heartbeat()
        row['thermal_zone0_raw'] = row['thermal_zone0_type'] = None
        self.state.accept_heartbeat(row)
        self.assertIsNone(self.state.snapshot()['board']['telemetry']['thermal_zone0_raw'])
        self.assertFalse(self.state.snapshot()['board']['thermal_safety_verified'])

    def test_schema_bool_and_nonfinite_values_rejected(self):
        for key, value in [('schema_version', True), ('seq', True), ('seq', 0),
                           ('uptime_seconds', float('nan')), ('uptime_seconds', float('inf')),
                           ('uptime_seconds', True), ('uptime_seconds', -1),
                           ('probe_only', False), ('ai_running', True),
                           ('hardware_outputs_enabled', True), ('thermal_zone0_raw', True),
                           ('thermal_zone0_raw', 5.4), ('thermal_zone0_type', []),
                           ('kind', 'ACTUATE')]:
            with self.subTest(key=key, value=value):
                row = heartbeat()
                row[key] = value
                with self.assertRaises(ValueError):
                    validate_heartbeat(row)
        for row in (None, [], 'raw'):
            with self.assertRaises(ValueError):
                validate_heartbeat(row)

    def test_duplicate_or_reboot_heartbeat_not_fresh(self):
        self.state.accept_heartbeat(heartbeat(2))
        self.now = 4
        for row in (heartbeat(2), heartbeat(1), dict(heartbeat(3), uptime_seconds=0.5)):
            with self.assertRaises(ValueError):
                self.state.accept_heartbeat(row)
        self.assertEqual(self.state.snapshot()['board']['status'], 'STALE')

    def test_heartbeat_expiry_and_invalid_status(self):
        self.assertEqual(self.state.snapshot()['board']['status'], 'NOT_RECEIVED')
        self.state.accept_heartbeat(heartbeat())
        self.assertEqual(self.state.snapshot()['board']['status'], 'RECEIVED')
        self.now = 3.6
        self.assertEqual(self.state.snapshot()['board']['status'], 'STALE')
        self.state.reject_heartbeat('invalid')
        self.assertEqual(self.state.snapshot()['board']['status'], 'INVALID')
        self.state.accept_heartbeat(heartbeat(2))
        self.assertEqual(self.state.snapshot()['board']['status'], 'RECEIVED')

    def test_live_preview_never_accepts_synthetic_ppe(self):
        report = replay_tracking(demo_rows(), load_workshop_config())[1]
        with self.assertRaises(ValueError):
            self.state.publish_demo(report, 1)
        self.assertIsNone(self.state.snapshot()['report'])

    def test_demo_cannot_accept_live_camera_frame(self):
        with self.assertRaises(ValueError):
            DebugState('DEMO').publish_camera(b'not-an-image')

    def test_received_camera_image_expires(self):
        state = DebugState('CAMERA_PREVIEW', clock=lambda: self.now)
        state.publish_camera(b'jpeg')
        self.assertEqual(state.jpeg(), b'jpeg')
        self.assertEqual(state.snapshot()['camera']['status'], 'FRAME_RECEIVED')
        self.now = 2.1
        self.assertIsNone(state.jpeg())
        self.assertEqual(state.snapshot()['camera']['status'], 'STALE')
        state.camera_fault('CAMERA_LOST')
        self.assertIsNone(state.jpeg())

    def test_demo_removal_and_put_on_all_items_then_expiry(self):
        reports = replay_tracking(demo_rows(), load_workshop_config())
        state = DebugState('DEMO', clock=lambda: self.now)
        for report in reports:
            state.publish_demo(report, 1)
        events = state.snapshot()['transitions']
        for kind in ('vest', 'shoes', 'helmet'):
            self.assertTrue(any(e['item'] == kind and e['cause'] == 'OPPOSING_EVIDENCE'
                                and e['previous'] == 'PRESENT' for e in events))
            self.assertTrue(any(e['item'] == kind and e['current'] == 'ABSENT' for e in events))
            self.assertTrue(any(e['item'] == kind and e['cause'] == 'OPPOSING_EVIDENCE'
                                and e['previous'] == 'ABSENT' for e in events))
        self.assertTrue(any(e['item'] == 'shoes' and e['cause'] == 'EVIDENCE_EXPIRED' for e in events))
        self.assertTrue(all(r['people'][0]['track_id'] == 1 for r in reports if r['people']))
        self.assertTrue(all(r['hardware_outputs_enabled'] is False for r in reports))

    def test_demo_expiry_and_copy_isolation(self):
        state = DebugState('DEMO', clock=lambda: self.now)
        state.publish_demo(replay_tracking(demo_rows(), load_workshop_config())[1], 1)
        out = state.snapshot()
        out['report']['indicators']['lights']['vest'] = False
        self.assertTrue(state.snapshot()['report']['indicators']['lights']['vest'])
        self.now = 3
        self.assertIsNone(state.snapshot()['report'])
        self.assertEqual(state.snapshot()['demo_status'], 'STALE')


class TelemetryTailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'probe.jsonl'
        self.state = DebugState('PROBE_ONLY')

    def append(self, data):
        with self.path.open('ab') as stream:
            stream.write(data)

    def test_skip_existing_history_then_accept_only_new_lines(self):
        self.append(json.dumps(heartbeat()).encode()+b'\n')
        tail = TelemetryTail(self.path, self.state)
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'NOT_RECEIVED')
        self.append(json.dumps(heartbeat(2)).encode()+b'\n')
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['telemetry']['seq'], 2)

    def test_partial_json_is_not_received_until_newline(self):
        tail = TelemetryTail(self.path, self.state)
        encoded = json.dumps(heartbeat()).encode()
        self.append(encoded[:50])
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'NOT_RECEIVED')
        self.append(encoded[50:]+b'\n')
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'RECEIVED')

    def test_utf8_bom_is_accepted_without_using_old_file_data(self):
        tail = TelemetryTail(self.path, self.state)
        self.append(b'\xef\xbb\xbf'+json.dumps(heartbeat()).encode()+b'\n')
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'RECEIVED')

    def test_oversized_line_and_invalid_json_are_rejected_then_recover(self):
        tail = TelemetryTail(self.path, self.state)
        self.append(b'x'*5000)
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'INVALID')
        self.assertEqual(len(tail.pending), 0)
        self.append(b'x'*5000+b'\n'+json.dumps(heartbeat()).encode()+b'\n')
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'RECEIVED')
        self.append(b'{invalid}\n')
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'INVALID')

    def test_truncation_invalidates_and_does_not_replay(self):
        tail = TelemetryTail(self.path, self.state)
        self.append(json.dumps(heartbeat()).encode()+b'\n')
        tail.poll()
        self.path.write_bytes(b'')
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'INVALID')
        self.assertIn('truncated', self.state.snapshot()['board']['error'])
        self.append(json.dumps(heartbeat(2)).encode()+b'\n')
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'INVALID')
        self.assertEqual(self.state.snapshot()['board']['telemetry']['seq'], 1)

    def test_file_replacement_requires_new_session(self):
        tail = TelemetryTail(self.path, self.state)
        self.append(json.dumps(heartbeat()).encode()+b'\n')
        tail.poll()
        other = self.path.with_suffix('.old')
        self.path.rename(other)
        self.append(json.dumps(heartbeat(2)).encode()+b'\n')
        tail.poll()
        self.assertEqual(self.state.snapshot()['board']['status'], 'INVALID')
        self.assertIn('replaced', self.state.snapshot()['board']['error'])


class LocalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.state = DebugState('DEMO')
        self.server = make_server(self.state, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_loopback_only_and_outputs_disabled_json(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        with urlopen(self.base+'/api/status', timeout=2) as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            row = json.load(response)
        self.assertFalse(row['hardware_outputs_enabled'])
        self.assertFalse(row['ai_running'])

    def test_page_has_explicit_simulation_and_no_external_assets(self):
        with urlopen(self.base+'/', timeout=2) as response:
            page = response.read().decode()
        self.assertIn('SIMULASI SINTETIS', page)
        self.assertIn('UNKNOWN', page)
        self.assertNotIn('https://', page)

    def test_no_control_endpoint_or_stale_camera(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base+'/camera.jpg', timeout=2)
        self.assertEqual(error.exception.code, 503)
        for path, method, code in [('/actuate', 'GET', 404), ('/', 'POST', 501)]:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.base+path, method=method), timeout=2)
            self.assertEqual(error.exception.code, code)


class DebugCLITests(unittest.TestCase):
    def test_preflight_blocks_live_without_thermal_ack_and_bounds_duration(self):
        for args in (['--rtsp', 'rtsp://example.invalid/live'],
                     ['--probe-only', '--telemetry-file', 'unused'],
                     ['--probe-only', '--thermal-checked'],
                     ['--demo', '--telemetry-file', 'unused', '--thermal-checked'],
                     ['--demo', '--duration', 'nan'], ['--demo', '--duration', '301'],
                     ['--demo', '--port', '0'],
                     ['--rtsp', 'file:///video.mp4', '--thermal-checked']):
            with self.subTest(args=args), patch('apd_runtime.computer_debug.make_server') as server:
                with patch('sys.stderr'), self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)
                server.assert_not_called()

    def test_preview_failure_clears_old_image_and_releases_capture(self):
        fake_cv = MagicMock()
        capture = fake_cv.VideoCapture.return_value
        capture.isOpened.return_value = True
        capture.read.return_value = (False, None)
        state = DebugState('CAMERA_PREVIEW')
        state.publish_camera(b'old jpeg')
        with patch.dict('sys.modules', {'cv2': fake_cv}):
            run_preview('rtsp://example.invalid/mock', state, threading.Event())
        self.assertEqual(state.snapshot()['camera']['status'], 'CAMERA_LOST')
        self.assertIsNone(state.jpeg())
        capture.release.assert_called_once()

    def test_preview_open_failure_does_not_publish_compliance(self):
        fake_cv = MagicMock()
        fake_cv.VideoCapture.return_value.isOpened.return_value = False
        state = DebugState('CAMERA_PREVIEW')
        with patch.dict('sys.modules', {'cv2': fake_cv}):
            run_preview('rtsp://example.invalid/mock', state, threading.Event())
        self.assertEqual(state.snapshot()['camera']['status'], 'STREAM_UNAVAILABLE')
        self.assertIsNone(state.snapshot()['report'])
        self.assertFalse(state.snapshot()['hardware_outputs_enabled'])
