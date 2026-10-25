"""Offline image inference and deterministic replay. NO board/network/serial IO."""
import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sys
import time
from .config import DEFAULT_CONFIG, ROOT, load_config
from .rules import Detection, Debouncer, FAULTS, assess


def make_debouncer(policy):
    return Debouncer(policy['violation_seconds'], policy['clear_seconds'],
                     policy['min_samples'], policy['max_gap_seconds'])


def replay(rows, config):
    policy = config['policy']
    debounce = make_debouncer(policy)
    results = []
    for index, row in enumerate(rows):
        timestamp = float(row['t'])
        if 'fault' in row:
            if row['fault'] not in FAULTS:
                raise ValueError('Unsupported fault')
            evidence = dict(observation=row['fault'], people=[], people_count=0)
        else:
            people = [Detection(p['label'], p['confidence'], tuple(p['box'])) for p in row.get('person', [])]
            gear = [Detection(p['label'], p['confidence'], tuple(p['box'])) for p in row.get('ppe', [])]
            evidence = assess(people, gear, policy['required'], policy['confidence'])
        alarm = debounce.update(evidence['observation'], timestamp)
        results.append(dict(index=index, t=timestamp, evidence=evidence,
                            alarm_indication=alarm, hardware_outputs_enabled=False))
    return results


def replay_command(args, config):
    rows = []
    for line in args.replay.read_text(encoding='utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    report = dict(stage='HOST_OFFLINE_REPLAY', simulated=True,
                  required=config['policy']['required'],
                  policy_confirmed=config['policy']['confirmed_by_operator'],
                  frames=replay(rows, config), hardware_outputs_enabled=False)
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / 'replay.json'
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print('Replay report:', output.resolve())
    print('Frames:', len(report['frames']), '/ Hardware outputs: DISABLED')


def image_command(args, config):
    # Imported only when real host inference is explicitly requested.
    import cv2
    from .detector import HostDetector, rotate_image, annotate
    source = args.image.resolve()
    image = cv2.imread(str(source))
    if image is None:
        raise ValueError('Cannot decode image: ' + str(source))
    image = rotate_image(image, config['policy']['rotation_degrees'])
    detector = HostDetector(config)
    started = time.monotonic()
    report = detector.infer(image)
    report.update(stage='HOST_OFFLINE_IMAGE', source=str(source),
                  timestamp_utc=datetime.now(timezone.utc).isoformat(),
                  policy_confirmed=config['policy']['confirmed_by_operator'],
                  inference_seconds=round(time.monotonic() - started, 3),
                  hardware_outputs_enabled=False, alarm_confirmed=False,
                  note='One still image cannot confirm a temporal alarm or validate model accuracy.',
                  models={k: dict(path=v['path'], sha256=v['sha256'])
                          for k, v in config['models'].items()})
    args.output.mkdir(parents=True, exist_ok=True)
    preview = args.output / 'annotated.jpg'
    if not cv2.imwrite(str(preview), annotate(image, report)):
        raise OSError('Could not write preview')
    result = args.output / 'report.json'
    result.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    rows = ''.join('<tr><td>P' + str(p['index']) + '</td><td>' + html.escape(p['state']) +
                   '</td><td>' + html.escape(', '.join(p['present'])) + '</td><td>' +
                   html.escape(', '.join(p['missing_evidence'])) + '</td></tr>' for p in report['people'])
    document = ('<!doctype html><meta charset="utf-8"><title>APD offline validation</title>'
                '<style>body{font:16px system-ui;background:#14202d;color:#eee;max-width:1000px;margin:30px auto;padding:20px}'
                'img{width:100%}td,th{padding:12px;text-align:left}aside{color:#ffc96a}</style>'
                '<h1>APD Checker - OFFLINE</h1><aside>Luckfox tidak terhubung. Relay NONAKTIF. '
                'Kebijakan APD belum dinyatakan tervalidasi untuk penggunaan lapangan. '
                'Satu foto bukan bukti akurasi atau alarm terkonfirmasi.</aside>'
                '<h2>' + html.escape(report['observation']) + '</h2><img src="annotated.jpg">'
                '<table><tr><th>Orang</th><th>Status</th><th>Bukti positif</th><th>Belum terbukti</th></tr>' + rows +
                '</table><p>Detail: <a href="report.json">report.json</a></p>')
    (args.output / 'index.html').write_text(document, encoding='utf-8')
    print('Observation:', report['observation'], '/ People:', report['people_count'])
    print('Report:', result.resolve())
    print('Preview:', preview.resolve())
    print('Hardware outputs: DISABLED / single-frame alarm confirmation: FALSE')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--image', type=Path, help='Previously captured local image')
    source.add_argument('--replay', type=Path, help='Synthetic/recorded detection JSONL')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs' / 'luckfox' / 'offline-check')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.replay:
            replay_command(args, config)
        else:
            image_command(args, config)
    except Exception as exc:
        print('OFFLINE VALIDATION FAILED (not SAFE): ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
