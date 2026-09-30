"""Fetch full article bodies for externally sourced stance-evaluation pairs."""
from __future__ import annotations

import argparse, csv, hashlib, json, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def extract(url: str) -> str:
    response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (academic evaluation)"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for selector in ("article p", "[itemprop='articleBody'] p", ".story-contents p", ".article-content p"):
        parts = [p.get_text(" ", strip=True) for p in soup.select(selector)]
        text = " ".join(part for part in parts if len(part) > 35)
        if len(text) >= 700:
            return text
    raise ValueError("No full article body extracted")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for path in args.inputs:
        rows.extend(csv.DictReader(path.open(encoding="utf-8", newline="")))
    exported, failures = [], []
    for row in rows:
        try:
            body = extract(row["source_url"])
            row["article"] = body
            row["article_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
            exported.append(row)
        except Exception as exc:
            failures.append({"pair_id": row["pair_id"], "url": row["source_url"], "error": str(exc)})
        time.sleep(0.5)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) + ["article", "article_sha256"]
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(exported)
    args.report.write_text(json.dumps({"requested":len(rows),"fetched":len(exported),"failures":failures},ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[OK] fetched {len(exported)}/{len(rows)} full articles")


if __name__ == "__main__": main()
