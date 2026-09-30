"""Print or execute the predeclared local stance adaptation experiments."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def command_for(
    *, model: str, split_dir: Path, output_dir: Path, seed: int,
    epochs: int, batch_size: int, learning_rate: float,
) -> list[str]:
    return [
        sys.executable, "-m", "app.ml.training.train_stance",
        "--model_name", model,
        "--train_stances", str(split_dir / "train_stances.csv"),
        "--train_bodies", str(split_dir / "train_bodies.csv"),
        "--val_stances", str(split_dir / "validation_stances.csv"),
        "--val_bodies", str(split_dir / "validation_bodies.csv"),
        "--test_stances", str(split_dir / "test_stances.csv"),
        "--test_bodies", str(split_dir / "test_bodies.csv"),
        "--output_dir", str(output_dir),
        "--seed", str(seed),
        "--epochs", str(epochs),
        "--batch_size", str(batch_size),
        "--lr", str(learning_rate),
        "--train_sampling", "shuffle",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-dir", type=Path, required=True, help="Directory containing the six FNC-style split files")
    parser.add_argument("--fnc-checkpoint", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("output/stance_es_pe_v1/experiments"))
    parser.add_argument("--seeds", default="42,123,2026")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    split_dir = args.split_dir.resolve()
    required = [split_dir / f"{split}_{kind}.csv" for split in ("train", "validation", "test") for kind in ("stances", "bodies")]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"missing split files: {missing}")
    seeds = [int(value.strip()) for value in args.seeds.split(",") if value.strip()]
    experiments = {
        "E1_mbert_fnc_adapted": args.fnc_checkpoint,
        "E2_xlmr_local": "xlm-roberta-base",
    }
    plan = []
    for name, model in experiments.items():
        for seed in seeds:
            output_dir = args.output_root.resolve() / name / f"seed_{seed}"
            command = command_for(
                model=model, split_dir=split_dir, output_dir=output_dir, seed=seed,
                epochs=args.epochs, batch_size=args.batch_size, learning_rate=args.learning_rate,
            )
            plan.append({"experiment": name, "seed": seed, "model": model, "output_dir": str(output_dir), "command": command})
            print(subprocess.list2cmdline(command))
            if args.execute:
                subprocess.run(command, check=True)
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "experiment_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
