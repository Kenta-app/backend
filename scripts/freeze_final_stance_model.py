"""Write a cryptographic freeze manifest for the final stance checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_root", type=Path, required=True)
    parser.add_argument("--repository_root", type=Path, required=True)
    args = parser.parse_args()
    model_root = args.model_root.resolve()
    repository_root = args.repository_root.resolve()
    checkpoint = model_root / "best_model"
    required_checkpoint_files = (
        "config.json",
        "model.safetensors",
        "serving_config.json",
        "tokenizer_config.json",
        "tokenizer.json",
    )
    missing = [name for name in required_checkpoint_files if not (checkpoint / name).exists()]
    if missing:
        raise FileNotFoundError(f"Incomplete checkpoint; missing: {', '.join(missing)}")

    checkpoint_files = {
        name: file_record(checkpoint / name) for name in required_checkpoint_files
    }
    tree_material = "\n".join(
        f"{name}\t{record['sha256']}" for name, record in sorted(checkpoint_files.items())
    ).encode("utf-8")
    supporting_paths = {
        "training_history": model_root / "training_history.json",
        "training_run_manifest": model_root / "final_training_manifest.json",
        "training_data_manifest": model_root / "training_data" / "final_training_data_manifest.json",
        "development_multiseed_metrics": repository_root / "output" / "stance_es_pe_v1" / "evidence_aware_spike_2026_09_28" / "multiseed" / "multiseed_aggregate.json",
        "final_model_protocol": repository_root / "output" / "stance_es_pe_v1" / "FINAL_MODEL_PROTOCOL_2026_09_28.md",
        "training_entrypoint": repository_root / "scripts" / "train_stance_fixed_epochs.py",
        "evidence_retriever": repository_root / "app" / "ml" / "evidence_retriever.py",
        "pipeline": repository_root / "app" / "ml" / "pipeline.py",
    }
    for label, path in supporting_paths.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing supporting artifact {label}: {path}")

    payload = {
        "status": "FROZEN_NOT_YET_EXTERNALLY_EVALUATED_NOT_PUBLICLY_ENABLED",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_version": "stance_es_pe_v1",
        "model_role": "final_evidence_aware_stance_candidate",
        "input_contract": {
            "text_a": "stance_target",
            "text_b": "article_title_plus_automatically_retrieved_evidence",
            "retriever": "tfidf_overlap_verdict_windows_v1",
            "max_length": 192,
        },
        "training": {
            "records": 198,
            "model_family": "bert-base-multilingual-cased",
            "seed": 42,
            "fixed_epochs": 4,
            "batch_size": 4,
            "learning_rate": 2e-5,
            "loss": "focal_gamma_2_with_class_weights",
        },
        "checkpoint": {
            "path": str(checkpoint),
            "files": checkpoint_files,
            "tree_sha256": hashlib.sha256(tree_material).hexdigest(),
        },
        "supporting_artifacts": {
            label: file_record(path) for label, path in supporting_paths.items()
        },
        "evaluation_state": {
            "development_complete": True,
            "legacy_operational_gold_inference_run": False,
            "new_four_class_challenge_evaluation_complete": False,
            "threshold_tuning_after_freeze_allowed": False,
        },
        "deployment_state": {
            "stance_public_enabled": False,
            "reason": "Awaiting external operational and four-class challenge evaluation.",
        },
    }
    output_path = model_root / "model_freeze_manifest.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(output_path), "checkpoint_tree_sha256": payload["checkpoint"]["tree_sha256"]}))


if __name__ == "__main__":
    main()
