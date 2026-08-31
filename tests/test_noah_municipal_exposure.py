import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.compute_noah_municipal_exposure as noah


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _square(x1, y1, x2, y2):
    return {
        "type": "Polygon",
        "coordinates": [[
            [x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]
        ]],
    }


def _catalog():
    return {
        "hazards": [{
            "family": "flood",
            "label": "Flood Hazard",
            "attribute": "Var",
            "scenarios": [{
                "id": "flood_100yr",
                "label": "100-year rain return period",
                "pmtiles_layer": "flood_100yr",
            }],
        }]
    }


def _minimal_sources():
    return {
        "folders": [{
            "folder": "Flood/100yr",
            "files": [{
                "path": "Flood/100yr/Cagayan.zip",
                "size": 100,
                "download_url": "https://example.test/Cagayan.zip",
            }],
        }]
    }


def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(noah, "MUNICIPALITIES_PATH", tmp_path / "config" / "municipalities.json")
    monkeypatch.setattr(noah, "MUNICIPAL_BOUNDARIES_PATH", tmp_path / "data" / "boundaries" / "municipalities_simplified.geojson")
    monkeypatch.setattr(noah, "NOAH_DIR", tmp_path / "data" / "geospatial" / "noah")
    monkeypatch.setattr(noah, "RAW_NOAH_DOWNLOADS", tmp_path / "data" / "raw" / "noah" / "downloads")
    monkeypatch.setattr(noah, "CATALOG_PATH", tmp_path / "data" / "reference" / "noah_hazard_overlays.json")
    monkeypatch.setattr(noah, "SOURCE_INDEX_PATH", tmp_path / "data" / "reference" / "noah_region2_source_files.json")


def _write_common_inputs(tmp_path):
    _write(tmp_path / "config" / "municipalities.json", [
        {"psgc": "023101000", "name": "City of Tuguegarao", "province": "Cagayan"}
    ])
    _write(tmp_path / "data" / "boundaries" / "municipalities_simplified.geojson", {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "municipality": "Tuguegarao",
                "province": "Cagayan",
                "AREA_SQKM": 100,
            },
            "geometry": _square(0, 0, 10, 10),
        }],
    })
    _write(tmp_path / "data" / "reference" / "noah_hazard_overlays.json", _catalog())
    _write(tmp_path / "data" / "reference" / "noah_region2_source_files.json", _minimal_sources())


def test_source_readiness_without_local_geometry(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    _write_common_inputs(tmp_path)
    monkeypatch.setattr(noah, "_load_shapely", lambda: (None, None))

    output_path = tmp_path / "out" / "municipal_hazard_exposure.json"
    assert noah.main(["--output", str(output_path)]) == 0

    data = json.loads(output_path.read_text(encoding="utf-8"))
    record = data["data"]["023101000"]
    assert data["meta"]["status"] == "pending_local_geometry"
    assert record["geometry_status"] == "matched"
    assert record["scenarios"]["flood_100yr"]["source_available_for_province"] is True
    assert record["summary"]["risk_score"] is None


@pytest.mark.skipif(noah._load_shapely()[0] is None, reason="Shapely is not installed")
def test_exact_exposure_intersection(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    _write_common_inputs(tmp_path)
    _write(tmp_path / "data" / "geospatial" / "noah" / "flood_100yr_r2.geojson", {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"hazard_level": 3, "Var": 3},
            "geometry": _square(0, 0, 5, 10),
        }],
    })

    output_path = tmp_path / "out" / "municipal_hazard_exposure.json"
    assert noah.main(["--output", str(output_path)]) == 0

    data = json.loads(output_path.read_text(encoding="utf-8"))
    scenario = data["data"]["023101000"]["scenarios"]["flood_100yr"]
    assert data["meta"]["status"] == "computed"
    assert scenario["hazard_area"]["high"]["pct"] == 50.0
    assert scenario["hazard_area"]["high"]["area_ha"] == 5000.0
