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

LIAR_BASE_URL = "https://raw.githubusercontent.com/tfs4/liar_dataset/master/"
LIAR_FILES = {
    "train.tsv": "train.tsv",
    "valid.tsv": "validation.tsv",
    "test.tsv": "test.tsv",
}


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
    """Download LIAR TSV files from a public GitHub mirror."""
    os.makedirs(output_dir, exist_ok=True)

    for remote_name, local_name in LIAR_FILES.items():
        dest = os.path.join(output_dir, local_name)
        if os.path.exists(dest):
            print(f"  [skip] {local_name} already exists")
            continue
        print(f"  Downloading {remote_name} as {local_name}...")
        urllib.request.urlretrieve(LIAR_BASE_URL + remote_name, dest)

    print("LIAR ready.\n")


if __name__ == "__main__":
    print("=== FNC-1 (Stance Detection) ===")
    download_fnc()
    print("=== LIAR (Fake News Detection) ===")
    download_liar()
    print("All datasets downloaded.")
