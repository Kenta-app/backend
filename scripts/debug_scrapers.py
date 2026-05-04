from __future__ import annotations

from dataclasses import dataclass

from app.scrapers.scrapers import ElComercioScraper, Peru21Scraper


@dataclass
class DebugResult:
    name: str
    ok: bool
    count: int
    sample_url: str | None
    sample_title: str | None
    sample_content_len: int
    error: str | None


def run_debug(name: str, scraper) -> DebugResult:
    try:
        items = scraper.scrape()
        if not items:
            return DebugResult(
                name=name,
                ok=False,
                count=0,
                sample_url=None,
                sample_title=None,
                sample_content_len=0,
                error="No se extrajeron articulos.",
            )

        sample = items[0]
        content = sample.get("content") or ""
        return DebugResult(
            name=name,
            ok=True,
            count=len(items),
            sample_url=sample.get("url"),
            sample_title=sample.get("title"),
            sample_content_len=len(str(content)),
            error=None,
        )
    except Exception as exc:
        return DebugResult(
            name=name,
            ok=False,
            count=0,
            sample_url=None,
            sample_title=None,
            sample_content_len=0,
            error=str(exc),
        )


def main() -> None:
    targets = [
        ("El Comercio", ElComercioScraper()),
        ("Peru21", Peru21Scraper()),
    ]

    print("=== Debug scrapers ===")
    for name, scraper in targets:
        result = run_debug(name, scraper)
        print(f"\n[{result.name}]")
        print(f"ok: {result.ok}")
        print(f"count: {result.count}")
        print(f"sample_url: {result.sample_url}")
        print(f"sample_title: {result.sample_title}")
        print(f"sample_content_len: {result.sample_content_len}")
        print(f"error: {result.error}")


if __name__ == "__main__":
    main()
