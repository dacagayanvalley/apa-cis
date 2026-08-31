"""
List available Project NOAH source ZIPs for Region 2 from the BetterGov mirror.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "reference" / "noah_region2_source_files.json"

TARGET_PROVINCES = {
    "Batanes",
    "Cagayan",
    "Isabela",
    "NuevaVizcaya",
    "Quirino",
}

NOAH_DIRS = [
    "Flood/5yr",
    "Flood/25yr",
    "Flood/100yr",
    "Landslide/LandslideHazards",
    "Landslide/DebrisFlowAlluvialFan",
    "Storm Surge/StormSurgeAdvisory1",
    "Storm Surge/StormSurgeAdvisory2",
    "Storm Surge/StormSurgeAdvisory3",
    "Storm Surge/StormSurgeAdvisory4",
]


def _tree_url(path: str) -> str:
    encoded = urllib.parse.quote(path, safe="/")
    return f"https://huggingface.co/api/datasets/bettergovph/project-noah-hazard-maps/tree/main/{encoded}?recursive=True"


def main() -> int:
    results = []
    for folder in NOAH_DIRS:
        response = requests.get(_tree_url(folder), timeout=60)
        response.raise_for_status()
        entries = response.json()
        matches = []
        for entry in entries:
            path = entry.get("path", "")
            compact_path = path.replace(" ", "")
            if entry.get("type") != "file" or not path.lower().endswith(".zip"):
                continue
            if any(province.lower() in compact_path.lower() for province in TARGET_PROVINCES):
                matches.append(
                    {
                        "path": path,
                        "size": entry.get("size"),
                        "download_url": "https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps/resolve/main/"
                        + urllib.parse.quote(path, safe="/"),
                    }
                )
        results.append({"folder": folder, "files": matches})

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "source": "https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps",
                "target_provinces": sorted(TARGET_PROVINCES),
                "folders": results,
            },
            handle,
            indent=2,
        )
        handle.write("\n")

    for result in results:
        print(result["folder"])
        for item in result["files"]:
            print(f"  {item['path']} ({item['size']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
