#!/usr/bin/env python3
"""Stage only an approved public catalog for the optional AWS Lambda function."""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", type=Path, default=ROOT / "public/data/movies.json")
    ap.add_argument("--allow-demo", action="store_true")
    args = ap.parse_args()
    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    if data.get("kind") != "public" and not (args.allow_demo and data.get("kind") == "demo"):
        ap.error("A rights-reviewed public catalog is required (or --allow-demo for tests).")
    if not isinstance(data.get("movies"), list):
        ap.error("Invalid catalog")
    for movie in data["movies"]:
        rights = movie.get("rights") or {}
        if rights.get("distribution") != "cleared" or not rights.get("evidence"):
            ap.error("Unapproved movie record; refusing Lambda package")
    dest = ROOT / "backend/data"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.catalog, dest / "movies.json")
    print("Staged", len(data["movies"]), "records in ignored backend/data/movies.json")

if __name__ == "__main__":
    main()
