from __future__ import annotations

from urllib.parse import urlparse


ASSESSMENT_VERSION = "evidence-policy-2026-10-25-v5"
ALLOWED_STANCES = {"supports", "refutes", "discusses", "unrelated"}
PRIMARY_CONTEXT_METHOD = "original_publication_context"


def independence_key(url: str | None) -> str:
    domain = urlparse(str(url or "")).netloc.casefold().removeprefix("www.")
    return domain


def normalize_evidence_source(source: dict, *, default_claim: str = "") -> dict:
    normalized = dict(source)
    stance = str(
        normalized.get("evidenceStance")
        or normalized.get("evidence_stance")
        or "discusses"
    ).strip()
    if stance not in ALLOWED_STANCES:
        stance = "discusses"

    normalized["evidenceStance"] = stance
    normalized["claim"] = str(normalized.get("claim") or default_claim or "").strip() or None
    normalized["independenceKey"] = str(
        normalized.get("independenceKey")
        or normalized.get("independence_key")
        or independence_key(normalized.get("url"))
    ).strip() or None
    normalized["assessmentMethod"] = str(
        normalized.get("assessmentMethod")
        or normalized.get("assessment_method")
        or "legacy_related_source"
    )
    normalized["assessmentVersion"] = str(
        normalized.get("assessmentVersion")
        or normalized.get("assessment_version")
        or ASSESSMENT_VERSION
    )
    is_primary_context = normalized["assessmentMethod"] == PRIMARY_CONTEXT_METHOD
    normalized["sourceRole"] = "primary_context" if is_primary_context else "independent_evidence"
    normalized["independenceEligible"] = not is_primary_context

    relevance = normalized.get("relevanceScore", normalized.get("relevance_score"))
    normalized["relevanceScore"] = (
        round(min(max(float(relevance), 0.0), 1.0), 4)
        if relevance is not None
        else None
    )
    return normalized


def build_evidence_assessment(sources: list[dict] | None) -> dict:
    unique: dict[str, dict] = {}
    primary_context_sources = 0
    total_source_records = 0
    for raw_source in sources or []:
        source = normalize_evidence_source(raw_source)
        total_source_records += 1
        if not source["independenceEligible"]:
            primary_context_sources += 1
            continue
        key = source.get("independenceKey") or independence_key(source.get("url"))
        if not key or key in unique:
            continue
        unique[key] = source

    counts = {stance: 0 for stance in ALLOWED_STANCES}
    for source in unique.values():
        counts[source["evidenceStance"]] += 1

    supports = counts["supports"]
    refutes = counts["refutes"]
    if supports and refutes:
        status = "mixed"
    elif supports >= 2:
        status = "supported"
    elif refutes >= 2:
        status = "disputed"
    else:
        status = "insufficient_evidence"

    return {
        "status": status,
        "supportingSources": supports,
        "refutingSources": refutes,
        "contextualSources": counts["discusses"],
        "unrelatedSources": counts["unrelated"],
        "primaryContextSources": primary_context_sources,
        "totalSourceRecords": total_source_records,
        "distinctPublisherSources": len(unique),
        "minimumDistinctPublisherAgreement": 2,
        "independenceStatus": "publisher_domain_only",
        "assessmentVersion": ASSESSMENT_VERSION,
    }
