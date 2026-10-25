"""Synthetic HOST tests. No camera, real inference, browser, or serial device."""
from contextlib import ExitStack
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from apd_runtime.ppe_bridge import Decision, DecisionFilter, encode_status, decode_status, report_decision
from apd_runtime import live_camera as live
from apd_runtime.rules import assess, Detection
from test_detector_contract import result


def person(state="VIOLATION", missing=("helmet",), present=()):
    return dict(state=state, explicit_missing=list(missing), present=list(present))


def report(observation="VIOLATION", missing=("helmet",)):
    return dict(observation=observation, required=["helmet", "shoes", "vest"],
                people=[person(observation, missing, ("helmet", "shoes", "vest") if observation == "COMPLIANT" else ())]
                if observation not in ("NO_PERSON", "MODEL_ERROR", "CAMERA_LOST") else [])


class PpeBridgeTests(unittest.TestCase):
    def test_all_wire_states_and_masks_roundtrip(self):
        for state, mask in [("V", m) for m in range(1, 8)] + [(s, 0) for s in "CNUF"]:
            with self.subTest(state=state, mask=mask):
                packet = encode_status(state, mask)
                self.assertEqual(len(packet), 12)
                self.assertEqual(decode_status(packet), (state, mask))

    def test_packet_checksum_corruption_rejected(self):
        packet = encode_status("V", 3)
        for index in range(len(packet)):
            altered = packet[:index] + bytes([packet[index] ^ 1]) + packet[index + 1:]
            with self.assertRaises(ValueError):
                decode_status(altered)

    def test_invalid_states_and_masks_rejected(self):
        for state, mask in [("C", 1), ("V", 0), ("V", 8), ("X", 0), ("V", -1), ("V", True), ("V", 1.5), ("", 0)]:
            with self.subTest(state=state, mask=mask), self.assertRaises(ValueError):
                encode_status(state, mask)

    def test_all_item_subsets(self):
        names = ("helmet", "shoes", "vest")
        for mask in range(1, 8):
            missing = [item for index, item in enumerate(names) if mask & (1 << index)]
            self.assertEqual(report_decision(report(missing=missing)), Decision("V", mask))

    def test_multi_person_union_only_explicit_negatives(self):
        r = report()
        r["people"] += [person(missing=("shoes",)), person("UNKNOWN", missing=("vest",))]
        self.assertEqual(report_decision(r), Decision("V", 3))

    def test_missing_detection_not_a_violation(self):
        people = [Detection("person", .9, (0, 0, 100, 200))]
        equipment = [Detection("helmet", .9, (20, 10, 40, 30)), Detection("shoes", .9, (20, 160, 40, 190))]
        r = assess(people, equipment, ("helmet", "shoes", "vest"))
        self.assertEqual(r["observation"], "UNKNOWN")
        self.assertEqual(report_decision(r), Decision("U"))

    def test_contradictory_helmet_not_missing(self):
        people = [Detection("person", .9, (0, 0, 100, 200))]
        r = assess(people, [Detection(label, .9, (20, 10, 40, 30)) for label in ("helmet", "no_helmet")], ("helmet", "shoes", "vest"))
        self.assertEqual(report_decision(r), Decision("U"))

    def test_unsupported_negative_not_turned_into_helmet(self):
        self.assertEqual(report_decision(report(missing=("mask",))), Decision("U"))

    def test_compliant_requires_all_three_and_people(self):
        self.assertEqual(report_decision(report("COMPLIANT")), Decision("C"))
        r = report("COMPLIANT"); r["required"] = ["helmet", "mask"]
        self.assertEqual(report_decision(r), Decision("U"))
        r = report("COMPLIANT"); r["people"][0]["present"] = ["helmet", "shoes"]
        self.assertEqual(report_decision(r), Decision("U"))
        r["people"] = []
        self.assertEqual(report_decision(r), Decision("U"))

    def test_no_person_and_fault_are_distinct(self):
        self.assertEqual(report_decision(report("NO_PERSON")), Decision("N"))
        for state in ("STARTING", "MODEL_ERROR", "CAMERA_LOST"):
            self.assertEqual(report_decision(report(state)), Decision("F"))

    def test_violation_debounce_time_and_samples(self):
        f = DecisionFilter()
        self.assertEqual(f.update(report(), 0), Decision("U"))
        self.assertEqual(f.update(report(), 1), Decision("U"))
        self.assertEqual(f.update(report(), 1.5), Decision("V", 1))

    def test_mask_changes_need_reconfirmation(self):
        f = DecisionFilter()
        for t in (0, 1, 1.5):
            f.update(report(), t)
        for t in (2, 3):
            self.assertEqual(f.update(report(missing=("helmet", "shoes")), t), Decision("U"))
        self.assertEqual(f.update(report(missing=("helmet", "shoes")), 3.5), Decision("V", 3))

    def test_clear_and_unknown_need_fresh_debounce(self):
        f = DecisionFilter()
        for t in (0, 1.5, 3):
            decision = f.update(report("COMPLIANT"), t)
        self.assertEqual(decision, Decision("C"))
        self.assertEqual(f.update(report("UNKNOWN"), 3.5), Decision("U"))
        self.assertEqual(f.update(report("COMPLIANT"), 4), Decision("U"))
        self.assertEqual(f.update(report("COMPLIANT"), 5.5), Decision("U"))
        self.assertEqual(f.update(report("COMPLIANT"), 7), Decision("C"))

    def test_sample_gap_and_duplicate_timestamp(self):
        f = DecisionFilter()
        f.update(report(), 1)
        with self.assertRaises(ValueError): f.update(report(), 1)
        self.assertEqual(f.update(report(), 5), Decision("U"))
        self.assertEqual(f.update(report(), 5.1), Decision("U"))


class LiveConfigAndModelTests(unittest.TestCase):
    def test_default_config_is_non_deployed_non_actuating(self):
        c = live.load_live_config()
        self.assertFalse(c["target"]["deployment_enabled"])
        self.assertFalse(c["actuators"]["enabled"])
        self.assertEqual(set(c["policy"]["required"]), {"helmet", "shoes", "vest"})

    def test_live_gate_cannot_be_bypassed_by_config(self):
        c = live.load_live_config(); c["actuators"]["enabled"] = True
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"; p.write_text(json.dumps(c), encoding="utf8")
            with self.assertRaises(ValueError): live.load_live_config(p)

    def detector(self):
        c = live.load_live_config()
        ppe, people = Mock(), Mock()
        ppe.names = dict(enumerate(c["models"]["ppe"]["expected_labels"]))
        people.names = {0: "person", 1: "bicycle"}
        ultra = Mock(); ultra.YOLO.side_effect = [ppe, people]
        with patch.dict(sys.modules, {"torch": Mock(), "ultralytics": ultra}):
            detector = live.LiveDetector(c)
        return detector, ppe, people

    def test_current_model_declares_missing_vest_capability(self):
        d, _, _ = self.detector()
        self.assertEqual(d.unsupported_items, ["vest"])

    def test_person_helmet_shoes_without_vest_is_unknown(self):
        d, ppe, people = self.detector()
        people.predict.return_value = [result(people.names, [0], [(0,0,100,200)], [.9])]
        ppe.predict.return_value = [result(ppe.names, [2,9], [(10,10,40,35),(10,160,40,190)], [.9,.9])]
        r = d.infer(NS(size=10))
        self.assertEqual(r["observation"], "UNKNOWN")
        self.assertEqual(report_decision(r), Decision("U"))

    def test_negative_helmet_and_shoes_are_person_associated(self):
        d, ppe, people = self.detector()
        people.predict.return_value = [result(people.names, [0], [(0,0,100,200)], [.9])]
        ppe.predict.return_value = [result(ppe.names, [6,8], [(10,10,40,35),(10,160,40,190)], [.9,.9])]
        r = d.infer(NS(size=10))
        self.assertEqual(report_decision(r), Decision("V", 3))
        self.assertEqual(people.predict.call_args.kwargs["classes"], [0])
        self.assertEqual(ppe.predict.call_args.kwargs["device"], "cpu")

    def test_unassociated_negative_is_unknown_not_area_empty(self):
        d, ppe, people = self.detector()
        people.predict.return_value = [result(people.names)]
        ppe.predict.return_value = [result(ppe.names, [6], [(10,10,40,35)], [.9])]
        self.assertEqual(report_decision(d.infer(NS(size=10))), Decision("U"))

    def test_model_capacity_faults(self):
        d, ppe, people = self.detector()
        people.predict.return_value = [result(people.names, [0]*128, [(0,0,100,200)]*128, [.9]*128)]
        ppe.predict.return_value = [result(ppe.names)]
        self.assertEqual(d.infer(NS(size=10))["observation"], "MODEL_ERROR")

    def test_import_entrypoints_has_no_camera_or_serial_io(self):
        with patch.dict(sys.modules, {"cv2": Mock(), "serial": Mock(), "ultralytics": Mock()}):
            import web_cctv_ai, detect_apd
            importlib.reload(web_cctv_ai); importlib.reload(detect_apd)
            sys.modules["cv2"].VideoCapture.assert_not_called()
            sys.modules["serial"].Serial.assert_not_called()
            sys.modules["ultralytics"].YOLO.assert_not_called()

    def test_serial_cli_requires_both_explicit_gates(self):
        with patch.object(live, "open_receiver") as opened, patch.object(live, "camera_worker") as camera:
            for args in (["--enable-serial"], ["--enable-serial", "--port", "COM3"], ["--port", "COM3"]):
                with self.assertRaises(SystemExit), patch("sys.stderr", new_callable=io.StringIO):
                    live.main(args)
            opened.assert_not_called(); camera.assert_not_called()

    def test_camera_indices_and_urls(self):
        self.assertEqual(live.camera_source("0"), 0)
        self.assertEqual(live.camera_source("rtsp://127.0.0.1:18554/live/0"), "rtsp://127.0.0.1:18554/live/0")


class SerialTransportTests(unittest.TestCase):
    def test_publisher_heartbeat_and_changes(self):
        stream = Mock(); stream.write.side_effect = lambda p: len(p)
        p = live.StatusPublisher(stream)
        self.assertTrue(p.send(Decision("V", 3), 0))
        self.assertFalse(p.send(Decision("V", 3), .499))
        self.assertTrue(p.send(Decision("V", 3), .5))
        self.assertTrue(p.send(Decision("F"), .6))
        self.assertEqual(stream.write.call_count, 3)

    def test_partial_write_is_a_fault(self):
        stream = Mock(); stream.write.return_value = 1
        p = live.StatusPublisher(stream)
        with self.assertRaises(OSError): p.send(Decision("C"), 0)
        self.assertIsNone(p.last)

    def test_receiver_handshake_no_commands_before_ready(self):
        stream = Mock(); stream.readline.side_effect = [b"OLD READY\n", b"READY - APD Receiver v2.2 [PPE1 LCD 500ms]\n"]
        factory = Mock(return_value=stream)
        self.assertIs(live.open_receiver("COM7", factory, clock=lambda: 0, sleep=lambda _: None), stream)
        stream.write.assert_not_called()
        factory.assert_called_once_with("COM7", 9600, timeout=.1, write_timeout=.25)

    def test_wrong_firmware_closes_without_writing(self):
        stream = Mock(); stream.readline.return_value = b"READY - APD3\n"
        clock = iter([0, 0, 7]).__next__
        with self.assertRaises(RuntimeError):
            live.open_receiver("COM7", lambda *a, **k: stream, clock=clock, sleep=lambda _: None)
        stream.close.assert_called_once(); stream.write.assert_not_called()

    def test_shared_camera_initial_unknown_not_safe(self):
        shared = live.SharedCamera()
        generation, captured, r, jpeg, error = shared.snapshot()
        self.assertEqual((generation, captured, jpeg, error), (0, 0, None, ""))
        self.assertEqual(r["observation"], "STARTING")
        shared.publish(report(), 12.0, b"jpeg")
        self.assertEqual(shared.snapshot()[0], 1)


class FreshnessTests(unittest.TestCase):
    def config(self):
        config = live.load_live_config()
        config["policy"].update(violation_seconds=0, clear_seconds=0, min_samples=2)
        return config

    def snapshot(self, generation, captured, observation="COMPLIANT"):
        return generation, captured, report(observation), None, ""

    def test_cached_frame_never_counts_as_fresh_inference(self):
        engine = live.FreshDecisionEngine(self.config())
        snapshot = self.snapshot(1, 10)
        self.assertEqual(engine.update(snapshot, 10), Decision("U"))
        for now in (10.1, 10.5, 11):
            self.assertEqual(engine.update(snapshot, now), Decision("U"))
        self.assertEqual(engine.update(self.snapshot(2, 11.1), 11.1), Decision("C"))

    def test_stalled_capture_changes_safe_to_fault_and_redebounces(self):
        engine = live.FreshDecisionEngine(self.config())
        engine.update(self.snapshot(1, 10), 10)
        self.assertEqual(engine.update(self.snapshot(2, 10.1), 10.1), Decision("C"))
        self.assertEqual(engine.update(self.snapshot(2, 10.1), 11.61), Decision("F"))
        self.assertEqual(engine.update(self.snapshot(3, 12), 12), Decision("U"))
        self.assertEqual(engine.update(self.snapshot(4, 12.1), 12.1), Decision("C"))

    def test_future_timestamp_faults(self):
        engine = live.FreshDecisionEngine(self.config())
        self.assertEqual(engine.update(self.snapshot(1, 11), 10), Decision("F"))

    def test_inference_runs_without_any_http_client(self):
        shared, stop = live.SharedCamera(), Mock()
        stop.is_set.return_value = False
        cv = Mock()
        cap = cv.VideoCapture.return_value
        cap.isOpened.return_value = True
        cap.read.side_effect = [(True, NS(size=1)), (False, None)]
        cv.imencode.return_value = (True, NS(tobytes=lambda: b"jpeg"))
        detector = Mock(); detector.unsupported_items = ["vest"]
        r = report("NO_PERSON"); r["detections"] = {"person": [], "ppe": []}
        detector.infer.return_value = r
        with patch.dict(sys.modules, {"cv2": cv}), patch.object(live, "LiveDetector", return_value=detector):
            live.camera_worker(shared, stop, live.load_live_config(), "0")
        detector.infer.assert_called_once()
        self.assertEqual(shared.snapshot()[2]["observation"], "CAMERA_LOST")
        cap.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
