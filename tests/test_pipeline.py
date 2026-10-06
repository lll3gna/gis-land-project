from pathlib import Path

import json

import numpy as np
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
    assert crs == "EPSG:6933"
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
