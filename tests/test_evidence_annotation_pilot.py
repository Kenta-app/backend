from collections import Counter

from scripts.build_evidence_annotation_pilot import evidence_id, select_balanced
from scripts.evaluate_evidence_annotations import bootstrap_macro_f1
from scripts.run_evidence_end_to_end_pilot import stratified_v4_blind_sample


def row(number: int, stance: str, *, domain: str | None = None, claim: str | None = None) -> dict[str, str]:
    return {
        "evidence_id": f"ev_{number}",
        "claim": claim or f"Afirmación {number}",
        "publisher_domain": domain or f"medio{number}.example",
        "model_stance": stance,
    }


def test_evidence_id_is_stable_and_sensitive_to_the_pair():
    first = evidence_id(4, "https://medio.example/a", "Una afirmación")
    assert first == evidence_id(4, "https://medio.example/a", "Una afirmación")
    assert first != evidence_id(4, "https://medio.example/b", "Una afirmación")


def test_balanced_selection_targets_each_model_stratum():
    rows = [row(index * 10 + offset, stance) for index, stance in enumerate(
        ("supports", "refutes", "discusses", "unrelated")
    ) for offset in range(3)]

    selected = select_balanced(rows, sample_size=8, seed=7)
    counts = {stance: sum(item["model_stance"] == stance for item in selected) for stance in (
        "supports", "refutes", "discusses", "unrelated"
    )}

    assert counts == {"supports": 2, "refutes": 2, "discusses": 2, "unrelated": 2}


def test_selection_deduplicates_same_claim_and_publisher_domain():
    rows = [
        row(1, "supports", domain="medio.example", claim="Misma afirmación"),
        row(2, "supports", domain="medio.example", claim="Misma afirmación"),
    ]

    assert len(select_balanced(rows, sample_size=4, seed=7)) == 1


def test_bootstrap_interval_is_deterministic_and_bounded():
    truth = ["supports", "refutes", "discusses", "unrelated"] * 2
    result = bootstrap_macro_f1(truth, truth, seed=10, repetitions=50)

    assert result == {"low": 0.75, "high": 1.0}


def test_v4_blind_sample_uses_frozen_risk_quotas_and_fresh_source_minimum():
    candidates = []
    number = 0
    for source, band, count in (
        ("RPP Noticias", "low", 3),
        ("El Comercio", "low", 8),
        ("El Comercio", "medium", 10),
        ("El Comercio", "high", 5),
    ):
        for _ in range(count):
            number += 1
            candidates.append({
                "prediction_id": number,
                "original_source": source,
                "risk_band": band,
                "group_key": f"cluster:{number}",
            })

    selected = stratified_v4_blind_sample(candidates, seed=20261025)

    assert len(selected) == 20
    assert Counter(row["risk_band"] for row in selected) == {
        "low": 8,
        "medium": 8,
        "high": 4,
    }
    assert sum(row["original_source"] == "RPP Noticias" for row in selected) == 3
    assert len({row["group_key"] for row in selected}) == 20
    assert [row["case_id"] for row in selected] == [
        f"V4-{index:03d}" for index in range(1, 21)
    ]
