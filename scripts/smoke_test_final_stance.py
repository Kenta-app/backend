"""Load the frozen checkpoint and run one development smoke case per class."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.ml.stance_classifier import StanceClassifier


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_dir", type=Path, required=True)
    parser.add_argument("--stances", type=Path, required=True)
    parser.add_argument("--bodies", type=Path, required=True)
    args = parser.parse_args()
    classifier = StanceClassifier(str(args.model_dir.resolve()))
    if not classifier.load():
        raise RuntimeError(classifier.load_error)
    stances = read_csv(args.stances)
    bodies = {row["Body ID"]: row["articleBody"] for row in read_csv(args.bodies)}
    selected = {}
    for row in stances:
        selected.setdefault(row["Stance"], row)
    results = []
    for label in ("unrelated", "discuss", "agree", "disagree"):
        row = selected[label]
        prediction = classifier.predict(row["Headline"], bodies[row["Body ID"]])
        results.append(
            {
                "expected": label,
                "predicted": prediction["label"],
                "confidence": prediction["confidence"],
                "pass": prediction["label"] == label,
            }
        )
    payload = {"status": "PASS" if all(row["pass"] for row in results) else "FAIL", "cases": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
