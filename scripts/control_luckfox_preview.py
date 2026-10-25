"""HOST-only manual control of builtin Luckfox preview, NOT PPE inference.
No UART/GPIO/Arduino, deletion, firmware flashing, or boot changes.
"""
import argparse
from pathlib import Path
import sys
import subprocess
import shlex
from audit_luckfox_thermal import adb_output, ROOT


def control(adb, serial, action, *, duration=60, cutoff_c=60):
    if action not in ('start','stop','status'):
        raise ValueError('invalid preview action')
    if type(duration) is not int or not 10 <= duration <= 300:
        raise ValueError('preview duration must be 10..300 seconds')
    if action != 'start' and duration != 60:
        raise ValueError('duration applies only to start')
    if type(cutoff_c) is not int or not 40 <= cutoff_c <= 78:
        raise ValueError('cutoff must be 40..78 C; not a chip safety specification')
    if action != 'start' and cutoff_c != 60:
        raise ValueError('cutoff applies only to start')
    argument = (' ' + str(duration) + ' ' + str(cutoff_c)) if action == 'start' else ''
    identity = adb_output(adb, serial, 'cat /proc/device-tree/model\n')
    if identity.replace(b'\x00',b'').strip() != b'Luckfox Pico Mini B':
        raise RuntimeError('Wrong board; no control command sent')
    # Legacy PTY adbd may NOT return the remote exit code. Check our marker.
    script = ('test -f /userdata/apd-previewctl.sh && '
              'sh /userdata/apd-previewctl.sh ' + shlex.quote(action) + argument +
              '\ncode=$?; printf "\\nAPD_CONTROL_EXIT=%s\\n" "$code"\n')
    output = adb_output(adb, serial, script).decode('utf-8','replace')
    if not output.rstrip().endswith('APD_CONTROL_EXIT=0'):
        raise RuntimeError('Preview control failed or unconfirmed:\n'+output)
    return output


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('start','stop','status'))
    parser.add_argument('--serial',required=True)
    parser.add_argument('--adb',type=Path,default=ROOT/'platform-tools/adb.exe')
    parser.add_argument('--duration', type=int, default=60, help='Bounded on-board preview 10..300 seconds (start only)')
    parser.add_argument('--cutoff-c', type=int, default=60, help='Requested supervised stop threshold 40..78 C, not a safe rating')
    args=parser.parse_args(argv)
    print(control(args.adb,args.serial,args.action,duration=args.duration,cutoff_c=args.cutoff_c))
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError,ValueError,subprocess.TimeoutExpired,FileNotFoundError) as exc:
        print('CONTROL NOT CONFIRMED: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
