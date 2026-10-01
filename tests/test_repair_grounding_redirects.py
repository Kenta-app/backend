from scripts.repair_grounding_redirects import resolve_publisher_url


class FakeService:
    def __init__(self, target):
        self.target = target

    def _resolve_grounding_url(self, _redirect):
        return self.target

    def _source_name_from_url(self, target):
        return "Gestión" if target.startswith("https://gestion.pe/") else "unknown"

    def _is_allowed_source(self, source):
        return source["url"].startswith("https://gestion.pe/")


def test_resolves_matching_publisher_url():
    target = "https://gestion.pe/peru/politica/noticia/"
    assert resolve_publisher_url(FakeService(target), "https://vertexaisearch.cloud.google.com/grounding-api-redirect/x", "Gestión") == (target, "ok")


def test_rejects_unresolved_and_unexpected_publisher():
    assert resolve_publisher_url(FakeService(None), "redirect", "Gestión") == (None, "redirect_not_resolved")
    assert resolve_publisher_url(FakeService("https://gestion.pe/peru/politica/noticia/"), "redirect", "El Comercio") == (None, "publisher_mismatch")


def test_rejects_non_https_and_url_credentials():
    assert resolve_publisher_url(FakeService("http://gestion.pe/peru/noticia/"), "redirect", "Gestión") == (None, "unsafe_destination")
    assert resolve_publisher_url(FakeService("https://name:pass@gestion.pe/peru/noticia/"), "redirect", "Gestión") == (None, "unsafe_destination")
