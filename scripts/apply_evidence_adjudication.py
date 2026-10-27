"""Apply the protocol-based decisions approved for the evidence pilot conflicts."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


DECISIONS = {
    "ev_bf61b78be2520635": (
        "exclude_insufficient_context", "",
        "El título de un resumen diario no constituye una afirmación verificable y la fuente cubre solo uno de sus posibles temas.",
    ),
    "ev_1d6149deb908bdac": (
        "exclude_insufficient_context", "",
        "El título de un resumen diario no constituye una afirmación verificable y la fuente cubre solo uno de sus posibles temas.",
    ),
    "ev_93650d861cc91f90": (
        "exclude_insufficient_context", "",
        "El título de columna no formula una proposición verificable y la evidencia trata un asunto distinto.",
    ),
    "ev_52347c4cc2c2693d": (
        "exclude_insufficient_context", "",
        "El título de un resumen diario no constituye una afirmación verificable y la fuente cubre solo uno de sus posibles temas.",
    ),
    "ev_9b9f1a8ef9de535a": (
        "include", "discusses",
        "La fuente aborda seguridad y los primeros cien días, pero no confirma que recuperar el orden sea lo más importante.",
    ),
    "ev_b24500736c5080d6": (
        "include", "discusses",
        "La fuente trata el voto exterior y sus resultados, pero no sustenta las respuestas de especialistas ni todo el procesamiento descrito.",
    ),
    "ev_ad04073dc195e610": (
        "include", "discusses",
        "Confirma la felicitación de Xi, pero no el propósito adicional de afianzar la alianza estratégica.",
    ),
    "ev_e215325541fc001f": (
        "include", "discusses",
        "La fuente presenta un corte del conteo oficial, pero no demuestra literalmente un seguimiento en tiempo real.",
    ),
    "ev_37b86cf10c195f36": (
        "include", "discusses",
        "Confirma la felicitación de Xi, pero no el propósito adicional de afianzar la alianza estratégica.",
    ),
    "ev_80297002f5a7bec0": (
        "include", "discusses",
        "Confirma coordinaciones de transferencia, pero no la reunión específica entre Vinelli y el premier.",
    ),
    "ev_03fcac7ce336d455": (
        "include", "discusses",
        "La fuente describe negociaciones sobre comisiones, pero no identifica las presidencias concretas a las que apunta cada bancada.",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = tuple(reader.fieldnames or ())

    found = {row.get("evidence_id", "").strip() for row in rows}
    if found != set(DECISIONS):
        missing = sorted(set(DECISIONS) - found)
        unexpected = sorted(found - set(DECISIONS))
        raise SystemExit(f"Adjudication set mismatch. Missing={missing}; unexpected={unexpected}")

    for row in rows:
        status, stance, rationale = DECISIONS[row["evidence_id"].strip()]
        row["final_status"] = status
        row["final_stance"] = stance
        row["rationale"] = rationale

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Applied {len(rows)} adjudication decisions to {args.output}")


if __name__ == "__main__":
    main()
