"""Offline execution of the POSIX guard with fake sensors/camera, never ADB.
Identity/token abstraction is replaced in the harness; real /proc identity is
verified separately on device. Tests cannot establish USB/thermal hardware safety.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which('sh') if os.name != 'nt' else None
if not SHELL:
    candidate = Path('C:/Program Files/Git/bin/bash.exe')
    SHELL = str(candidate) if candidate.exists() else None
SOURCE = ROOT / 'edge/luckfox/apd-preview-session.sh'

@unittest.skipUnless(SHELL, 'POSIX host shell unavailable; guard execution NOT TESTED')
class SessionGuardTests(unittest.TestCase):
    def execute(self, mode, duration='10', *, locked=False, running=False, cutoff='60'):
        with tempfile.TemporaryDirectory(prefix='apd-guard-test-') as directory:
            root = Path(directory)
            # All board paths replaced, with no network/serial/ADB dependencies.
            def path(name):
                return (root / name).as_posix()
            runtime = root / 'fake-camera.sh'
            runtime.write_text('echo CAMERA_INVOKED >>"'+path('called')+'"\nexec sleep 30\n')
            script = SOURCE.read_text()
            script = script.replace('STATE=/tmp/apd-preview-session', 'STATE="'+path('state')+'"')
            script = script.replace('LOG=/tmp/apd-preview.log', 'LOG="'+path('log')+'"')
            script = script.replace('RUNTIME=/oem/usr/bin/rkipc', 'RUNTIME="'+path('fake-camera.sh')+'"')
            script = script.replace('"$RUNTIME" -a', 'sh "$RUNTIME" -a')
            # Stub only sensor/time/process-identification adapters; execute the
            # original run loop, trap, ownership cleanup and TERM escalation.
            definitions = """
board_ok() { [ "$MODE" != wrong_board ]; }
read_temp() {
 [ "$MODE" != invalid_temp ] || return 1
 if [ -n "$camera_pid" ] && [ "$MODE" = sensor_loss ]; then return 1; fi
 raw=40000
 [ "$MODE" != hot_start ] || raw=55000
 if [ -n "$camera_pid" ] && [ "$MODE" = thermal ]; then raw=60000; fi
}
read_time() {
 now=10
 if [ -n "$camera_pid" ]; then
  [ "$MODE" != time_limit ] || now=20
  [ "$MODE" != clock_rollback ] || now=9
 fi
}
usb_ok() { [ -z "$camera_pid" ] || [ "$MODE" != usb_loss ]; }
# Match the real adapter's identity readiness: a live launch shell is NOT
# yet the camera runtime. Wait for its own marker before accepting the PID.
process_token() { [ -f "$CALLED_MARKER" ] || return 1; kill -0 "$1" 2>/dev/null || return 1; echo TEST_TOKEN; }
pidof() { [ "$RUNNING" = yes ]; }
wc() { if [ "$MODE" = log_limit ]; then echo 1048576; else command wc "$@"; fi; }
sleep() { command sleep 0.1; }
"""
            script = script.replace('case "$1" in\n run)', definitions+'\ncase "$1" in\n run)')
            file = root / 'session.sh'
            file.write_text(script, newline='\n')
            if locked:
                (root/'state').mkdir()
                (root/'state/owner').write_text('ANOTHER_OWNER')
            result = subprocess.run([SHELL, str(file), 'run', duration, cutoff], capture_output=True,
                                    text=True, timeout=8,
                                    env={**os.environ, 'MODE': mode, 'RUNNING': 'yes' if running else 'no', 'CALLED_MARKER': path('called')})
            log = (root/'log').read_text() if (root/'log').exists() else ''
            return result, log, (root/'called').exists(), (root/'state').exists()

    def test_automatic_stop_without_host_control(self):
        for mode, reason in [('thermal','THERMAL_CUTOFF'), ('usb_loss','USB_NOT_CONFIGURED'),
                             ('time_limit','TIME_LIMIT'), ('clock_rollback','INVALID_MONOTONIC_CLOCK'),
                             ('sensor_loss','INVALID_THERMAL_SENSOR'), ('log_limit','LOG_LIMIT')]:
            with self.subTest(mode=mode):
                result, log, called, locked = self.execute(mode)
                self.assertTrue(called, result.stderr)
                self.assertIn('APD_GUARD_STOP='+reason, log)
                self.assertFalse(locked)

    def test_invalid_duration_never_starts_camera(self):
        for value in ('0','9','301','-1','bad','9999999999'):
            result, log, called, locked = self.execute('time_limit',value)
            self.assertEqual(result.returncode,2)
            self.assertFalse(called)
            self.assertFalse(locked)

    def test_wrong_board_or_bad_sensor_never_starts(self):
        for mode in ('wrong_board','hot_start','invalid_temp'):
            result, log, called, locked = self.execute(mode)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(called)
            self.assertFalse(locked)

    def test_no_takeover_or_stale_lock_cleanup(self):
        result, log, called, locked = self.execute('time_limit',locked=True)
        self.assertEqual(result.returncode,19)
        self.assertFalse(called)
        self.assertTrue(locked)
        result, log, called, locked = self.execute('time_limit',running=True)
        self.assertEqual(result.returncode,18)
        self.assertFalse(called)

    def test_source_has_no_actuator_or_boot_control(self):
        for filename in ('apd-preview-session.sh','apd-previewctl.sh'):
            text = (SOURCE.parent/filename).read_text()
            for forbidden in ('rm -rf', '/dev/tty', '/sys/class/gpio', 'reboot', 'RkLunch.sh', 'shutdown'):
                self.assertNotIn(forbidden,text)

    def test_explicit_78_keeps_sensor_and_time_guards(self):
        result,log,called,locked=self.execute('time_limit',cutoff='78')
        self.assertTrue(called,result.stderr)
        self.assertIn('cutoff_raw=78000',log)
        self.assertIn('APD_GUARD_STOP=TIME_LIMIT',log)
        self.assertFalse(locked)
        for cutoff in ('79','bad','0','39','9999999999'):
            result,log,called,locked=self.execute('time_limit',cutoff=cutoff)
            self.assertEqual(result.returncode,2)
            self.assertFalse(called)
