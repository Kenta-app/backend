from __future__ import annotations

import csv
import unittest
from collections import Counter, defaultdict

from scripts.stance_corpus import (
    VALID_LABELS,
    assign_grouped_splits,
    derive_final_label,
    export_fnc_splits,
    validate_rows,
)


def make_row(index: int, label: str, group: str | None = None) -> dict[str, str]:
    return {
        "pair_id": f"PE-{index:03d}",
        "corpus_version": "stance_es_pe_v1",
        "intended_use": "train_candidate",
        "batch_id": "test",
        "group_id": group or f"event-{index}",
        "event_id": group or f"event-{index}",
        "claim_id": f"claim-{index}",
        "article_id": f"article-{group or index}",
        "pair_construction": "source_pair",
        "source_name": "Fuente",
        "title": "Título",
        "original_url": f"https://example.test/{index}",
        "published_at": "2026-01-01",
        "claim": f"Este es el claim número {index} con suficiente longitud.",
        "article": "Artículo peruano de prueba. " * 30,
        "annotator_1": "A1",
        "label_annotator_1": label,
        "annotator_2": "A2",
        "label_annotator_2": label,
        "adjudicated_label": "",
        "adjudication_note": "",
        "final_label": "",
        "quality_status": "include",
        "quality_flags": "",
        "split": "",
    }


class StanceCorpusTests(unittest.TestCase):
    def test_final_label_requires_two_annotations_or_adjudication(self):
        label, flags = derive_final_label({"label_annotator_1": "agree", "label_annotator_2": "agree"})
        self.assertEqual(label, "agree")
        self.assertFalse(flags)

        label, flags = derive_final_label({"label_annotator_1": "agree", "label_annotator_2": "discuss"})
        self.assertEqual(label, "")
        self.assertIn("unadjudicated_disagreement", flags)

        label, flags = derive_final_label({
            "label_annotator_1": "agree", "label_annotator_2": "discuss",
            "adjudicated_label": "discuss", "adjudication_note": "El artículo solo atribuye la versión.",
        })
        self.assertEqual(label, "discuss")
        self.assertFalse(flags)

    def test_validation_flags_missing_provenance(self):
        row = make_row(1, "agree")
        row["label_annotator_2"] = ""
        validated, report = validate_rows([row])
        self.assertEqual(validated[0]["quality_status"], "review")
        self.assertEqual(validated[0]["final_label"], "")
        self.assertEqual(report["eligible_rows"], 0)

    def test_grouped_split_is_deterministic_and_has_no_leakage(self):
        rows = []
        index = 0
        for label in VALID_LABELS:
            for group_number in range(10):
                group = f"{label}-event-{group_number}"
                for _ in range(2):
                    index += 1
                    rows.append(make_row(index, label, group))
        validated, _ = validate_rows(rows)
        first = assign_grouped_splits(validated, seed=42)
        second = assign_grouped_splits(validated, seed=42)
        self.assertEqual([row["split"] for row in first], [row["split"] for row in second])

        splits_by_group = defaultdict(set)
        for row in first:
            splits_by_group[row["group_id"]].add(row["split"])
        self.assertTrue(all(len(splits) == 1 for splits in splits_by_group.values()))
        self.assertEqual(Counter(row["split"] for row in first), {"train": 48, "validation": 16, "test": 16})
        for split in ("train", "validation", "test"):
            self.assertEqual(set(row["final_label"] for row in first if row["split"] == split), set(VALID_LABELS))

    def test_export_fnc_splits_keeps_metadata_alignment(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            from pathlib import Path

            rows = []
            for index, label in enumerate(VALID_LABELS, start=1):
                row = make_row(index, label)
                row["split"] = ("train", "validation", "test", "train")[index - 1]
                rows.append(row)
            output_dir = Path(directory)
            outputs = export_fnc_splits(rows, output_dir)
            self.assertEqual(outputs["train"]["rows"], 2)
            with (output_dir / "train_stances.csv").open(encoding="utf-8", newline="") as handle:
                stances = list(csv.DictReader(handle))
            with (output_dir / "train_metadata.csv").open(encoding="utf-8", newline="") as handle:
                metadata = list(csv.DictReader(handle))
            self.assertEqual([row["Body ID"] for row in stances], [row["Body ID"] for row in metadata])
            self.assertEqual([row["pair_id"] for row in metadata], ["PE-001", "PE-004"])

    def test_locked_group_cannot_cross_splits(self):
        left = make_row(1, "agree", "same-event")
        right = make_row(2, "disagree", "same-event")
        left["split"] = "train"
        right["split"] = "test"
        validated, _ = validate_rows([left, right])
        with self.assertRaisesRegex(ValueError, "group leakage"):
            assign_grouped_splits(validated)


if __name__ == "__main__":
    unittest.main()
