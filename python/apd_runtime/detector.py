"""CPU-only validation on the HOST. Never import this module on Mini B.

No generic detector fallback pretending to be a PPE model. Existing trusted local
checkpoints only; a checksum identifies bytes, not model accuracy or trustworthiness.
"""
import os
from dataclasses import asdict
from .config import ROOT, verify_model
from .rules import Detection, assess, normal_label


class HostDetector:
    def __init__(self, config):
        self.config = config
        paths = {kind: verify_model(spec)[0] for kind, spec in config['models'].items()}
        os.environ.setdefault('YOLO_CONFIG_DIR', str(ROOT / '.cache' / 'ultralytics'))
        os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
        import torch
        torch.set_num_threads(2)
        from ultralytics import YOLO, settings
        settings.update({'sync': False, 'hub': False})
        self.ppe = YOLO(str(paths['ppe']))
        self.person = YOLO(str(paths['person']))
        labels = [normal_label(self.ppe.names[i]) for i in sorted(self.ppe.names)]
        if labels != config['models']['ppe']['expected_labels']:
            raise ValueError('Unexpected PPE model label order; reject generic fallback')
        from .tracking import model_capabilities
        capabilities = model_capabilities(labels, config['policy']['required'])
        if not capabilities['label_contract_supported']:
            raise ValueError('PPE model cannot support required policy: ' + str(capabilities))
        person_ids = [i for i, label in self.person.names.items() if normal_label(label) == 'person']
        if len(person_ids) != 1:
            raise ValueError('Person detector requires exactly one person class')
        self.person_ids = person_ids

    @staticmethod
    def _rows(result):
        if result.boxes is None:
            return []
        xyxy = result.boxes.xyxy.cpu().tolist()
        classes = result.boxes.cls.cpu().tolist()
        scores = result.boxes.conf.cpu().tolist()
        if not len(xyxy) == len(classes) == len(scores):
            raise ValueError('Inconsistent detection tensors')
        return [Detection(normal_label(result.names[int(c)]), float(s), tuple(b))
                for b, c, s in zip(xyxy, classes, scores)]

    def infer(self, image):
        if image is None or image.size == 0:
            raise ValueError('No image supplied')
        policy = self.config['policy']
        args = dict(imgsz=policy['input_size'], conf=policy['confidence'],
                    device='cpu', verbose=False, max_det=128)
        people = self._rows(self.person.predict(image, classes=self.person_ids, **args)[0])
        equipment = self._rows(self.ppe.predict(image, **args)[0])
        report = assess(people, equipment, policy['required'], policy['confidence'])
        report['detections'] = dict(person=[asdict(d) for d in people],
                                    ppe=[asdict(d) for d in equipment])
        report['model_capacity_reached'] = len(people) >= 128 or len(equipment) >= 128
        if report['model_capacity_reached']:
            report['observation'] = 'MODEL_ERROR'
        return report


def rotate_image(image, degrees):
    import cv2
    if degrees == 0:
        return image
    rotations = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    return cv2.rotate(image, rotations[degrees])


def annotate(image, report):
    import cv2
    output = image.copy()
    colors = {'VIOLATION': (30, 30, 230), 'UNKNOWN': (0, 200, 255),
              'COMPLIANT': (0, 180, 0)}
    scale = max(0.5, output.shape[1] / 1600)
    for person in report['people']:
        x1, y1, x2, y2 = map(int, person['box'])
        color = colors[person['state']]
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 3)
        label = f"P{person['index']} {person['state']}"
        cv2.putText(output, label, (x1, max(25, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)
    for gear in report['detections']['ppe']:
        x1, y1, x2, y2 = map(int, gear['box'])
        cv2.rectangle(output, (x1, y1), (x2, y2), (255, 180, 40), 2)
        cv2.putText(output, f"{gear['label']} {gear['confidence']:.2f}",
                    (x1, max(20, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX,
                    scale * 0.7, (255, 180, 40), 2)
    cv2.rectangle(output, (0, 0), (output.shape[1], 65), (20, 20, 20), -1)
    cv2.putText(output, 'OFFLINE / RELAY DISABLED / ' + report['observation'],
                (15, 42), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2)
    return output
