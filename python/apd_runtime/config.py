"""Configuration loading has no hardware side effects."""
import hashlib
import json
from pathlib import Path
from .rules import validate_required

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / 'config' / 'apd_offline.json'


def load_config(path=DEFAULT_CONFIG):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding='utf-8'))
    if config.get('schema_version') != 1 or config.get('stage') != 'HOST_OFFLINE_VALIDATION':
        raise ValueError('Unsupported configuration/stage')
    if config['target'].get('deployment_enabled') is not False:
        raise ValueError('Offline runner never permits deployment')
    if config['actuators'].get('enabled') is not False:
        raise ValueError('Offline runner never permits actuation')
    policy = config['policy']
    validate_required(policy['required'])
    if not 0 < policy['confidence'] <= 1:
        raise ValueError('Confidence threshold must be in (0, 1]')
    if policy['rotation_degrees'] not in (0, 90, 180, 270):
        raise ValueError('Rotation must be 0, 90, 180, or 270')
    size = policy['input_size']
    if not isinstance(size, int) or not 32 <= size <= 1280 or size % 32:
        raise ValueError('Input size must be a multiple of 32 in [32, 1280]')
    # Validate every temporal parameter before creating a runner.
    from .rules import Debouncer
    Debouncer(policy['violation_seconds'], policy['clear_seconds'],
              policy['min_samples'], policy['max_gap_seconds'])
    return config


def verify_model(spec, root=ROOT):
    path = (root / spec['path']).resolve()
    if not path.is_file():
        raise FileNotFoundError('Local model missing; no automatic downloads: ' + str(path))
    if path.suffix.lower() != '.pt':
        raise ValueError('Offline validator expects local .pt models')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != spec['sha256']:
        raise ValueError('Model hash mismatch: ' + str(path))
    return path, digest
