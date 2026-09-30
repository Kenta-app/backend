from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_MODEL_FILES = (
    "model_freeze_manifest.json",
    "serving_config.json",
    "stage_a_relevance.joblib",
    "stage_a_base_nli/config.json",
    "stage_a_base_nli/model.safetensors",
    "stage_a_base_nli/tokenizer_config.json",
    "stage_a_base_nli/tokenizer.json",
    "stage_b_relation/config.json",
    "stage_b_relation/model.safetensors",
    "stage_b_relation/tokenizer_config.json",
    "stage_b_relation/tokenizer.json",
)

SOURCE_FILES = (
    "app/ml/stance_classifier.py",
    "app/ml/pipeline.py",
    "scripts/train_stance_v2_hierarchical.py",
    "scripts/Run-StanceV2Final.ps1",
    "tests/test_stance_v2_serving.py",
)

TEST_MODULES = (
    "tests.test_stance_v2_serving",
    "tests.test_fakenews_components",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, base: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(base).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def package_versions() -> dict[str, str | None]:
    names = ("joblib", "numpy", "scikit-learn", "torch", "transformers")
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def run_tests(repo_root: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", *TEST_MODULES]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "output_tail": output[-4000:],
    }


def run_smoke(model_dir: Path, repo_root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(repo_root))
    from app.ml.stance_classifier import StanceClassifier

    classifier = StanceClassifier(str(model_dir))
    loaded = classifier.load()
    if not loaded:
        return {"passed": False, "load_error": classifier.load_error}

    prediction = classifier.predict(
        "El Minsa confirmó que las vacunas contra la COVID-19 contienen microchips.",
        (
            "Es falso que las vacunas contra la COVID-19 contengan microchips. "
            "El Ministerio de Salud desmintió esa afirmación y explicó que no existe "
            "ningún componente electrónico en las dosis aplicadas en el Perú."
        ),
    )
    probabilities = prediction.get("probabilities", {})
    labels_ok = set(probabilities) == {"unrelated", "discuss", "agree", "disagree"}
    probability_sum = sum(float(value) for value in probabilities.values())
    passed = labels_ok and abs(probability_sum - 1.0) <= 0.001
    return {
        "passed": passed,
        "loaded": loaded,
        "input_kind": "synthetic_refutation_smoke_only",
        "prediction": prediction,
        "probability_sum": probability_sum,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit the frozen stance-v2 runtime without reading external challenge data."
    )
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--run-smoke", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    model_dir = args.model_dir.resolve()
    output_path = model_dir / "runtime_package_audit.json"

    missing_model_files = [name for name in REQUIRED_MODEL_FILES if not (model_dir / name).is_file()]
    missing_source_files = [name for name in SOURCE_FILES if not (repo_root / name).is_file()]

    serving_config = json.loads((model_dir / "serving_config.json").read_text(encoding="utf-8"))
    freeze_manifest = json.loads((model_dir / "model_freeze_manifest.json").read_text(encoding="utf-8"))
    configuration_checks = {
        "hierarchical_architecture": serving_config.get("architecture") == "hierarchical_stance_v2",
        "four_expected_labels": serving_config.get("label_names")
        == ["unrelated", "discuss", "agree", "disagree"],
        "public_exposure_disabled": serving_config.get("public_enabled") is False,
        "awaiting_external_evaluation": freeze_manifest.get("status")
        == "FROZEN_AWAITING_CHALLENGE_05_AND_OPERATIONAL_EVALUATION",
        "challenge_05_not_read_by_training": freeze_manifest.get("separation", {}).get(
            "challenge_05_read_by_training_script"
        )
        is False,
    }

    model_records = [file_record(model_dir / name, model_dir) for name in REQUIRED_MODEL_FILES if (model_dir / name).is_file()]
    source_records = [file_record(repo_root / name, repo_root) for name in SOURCE_FILES if (repo_root / name).is_file()]
    test_result = run_tests(repo_root) if args.run_tests else {"executed": False}
    smoke_result = run_smoke(model_dir, repo_root) if args.run_smoke else {"executed": False}

    tests_ok = test_result.get("passed", True) if args.run_tests else True
    smoke_ok = smoke_result.get("passed", True) if args.run_smoke else True
    passed = (
        not missing_model_files
        and not missing_source_files
        and all(configuration_checks.values())
        and tests_ok
        and smoke_ok
    )

    audit = {
        "audit_status": "PASS" if passed else "FAIL",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": (
            "Frozen stance-v2 runtime package only. Challenge 05 was not opened, "
            "predicted, tuned on, or otherwise consumed."
        ),
        "model_dir": str(model_dir),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "packages": package_versions(),
        },
        "configuration_checks": configuration_checks,
        "missing_model_files": missing_model_files,
        "missing_source_files": missing_source_files,
        "model_files": model_records,
        "model_files_total_bytes": sum(item["bytes"] for item in model_records),
        "runtime_source_files": source_records,
        "unit_tests": test_result,
        "real_model_smoke": smoke_result,
    }
    output_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"audit_status": audit["audit_status"], "output": str(output_path)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
