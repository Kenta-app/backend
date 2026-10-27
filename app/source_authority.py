from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from app.raw.models import Source


@dataclass(frozen=True)
class SourceAuthorityPolicy:
    authority_type: str
    label: str
    scope: str
    reason: str
    policy_version: str
    public_risk_policy: str

    def as_payload(self) -> dict[str, str]:
        return asdict(self)


EL_PERUANO_POLICY = SourceAuthorityPolicy(
    authority_type="official_state_publisher",
    label="Fuente oficial del Estado peruano",
    scope="Publicaciones institucionales, normas y comunicaciones del Estado",
    reason=(
        "El Peruano es el Diario Oficial. Esta identificación acredita la "
        "procedencia institucional, no la veracidad automática de cada afirmación."
    ),
    policy_version="official-sources-2026-10-20-v1",
    public_risk_policy="withhold_pending_source_audit",
)

OFFICIAL_SOURCE_NAMES = ("el peruano",)
OFFICIAL_SOURCE_DOMAINS = ("elperuano.pe", "diariooficial.elperuano.pe")


def source_authority_policy(
    source: Source | None = None,
    *,
    source_name: str | None = None,
    source_url: str | None = None,
) -> SourceAuthorityPolicy | None:
    name = (source_name or (source.name if source is not None else "") or "").strip().casefold()
    candidate_url = source_url or (source.base_url if source is not None else "") or ""
    domain = urlparse(candidate_url).netloc.casefold().removeprefix("www.")

    if name in OFFICIAL_SOURCE_NAMES:
        return EL_PERUANO_POLICY
    if any(domain == allowed or domain.endswith(f".{allowed}") for allowed in OFFICIAL_SOURCE_DOMAINS):
        return EL_PERUANO_POLICY
    return None


def withholds_public_risk(source: Source | None) -> bool:
    policy = source_authority_policy(source)
    return bool(policy and policy.public_risk_policy == "withhold_pending_source_audit")
