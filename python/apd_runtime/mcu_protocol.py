"""APD3 candidate codec ONLY; no serial, GPIO, ADB, file or network IO.
NEVER send to legacy/unknown firmware: embedded digits/letters may actuate v1.9.
Session token/CRC detect mixups/corruption, NOT authenticated safety transport.
Alarm and UNKNOWN physical display policy remain uncommissioned.
"""
import re
from .protocol import encode_frame

STATUSES = frozenset(('STARTING', 'NO_PERSON', 'UNKNOWN', 'COMPLIANT',
                      'VIOLATION', 'CAMERA_LOST', 'MODEL_ERROR'))
FAULTS = frozenset(('STARTING', 'CAMERA_LOST', 'MODEL_ERROR'))
ITEMS = ('vest', 'shoes', 'helmet')


def _uint(value, maximum, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid unsigned integer')
    return value


def _session(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9A-F]{8}', value) or value == '00000000':
        raise ValueError('Session requires eight uppercase nonzero hex digits')
    return value


def hello(sequence, session):
    return encode_frame(_uint(sequence, 65535, 1), 'HELLO', _session(session))


def stop(sequence, session):
    return encode_frame(_uint(sequence, 65535, 1), 'STOP', _session(session))


def heartbeat(sequence, session):
    # Receiver heartbeat NEVER refreshes a data/frame TTL.
    return encode_frame(_uint(sequence, 65535, 1), 'H', _session(session))


def data(sequence, session, frame_id, status, target_id, states, alarm_candidate=False):
    _uint(sequence, 65535, 1)
    _session(session)
    _uint(frame_id, 0xffffffff)
    _uint(target_id, 0xffffffffffffffff)
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError('Invalid observation status')
    if not isinstance(states, str) or not re.fullmatch(r'[UPCND]{3}', states):
        raise ValueError('Require three item/source symbols in vest/shoes/helmet order')
    if type(alarm_candidate) is not bool:
        raise ValueError('Alarm candidate must be bool')
    if (not target_id or status in FAULTS or status == 'NO_PERSON') and (states != 'UUU' or alarm_candidate):
        raise ValueError('No target/fault cannot carry item evidence or alarm')
    if (status in FAULTS or status == 'NO_PERSON') and target_id:
        raise ValueError('Fault/no-person cannot carry a target')
    if status == 'COMPLIANT' and target_id and any(symbol not in 'PC' for symbol in states):
        raise ValueError('Selected compliant target requires all positive evidence')
    if any(symbol in 'ND' for symbol in states) and status != 'VIOLATION':
        raise ValueError('Confirmed absence requires violation observation')
    if alarm_candidate and (not target_id or status != 'VIOLATION' or 'N' not in states):
        raise ValueError('Draft alarm route requires fresh negative on selected target')
    return encode_frame(sequence, 'DATA', session, str(frame_id), status,
                        f'{target_id:016X}', states, '1' if alarm_candidate else '0')


def report_data(sequence, session, frame_id, report):
    """Translate ws-style Python report conservatively, no global lamp OR.
    report must come from a freshness-validated tracker, not caller-created status.
    This function cannot establish camera/model validity or authorize hardware.
    Target alarm is deliberately per selected person, not any-person global.
    """
    if not isinstance(report, dict) or report.get('hardware_outputs_enabled') is not False:
        raise ValueError('Only non-actuating prototype reports are accepted')
    status = report.get('observation')
    target_id = report.get('indicators', {}).get('track_id')
    target_id = 0 if target_id is None else _uint(target_id, 0xffffffffffffffff, 1)
    if status in FAULTS or status == 'NO_PERSON':
        return data(sequence, session, frame_id, status, 0, 'UUU')
    people = [p for p in report.get('people', []) if p.get('track_id') == target_id]
    if not target_id:
        return data(sequence, session, frame_id, status, 0, 'UUU')
    if len(people) != 1 or people[0].get('identity_ambiguous'):
        raise ValueError('Selected track missing/ambiguous')
    symbols = []
    for kind in ITEMS:
        item = people[0]['items'][kind]
        key = item['state'], item['source']
        if item['state'] == 'UNKNOWN': symbols.append('U')
        elif key == ('PRESENT', 'FRESH'): symbols.append('P')
        elif key == ('PRESENT', 'CACHED'): symbols.append('C')
        elif key == ('ABSENT', 'FRESH'): symbols.append('N')
        elif key == ('ABSENT', 'CACHED'): symbols.append('D')
        else: raise ValueError('Invalid confirmed state/source')
    alarm = people[0].get('alarm_candidate') is True and 'N' in symbols
    return data(sequence, session, frame_id, status, target_id, ''.join(symbols), alarm)
