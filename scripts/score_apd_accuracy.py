"""HOST-only observation scoring. No camera/ADB/serial/model execution.
This is NOT box mAP, event-level acceptance or a production release gate.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import statistics

ITEMS = ("vest", "shoes", "helmet")
TRUTHS = ("PRESENT", "ABSENT", "UNOBSERVABLE")
PREDICTIONS = ("PRESENT", "ABSENT", "UNKNOWN")
REQUIRED = ("run_id", "scenario_id", "trial_id", "observation_id", "item",
            "ground_truth", "prediction", "evidence_mode", "unknown_reason",
            "capture_ms", "decision_ms")


def number(value, label):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(label + " must be finite and nonnegative")
    return value


def ratio(a, b):
    return a / b if b else None


def score_rows(rows):
    results = {}
    seen = set()
    runs = set()
    trials = set()
    for item in ITEMS:
        results[item] = {
            "observations": 0,
            "confusion": {truth: {pred: 0 for pred in PREDICTIONS} for truth in TRUTHS},
            "unobservable_known_by_evidence": {"FRESH": 0, "CACHED": 0},
            "latencies_ms": [],
        }
    for index, row in enumerate(rows, 2):
        if any(key not in row or row[key] is None for key in REQUIRED):
            raise ValueError(f"row {index}: missing required fields")
        if any(not row[key].strip() for key in REQUIRED[:4]):
            raise ValueError(f"row {index}: empty observation identity")
        item, truth, pred, mode = (row[key] for key in
                                  ("item", "ground_truth", "prediction", "evidence_mode"))
        if item not in ITEMS or truth not in TRUTHS or pred not in PREDICTIONS:
            raise ValueError(f"row {index}: invalid item/truth/prediction")
        if mode not in ("FRESH", "CACHED", "NONE"):
            raise ValueError(f"row {index}: invalid evidence_mode")
        if pred != "UNKNOWN" and mode == "NONE":
            raise ValueError(f"row {index}: known prediction without evidence")
        if pred == "UNKNOWN" and not row["unknown_reason"].strip():
            raise ValueError(f"row {index}: UNKNOWN needs a reason")
        key = tuple(row[k] for k in REQUIRED[:4]) + (item,)
        if key in seen:
            raise ValueError(f"row {index}: duplicate observation/item")
        seen.add(key)
        runs.add(row["run_id"])
        trials.add(tuple(row[k] for k in REQUIRED[:3]))
        result = results[item]
        result["observations"] += 1
        result["confusion"][truth][pred] += 1
        if truth == "UNOBSERVABLE" and pred != "UNKNOWN":
            result["unobservable_known_by_evidence"][mode] += 1
        if bool(row["capture_ms"].strip()) != bool(row["decision_ms"].strip()):
            raise ValueError(f"row {index}: supply both latency timestamps or neither")
        if row["capture_ms"].strip():
            captured = number(row["capture_ms"], "capture_ms")
            decided = number(row["decision_ms"], "decision_ms")
            if decided < captured:
                raise ValueError(f"row {index}: decision precedes capture")
            if truth != "UNOBSERVABLE" and pred != "UNKNOWN":
                result["latencies_ms"].append(decided - captured)
    if not seen:
        raise ValueError("No observations: an empty template is NOT a successful accuracy test")
    for result in results.values():
        c = result["confusion"]
        present, absent = c["PRESENT"], c["ABSENT"]
        observable = sum(present.values()) + sum(absent.values())
        known = present["PRESENT"] + present["ABSENT"] + absent["PRESENT"] + absent["ABSENT"]
        latencies = sorted(result.pop("latencies_ms"))
        result.update({
            "observable_samples": observable,
            "violation_recall_including_unknown_as_unresolved": ratio(absent["ABSENT"], sum(absent.values())),
            "violation_precision_observable_only": ratio(absent["ABSENT"], absent["ABSENT"] + present["ABSENT"]),
            "false_alarm_on_visible_present": present["ABSENT"],
            "false_safe_on_visible_absent": absent["PRESENT"],
            "visible_absent_unresolved_unknown": absent["UNKNOWN"],
            "observable_decision_coverage": ratio(known, observable),
            "correct_observable_fraction_unknown_not_dropped": ratio(present["PRESENT"] + absent["ABSENT"], observable),
            "unobservable_unknown_fraction": ratio(c["UNOBSERVABLE"]["UNKNOWN"], sum(c["UNOBSERVABLE"].values())),
            "latency_count": len(latencies),
            "decision_latency_median_ms": statistics.median(latencies) if latencies else None,
            "decision_latency_p95_ms": latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
        })
    return {
        "stage": "DIAGNOSTIC_OBSERVATIONS_ONLY", "hardware_accessed": False,
        "production_ready": False, "runs": sorted(runs), "trial_count": len(trials),
        "observation_item_count": len(seen), "items": results,
        "limitations": [
            "Rows must be independently human-labeled, including missed people as UNKNOWN.",
            "Repeated frames are correlated: trial_count is not statistical confidence.",
            "No box IoU/mAP, event-level alarm rate, ID switch or removal delay computed.",
            "Precision only covers observable truth; inspect unobservable fresh negatives separately.",
            "Known CACHED results on unobservable regions need TTL/view evidence review; not automatically wrong.",
            "Latency is capture-to-decision only, not PPE-removal-to-alarm delay.",
            "Synthetic observations cannot establish real detector accuracy.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.observations.open(newline="", encoding="utf-8-sig") as source:
            report = score_rows(csv.DictReader(source))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Do not overwrite an older evidence report.
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, allow_nan=False)
            output.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, "ACCURACY NOT COMPLETED: " + str(exc) + "\n")
    print("HOST diagnostic report:", args.output.resolve())
    print("Observations:", report["observation_item_count"], "/ Production: NOT ACCEPTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
