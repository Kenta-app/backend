"""Prepare a grouped evidence-aware stance feasibility experiment.

The script reuses only adjudicated development material.  It creates three
representations over one identical grouped split:

* document_prefix: current full-article input (truncated by FNCDataset)
* oracle_evidence: adjudicated evidence for related cases
* retrieved_evidence: automatically selected evidence sentences

The frozen prospective evaluation set is never read by this script.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoTokenizer


LABELS = ("unrelated", "discuss", "agree", "disagree")
REPRESENTATIONS = (
    "document_prefix",
    "oracle_evidence",
    "retrieved_evidence",
    "oracle_evidence_no_title",
    "retrieved_evidence_no_title",
)
SPANISH_STOPWORDS = {
    "a", "al", "algo", "ante", "bajo", "con", "contra", "de", "del", "desde", "donde",
    "e", "el", "ella", "en", "entre", "era", "es", "esa", "ese", "esta", "este", "fue",
    "ha", "hasta", "hay", "la", "las", "le", "lo", "los", "más", "muy", "no", "o", "para",
    "pero", "por", "que", "se", "según", "ser", "si", "sin", "sobre", "su", "sus", "también",
    "un", "una", "y", "ya",
}
VERDICT_CUES = (
    "es falso", "es falsa", "falso", "falsa", "no es cierto", "no ocurrió", "no ocurrio",
    "desmint", "refut", "negó", "nego", "rechaz", "carece de sustento", "sin sustento",
    "imprecis", "engaños", "enganos", "incorrect", "rectific", "en realidad", "sino",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn")
    text = re.sub(r"[^\w%]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def content_tokens(text: str) -> set[str]:
    return {
        token for token in normalized(text).split()
        if len(token) > 2 and token not in SPANISH_STOPWORDS
    }


def sentence_split(text: str) -> list[str]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return []
    pieces = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"“])", cleaned)
    return [piece.strip() for piece in pieces if piece.strip()]


def relevance_scores(claim: str, sentences: list[str]) -> list[float]:
    if not sentences:
        return []
    try:
        vectorizer = TfidfVectorizer(
            lowercase=True, strip_accents="unicode", ngram_range=(1, 2), sublinear_tf=True,
        )
        matrix = vectorizer.fit_transform([claim, *sentences])
        cosine = cosine_similarity(matrix[0:1], matrix[1:]).ravel()
    except ValueError:
        cosine = np.zeros(len(sentences), dtype=float)
    claim_tokens = content_tokens(claim)
    claim_norm = normalized(claim)
    scores: list[float] = []
    for index, sentence in enumerate(sentences):
        sentence_tokens = content_tokens(sentence)
        overlap = len(claim_tokens & sentence_tokens) / max(1, len(claim_tokens))
        exact_bonus = 1.5 if claim_norm and claim_norm in normalized(sentence) else 0.0
        scores.append(float(cosine[index]) + overlap + exact_bonus)
    return scores


def verdict_score(sentence: str, claim: str, base_score: float) -> float:
    lowered = normalized(sentence)
    cue_count = sum(cue in lowered for cue in VERDICT_CUES)
    if not cue_count:
        return -1.0
    claim_overlap = len(content_tokens(sentence) & content_tokens(claim)) / max(1, len(content_tokens(claim)))
    return base_score + (0.35 * cue_count) + claim_overlap


def add_title(title: str, body: str) -> str:
    title = " ".join((title or "").split())
    body = " ".join((body or "").split())
    if not title:
        return body
    if normalized(body).startswith(normalized(title)):
        return body
    return f"{title}. {body}".strip()


def fit_token_budget(tokenizer, claim: str, pieces: list[str], max_length: int) -> str:
    budget = max_length - len(tokenizer(claim, add_special_tokens=False)["input_ids"]) - tokenizer.num_special_tokens_to_add(pair=True)
    budget = max(24, budget)
    kept: list[str] = []
    used = 0
    for piece in pieces:
        piece = " ".join((piece or "").split())
        if not piece or piece in kept:
            continue
        ids = tokenizer(piece, add_special_tokens=False)["input_ids"]
        remaining = budget - used
        if remaining <= 0:
            break
        if len(ids) <= remaining:
            kept.append(piece)
            used += len(ids)
        elif not kept:
            kept.append(tokenizer.decode(ids[:remaining], skip_special_tokens=True))
            used = budget
    return " ".join(kept).strip()


def retrieve_context(row: dict, tokenizer, max_length: int, *, include_title: bool = True) -> tuple[str, dict]:
    claim = row["claim"]
    title = row.get("title") or ""
    sentences = sentence_split(row["article"])
    if not sentences:
        pieces = [title, row["article"]] if include_title else [row["article"]]
        return fit_token_budget(tokenizer, claim, pieces, max_length), {
            "sentence_count": 0, "primary_index": None, "verdict_index": None,
        }
    scores = relevance_scores(claim, sentences)
    primary = max(range(len(sentences)), key=lambda index: scores[index])
    selected = {primary}
    if primary > 0:
        selected.add(primary - 1)
    if primary + 1 < len(sentences):
        selected.add(primary + 1)
    verdict_candidates = [
        (verdict_score(sentence, claim, scores[index]), index)
        for index, sentence in enumerate(sentences)
    ]
    verdict_value, verdict_index = max(verdict_candidates)
    if verdict_value >= 0:
        selected.add(verdict_index)
        if verdict_index > 0:
            selected.add(verdict_index - 1)
        if verdict_index + 1 < len(sentences):
            selected.add(verdict_index + 1)
    ordered = [sentences[index] for index in sorted(selected)]
    pieces = [title, *ordered] if include_title else ordered
    context = fit_token_budget(tokenizer, claim, pieces, max_length)
    evidence_tokens = content_tokens(row.get("final_evidence") or "")
    retrieved_tokens = content_tokens(context)
    token_recall = len(evidence_tokens & retrieved_tokens) / max(1, len(evidence_tokens)) if row["final_label"] != "unrelated" else None
    return context, {
        "sentence_count": len(sentences),
        "primary_index": primary,
        "primary_score": scores[primary],
        "verdict_index": verdict_index if verdict_value >= 0 else None,
        "selected_indexes": sorted(selected),
        "evidence_token_recall": token_recall,
        "evidence_recovered_at_0_60": token_recall >= 0.60 if token_recall is not None else None,
    }


def oracle_context(
    row: dict,
    retrieved: str,
    tokenizer,
    max_length: int,
    *,
    include_title: bool = True,
) -> str:
    if row["final_label"] == "unrelated":
        return retrieved
    evidence = (row.get("final_evidence") or "").strip()
    pieces = [row.get("title") or "", evidence] if include_title else [evidence]
    return fit_token_budget(tokenizer, row["claim"], pieces, max_length)


def grouped_split(rows: list[dict], seed: int, trials: int = 30000) -> dict[str, str]:
    """Search deterministic grouped assignments with balanced per-label targets."""
    split_names = ("train", "validation", "test")
    proportions = np.array([0.60, 0.20, 0.20], dtype=float)
    group_rows: dict[str, list[dict]] = {}
    for row in rows:
        group_rows.setdefault(row["group_id"], []).append(row)
    group_ids = sorted(group_rows)
    overall = Counter(row["final_label"] for row in rows)
    target_total = proportions * len(rows)
    target_labels = {
        label: proportions * overall[label] for label in LABELS
    }
    rng = np.random.default_rng(seed)
    best_score = float("inf")
    best_assignment: dict[str, int] | None = None
    for _ in range(trials):
        candidate = rng.choice(3, size=len(group_ids), p=proportions)
        total = np.zeros(3, dtype=float)
        label_counts = {label: np.zeros(3, dtype=float) for label in LABELS}
        group_counts = np.zeros(3, dtype=float)
        for group_id, split_index in zip(group_ids, candidate, strict=True):
            group_counts[split_index] += 1
            total[split_index] += len(group_rows[group_id])
            for row in group_rows[group_id]:
                label_counts[row["final_label"]][split_index] += 1
        if np.any(group_counts == 0) or any(np.any(label_counts[label] == 0) for label in LABELS):
            continue
        total_error = np.sum(((total - target_total) / np.maximum(1.0, target_total)) ** 2)
        label_error = sum(
            np.sum(((label_counts[label] - target_labels[label]) / np.maximum(1.0, target_labels[label])) ** 2)
            for label in LABELS
        )
        score = float((2.0 * label_error) + total_error)
        if score < best_score:
            best_score = score
            best_assignment = dict(zip(group_ids, candidate.tolist(), strict=True))
    if best_assignment is None:
        raise RuntimeError("Could not find a valid grouped stratified assignment")
    return {
        row["pair_id"]: split_names[best_assignment[row["group_id"]]]
        for row in rows
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_representation(output_dir: Path, name: str, rows: list[dict], context_field: str) -> list[Path]:
    written: list[Path] = []
    for split in ("train", "validation", "test"):
        split_rows = [row for row in rows if row["split"] == split]
        bodies = []
        stances = []
        metadata = []
        for body_id, row in enumerate(split_rows, start=1):
            bodies.append({"Body ID": body_id, "articleBody": row[context_field]})
            stances.append({"Headline": row["claim"], "Body ID": body_id, "Stance": row["final_label"]})
            metadata.append({
                "Body ID": body_id, "pair_id": row["pair_id"], "group_id": row["group_id"],
                "article_id": row["article_id"], "source_name": row["source_name"],
                "final_label": row["final_label"], "representation": name,
            })
        fnc_dir = output_dir / name / "fnc"
        body_path = fnc_dir / f"{split}_bodies.csv"
        stance_path = fnc_dir / f"{split}_stances.csv"
        metadata_path = fnc_dir / f"{split}_metadata.csv"
        write_csv(body_path, bodies, ["Body ID", "articleBody"])
        write_csv(stance_path, stances, ["Headline", "Body ID", "Stance"])
        write_csv(metadata_path, metadata, list(metadata[0]))
        written.extend([body_path, stance_path, metadata_path])
    return written


def load_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload:
            if row.get("quality_status") != "include" or row.get("final_label") not in LABELS:
                continue
            copied = dict(row)
            copied["source_artifact"] = str(path)
            rows.append(copied)
    if len(rows) != 198:
        raise ValueError(f"Expected 198 included evidence-annotated rows, got {len(rows)}")
    if len({row["pair_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate pair_id in evidence-aware development rows")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-02b", type=Path, required=True)
    parser.add_argument("--production-03", type=Path, required=True)
    parser.add_argument("--production-04", type=Path, required=True)
    parser.add_argument("--tokenizer-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=192)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    source_paths = [args.calibration_02b.resolve(), args.production_03.resolve(), args.production_04.resolve()]
    rows = load_rows(source_paths)
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer_dir.resolve()), local_files_only=True)
    assignment = grouped_split(rows, args.seed)
    prepared: list[dict] = []
    for row in rows:
        retrieved, retrieval = retrieve_context(row, tokenizer, args.max_length)
        retrieved_no_title, _ = retrieve_context(
            row, tokenizer, args.max_length, include_title=False,
        )
        prepared.append({
            **row,
            "split": assignment[row["pair_id"]],
            "document_context": add_title(row.get("title") or "", row["article"]),
            "retrieved_context": retrieved,
            "oracle_context": oracle_context(row, retrieved, tokenizer, args.max_length),
            "retrieved_context_no_title": retrieved_no_title,
            "oracle_context_no_title": oracle_context(
                row,
                retrieved_no_title,
                tokenizer,
                args.max_length,
                include_title=False,
            ),
            **retrieval,
        })

    split_groups = {
        split: {row["group_id"] for row in prepared if row["split"] == split}
        for split in ("train", "validation", "test")
    }
    if any(split_groups[a] & split_groups[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("Group leakage detected")
    for split in ("train", "validation", "test"):
        counts = Counter(row["final_label"] for row in prepared if row["split"] == split)
        if set(counts) != set(LABELS):
            raise ValueError(f"Split {split} is missing labels: {counts}")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    written += export_representation(output_dir, "document_prefix", prepared, "document_context")
    written += export_representation(output_dir, "oracle_evidence", prepared, "oracle_context")
    written += export_representation(output_dir, "retrieved_evidence", prepared, "retrieved_context")
    written += export_representation(
        output_dir, "oracle_evidence_no_title", prepared, "oracle_context_no_title",
    )
    written += export_representation(
        output_dir, "retrieved_evidence_no_title", prepared, "retrieved_context_no_title",
    )
    audit_fields = [
        "pair_id", "group_id", "article_id", "source_name", "final_label", "split",
        "claim", "final_evidence", "document_context", "oracle_context", "retrieved_context",
        "oracle_context_no_title", "retrieved_context_no_title",
        "sentence_count", "primary_index", "primary_score", "verdict_index", "selected_indexes",
        "evidence_token_recall", "evidence_recovered_at_0_60",
    ]
    audit_path = output_dir / "evidence_retrieval_audit.csv"
    write_csv(audit_path, prepared, audit_fields)
    written.append(audit_path)

    related = [row for row in prepared if row["final_label"] != "unrelated"]
    manifest = {
        "status": "PREPARED_DEVELOPMENT_ONLY_NOT_FINAL_TEST",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "48-hour evidence-aware stance feasibility spike",
        "frozen_prospective_set_used": False,
        "records": len(prepared),
        "groups": len({row["group_id"] for row in prepared}),
        "label_counts": dict(Counter(row["final_label"] for row in prepared)),
        "split_counts": {
            split: {
                "records": sum(row["split"] == split for row in prepared),
                "groups": len(split_groups[split]),
                "labels": dict(Counter(row["final_label"] for row in prepared if row["split"] == split)),
            }
            for split in ("train", "validation", "test")
        },
        "retrieval_diagnostic": {
            "related_records": len(related),
            "mean_evidence_token_recall": float(np.mean([row["evidence_token_recall"] for row in related])),
            "recovered_at_token_recall_0_60": sum(row["evidence_recovered_at_0_60"] for row in related),
            "recovery_rate_at_0_60": sum(row["evidence_recovered_at_0_60"] for row in related) / len(related),
        },
        "representations": list(REPRESENTATIONS),
        "max_length": args.max_length,
        "seed": args.seed,
        "tokenizer_dir": str(args.tokenizer_dir.resolve()),
        "source_artifacts": [
            {"path": str(path), "sha256": sha256_file(path)} for path in source_paths
        ],
        "artifacts": {},
    }
    manifest_path = output_dir / "manifest.json"
    for path in written:
        manifest["artifacts"][str(path.relative_to(output_dir)).replace("\\", "/")] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
