"""
Download and prepare FNC-1 and LIAR datasets.

Usage:
    python scripts/download_data.py
"""

import os
import urllib.request


FNC_BASE_URL = "https://raw.githubusercontent.com/FakeNewsChallenge/fnc-1/master/"
FNC_FILES = [
    "train_bodies.csv",
    "train_stances.csv",
    "competition_test_bodies.csv",
    "competition_test_stances.csv",
]


def download_fnc(output_dir="data/fnc-1"):
    """Download FNC-1 CSV files from GitHub."""
    os.makedirs(output_dir, exist_ok=True)
    for fname in FNC_FILES:
        dest = os.path.join(output_dir, fname)
        if os.path.exists(dest):
            print(f"  [skip] {fname} already exists")
            continue
        print(f"  Downloading {fname}...")
        urllib.request.urlretrieve(FNC_BASE_URL + fname, dest)
    print("FNC-1 ready.\n")


def download_liar(output_dir="data/liar"):
    """Download LIAR dataset via HuggingFace datasets library."""
    os.makedirs(output_dir, exist_ok=True)

    try:
        from datasets import load_dataset
    except ImportError:
        print("Install the datasets library first:  pip install datasets")
        raise

    ds = load_dataset("ucsbnlp/liar", trust_remote_code=True)
    label_names = ds["train"].features["label"].names

    splits = {"train": "train", "validation": "validation", "test": "test"}
    for split_name, split_key in splits.items():
        dest = os.path.join(output_dir, f"{split_name}.tsv")
        if os.path.exists(dest):
            print(f"  [skip] {split_name}.tsv already exists")
            continue
        print(f"  Saving {split_name}.tsv ({len(ds[split_key]):,} rows)...")
        with open(dest, "w", encoding="utf-8") as f:
            for row in ds[split_key]:
                label = label_names[row["label"]]
                stmt = row["statement"].replace("\t", " ").replace("\n", " ")
                row_id = row.get("id", "")
                f.write(f"{row_id}\t{label}\t{stmt}\n")

    print("LIAR ready.\n")


if __name__ == "__main__":
    print("=== FNC-1 (Stance Detection) ===")
    download_fnc()
    print("=== LIAR (Fake News Detection) ===")
    download_liar()
    print("All datasets downloaded.")
