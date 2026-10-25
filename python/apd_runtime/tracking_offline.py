"""Workshop tracking replay only. NO camera/network/hardware dependencies."""
import argparse
import json
from pathlib import Path
import sys
from .config import ROOT, load_config
from .rules import Detection
from .tracking import PersonPPETracker, TrackingSettings, INDICATOR_COLORS, model_capabilities

DEFAULT_WORKSHOP_CONFIG = ROOT / 'config' / 'apd_workshop.json'


def load_workshop_config(path=DEFAULT_WORKSHOP_CONFIG):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if config.get('schema_version') != 1 or config.get('stage') != 'HOST_TRACKING_PROTOTYPE':
        raise ValueError('Not a workshop offline prototype config')
    if config['target'].get('deployment_enabled') is not False or config['actuators'].get('enabled') is not False:
        raise ValueError('Workshop prototype cannot enable hardware')
    if config['policy']['required'] != ['vest', 'shoes', 'helmet']:
        raise ValueError('Workshop requires vest + shoes + helmet')
    if config['indicator_colors'] != INDICATOR_COLORS:
        raise ValueError('Item-color mapping differs from confirmed workshop policy')
    TrackingSettings(required=tuple(config['policy']['required']), **config['tracking'])
    return config


def replay_tracking(rows, config):
    tracker = PersonPPETracker(TrackingSettings(required=tuple(config['policy']['required']), **config['tracking']))
    results = []
    for row in rows:
        people = [Detection(p['label'], p['confidence'], tuple(p['box'])) for p in row.get('person', [])]
        equipment = [Detection(p['label'], p['confidence'], tuple(p['box'])) for p in row.get('ppe', [])]
        visibility = {int(i): value for i, value in row.get('visibility', {}).items()}
        result = tracker.update(row['frame_id'], row['t'], people, equipment,
                                visibility=visibility, received_at=row.get('received_at'),
                                fault=row.get('fault'), selected_track_id=row.get('selected_track_id'),
                                camera_view_epoch=row.get('camera_view_epoch', 0),
                                camera_view_unstable=row.get('camera_view_unstable', False))
        results.append(dict(frame_id=row['frame_id'], t=row['t'], scenario=row.get('scenario'), **result))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=DEFAULT_WORKSHOP_CONFIG)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs' / 'luckfox' / 'tracking-check' / 'replay.json')
    args = parser.parse_args(argv)
    try:
        config = load_workshop_config(args.config)
        rows = [json.loads(line) for line in args.replay.read_text(encoding='utf-8').splitlines() if line.strip()]
        # Metadata contract check only, not a neural inference/accuracy test.
        host_config = load_config()
        capabilities = model_capabilities(host_config['models']['ppe']['expected_labels'], config['policy']['required'])
        report = dict(stage=config['stage'], simulated=True, required=config['policy']['required'],
                      indicator_colors=config['indicator_colors'], current_model_capabilities=capabilities,
                      frames=replay_tracking(rows, config), hardware_outputs_enabled=False,
                      deployment_ready=False)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        print('Synthetic workshop replay:', args.output.resolve())
        print('Frames:', len(report['frames']), '/ Hardware: DISABLED / Deployment: NOT READY')
        print('Current model missing labels:', capabilities['missing_positive'] + capabilities['missing_negative'])
    except Exception as exc:
        print('WORKSHOP REPLAY FAILED (not SAFE): ' + str(exc), file=sys.stderr)
        return 1
    return 0
