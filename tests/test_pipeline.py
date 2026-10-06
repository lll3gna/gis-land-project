from pathlib import Path

import json

import numpy as np
import pytest
import rasterio

from cadastre.read_cadastre import read_cadastre
from imagery.process_imagery import process_geotiff, percentile_normalize


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CADASTRE = ROOT / "data" / "samples" / "vok104_boundary.geojson"
SAMPLE_IMAGERY = ROOT / "data" / "samples" / "vok104_imagery.tif"


def test_cadastre_contract_and_area():
    data = read_cadastre(SAMPLE_CADASTRE)
    assert data["schema_version"] == "1.0"
    assert data["cadastral_number"] == "50:11:0000000:104"
    assert data["area_m2"] == 10000.0
    assert data["geometry"]["type"] == "Polygon"
    assert data["crs"] == "EPSG:4326"
    assert data["area_relative_error"] <= 0.05


def test_geotiff_keeps_spatial_contract():
    rgb, valid, transform, crs, manifest = process_geotiff(SAMPLE_IMAGERY)
    assert rgb.shape[0] == 3
    assert rgb.dtype == np.uint8
    assert valid.any()
    assert crs == "EPSG:32637"
    assert transform.a > 0
    assert transform.e < 0
    assert manifest["bands"] == [1, 2, 3]

    with rasterio.open(SAMPLE_IMAGERY) as src:
        assert src.crs is not None
        assert src.transform.a > 0


def test_percentile_normalization_ignores_extreme_outlier():
    values = np.ones((100, 100), dtype=np.float32) * 100
    values[0, 0] = 100000
    valid = np.ones_like(values, dtype=bool)
    normalized = percentile_normalize(values, valid)
    assert normalized[50, 50] > 0
    assert normalized[0, 0] == 255


def test_save_outputs_writes_segmentation_contract(tmp_path, monkeypatch):
    import imagery.process_imagery as imagery

    rgb = np.zeros((3, 8, 10), dtype=np.uint8)
    rgb[:, 2:6, 3:8] = 120
    valid = np.zeros((8, 10), dtype=bool)
    valid[2:6, 3:8] = True

    monkeypatch.setattr(imagery, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(imagery, "OUTPUT_PNG", tmp_path / "2026-10-06_vok104_cadastre.png")
    monkeypatch.setattr(imagery, "OUTPUT_TIFF", tmp_path / "2026-10-06_vok104_cadastre.tif")
    monkeypatch.setattr(imagery, "OUTPUT_MASK", tmp_path / "2026-10-06_vok104_cadastre_nodata_mask.png")
    monkeypatch.setattr(imagery, "OUTPUT_MANIFEST", tmp_path / "2026-10-06_vok104_cadastre.json")

    transform = imagery.Affine(2, 0, 100, 0, -2, 200)
    imagery.save_outputs(rgb, valid, transform, "EPSG:32637", {
        "source_crs": "EPSG:32637",
        "working_crs": "EPSG:32637",
        "exchange_crs": "EPSG:4326",
        "bands": [1, 2, 3],
        "normalization": {"method": "percentile_clip", "low": 2, "high": 98},
    })

    assert (tmp_path / "2026-10-06_vok104_cadastre.png").is_file()
    assert (tmp_path / "2026-10-06_vok104_cadastre.tif").is_file()
    assert (tmp_path / "2026-10-06_vok104_cadastre.pgw").is_file()
    assert (tmp_path / "2026-10-06_vok104_cadastre_nodata_mask.png").is_file()

    manifest = json.loads((tmp_path / "2026-10-06_vok104_cadastre.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0"
    assert manifest["georeferenced"] is True
    assert manifest["crs"] == "EPSG:32637"
    assert manifest["geotiff"] == "2026-10-06_vok104_cadastre.tif"
    assert manifest["nodata_mask"] == "2026-10-06_vok104_cadastre_nodata_mask.png"

    with rasterio.open(tmp_path / "2026-10-06_vok104_cadastre.tif") as src:
        assert src.count == 3
        assert src.dtypes == ("uint8", "uint8", "uint8")
        assert src.nodata == 0
        assert src.crs.to_string() == "EPSG:32637"
        assert src.transform == transform

    
def test_percentile_normalization_flat_band_is_grey_not_black():
    values = np.full((50, 50), 7.0, dtype=np.float32)
    valid = np.ones_like(values, dtype=bool)
    normalized = percentile_normalize(values, valid)
    assert (normalized == 128).all()


def test_percentile_normalization_regular_band_uses_full_range():
    values = np.tile(np.arange(100, dtype=np.float32), (10, 1))
    valid = np.ones_like(values, dtype=bool)
    normalized = percentile_normalize(values, valid)
    assert normalized.min() == 0
    assert normalized.max() == 255


def test_working_crs_keeps_image_shape():
    rgb, valid, transform, crs, manifest = process_geotiff(SAMPLE_IMAGERY)
    with rasterio.open(SAMPLE_IMAGERY) as src:
        assert rgb.shape[1:] == (src.height, src.width)
    assert abs(transform.a) == pytest.approx(abs(transform.e))
