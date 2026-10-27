from app.evidence_assessment import build_evidence_assessment, normalize_evidence_source


def source(url: str, stance: str) -> dict:
    return normalize_evidence_source(
        {
            "url": url,
            "source": "Medio",
            "title": "Cobertura",
            "excerpt": "Fragmento citado.",
            "evidenceStance": stance,
        }
    )


def test_two_distinct_publisher_domains_are_required_for_supported_status():
    limited = build_evidence_assessment([source("https://a.example/1", "supports")])
    supported = build_evidence_assessment([
        source("https://a.example/1", "supports"),
        source("https://b.example/2", "supports"),
    ])

    assert limited["status"] == "insufficient_evidence"
    assert supported["status"] == "supported"
    assert supported["supportingSources"] == 2


def test_repeated_urls_from_one_outlet_do_not_count_as_distinct_corroboration():
    result = build_evidence_assessment([
        source("https://medio.example/uno", "supports"),
        source("https://www.medio.example/dos", "supports"),
    ])

    assert result["status"] == "insufficient_evidence"
    assert result["supportingSources"] == 1
    assert result["distinctPublisherSources"] == 1
    assert result["independenceStatus"] == "publisher_domain_only"


def test_support_and_refutation_produce_mixed_evidence():
    result = build_evidence_assessment([
        source("https://a.example/1", "supports"),
        source("https://b.example/2", "refutes"),
    ])

    assert result["status"] == "mixed"
    assert result["supportingSources"] == 1
    assert result["refutingSources"] == 1


def test_context_only_never_increases_claim_support():
    result = build_evidence_assessment([
        source("https://a.example/1", "discusses"),
        source("https://b.example/2", "discusses"),
    ])

    assert result["status"] == "insufficient_evidence"
    assert result["contextualSources"] == 2


def test_primary_context_is_visible_but_never_counts_as_independent_support():
    primary = normalize_evidence_source({
        "url": "https://rpp.pe/politica/declaracion-original",
        "source": "RPP",
        "title": "Declaración original",
        "excerpt": "La publicación reproduce la declaración investigada.",
        "evidenceStance": "supports",
        "assessmentMethod": "original_publication_context",
    })

    result = build_evidence_assessment([primary])

    assert primary["sourceRole"] == "primary_context"
    assert primary["independenceEligible"] is False
    assert result["status"] == "insufficient_evidence"
    assert result["supportingSources"] == 0
    assert result["distinctPublisherSources"] == 0
    assert result["primaryContextSources"] == 1
    assert result["totalSourceRecords"] == 1
