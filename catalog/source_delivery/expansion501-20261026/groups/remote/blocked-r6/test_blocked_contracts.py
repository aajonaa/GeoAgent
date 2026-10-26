"""Synthetic preflight tests; scientific kernels are a separate, unexecuted suite."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[6]
SUPPORT = ROOT / "geological_agent/geology/expansion501_remote/blocked_support.py"
spec = importlib.util.spec_from_file_location("expansion501_remote_blocked_support", SUPPORT)
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def acquisition(day, sensor):
    start = datetime(2019, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=day)
    end = start + timedelta(seconds=30)
    return {
        "product_id": sensor + "_IW_SLC__1SDV_" + start.strftime("%Y%m%dT%H%M%S") +
                      "_" + end.strftime("%Y%m%dT%H%M%S") + "_000001_000001_0001.SAFE",
        "sensor": sensor, "start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stop_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "polarization": "VV",
        "manifest_sha256": "1" * 64, "coregistration_reference": "SYNTHETIC_REFERENCE",
    }


def acquisitions():
    return [acquisition(i * 6, "S1B" if i % 2 == 0 else "S1A") for i in range(6)]


def grid():
    return {"crs": "EPSG:32650", "affine": [10, 0, 500000, 0, -10, 3400000],
            "shape": [1, 2], "mask": [[True, False]], "nodata": None}


def weather():
    return [{"file": {"path": "weather/synthetic.grib", "bytes": 32, "sha256": "2" * 64,
                      "role": "grib"},
             "valid_utc": "2019-01-01T12:00:00Z", "bounds": [99, 19, 102, 22],
             "pressure_levels_hpa": [100, 500, 1000],
             "variables": ["geopotential", "specific_humidity", "temperature"],
             "units": {"geopotential": "m2/s2", "specific_humidity": "kg/kg",
                       "temperature": "K", "pressure": "hPa"},
             "provider": "ECMWF_ERA5", "data_license_url": "https://example.invalid/SYNTHETIC"}]


class ContractTests(unittest.TestCase):
    """These are metadata/path/units checks, NOT scientific numerical acceptance."""

    def setUp(self):
        scratch = ROOT / "assets/expansion501-remote/local-contract-r6"
        scratch.mkdir(parents=True, exist_ok=True)
        if not scratch.resolve().is_relative_to(ROOT.resolve()) or scratch.is_symlink():
            raise RuntimeError("Synthetic test scratch must remain within own workspace.")
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def safe_files(self):
        safe = acquisition(0, "S1A")["product_id"]
        payloads = {
            safe + "/measurement/synthetic.tiff": (b"SYNTHETIC_NOT_A_REAL_TIFF", "measurement"),
            safe + "/annotation/synthetic.xml": (b"<synthetic/>", "annotation"),
            safe + "/annotation/calibration/calibration-synthetic.xml": (b"<synthetic/>", "calibration"),
            safe + "/support.txt": (b"SYNTHETIC_REFERENCE_ONLY", "support"),
        }
        xml = "<xfdu>" + "".join('<fileLocation href="./' + name[len(safe) + 1:] + '"/>'
                                 for name in payloads) + "</xfdu>"
        payloads[safe + "/manifest.safe"] = (xml.encode("utf-8"), "manifest")
        result = []
        for name, (body, role) in payloads.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            result.append({"path": name, "bytes": len(body),
                           "sha256": hashlib.sha256(body).hexdigest(), "role": role})
        return result

    def reject(self, function, *args, **kwargs):
        with self.assertRaises(support.ContractViolation):
            function(*args, **kwargs)

    def test_finite_positive(self):
        self.assertEqual(support.number(0.2, 0, 1), 0.2)

    def test_nan(self):
        self.reject(support.number, float("nan"), 0, 1)

    def test_infinity(self):
        self.reject(support.number, float("inf"), 0, 1)

    def test_bool_is_not_number(self):
        self.reject(support.number, True, 0, 1)

    def test_utc_positive(self):
        self.assertEqual(support.utc("2019-01-01T12:00:00Z").hour, 12)

    def test_utc_offset_not_silently_converted(self):
        self.reject(support.utc, "2019-01-01T12:00:00+08:00")

    def test_utc_invalid_calendar(self):
        self.reject(support.utc, "2019-02-30T12:00:00Z")

    def test_tide_reviewed_interval(self):
        self.assertEqual(support.tide_time("2017-01-01T00:00:00Z").year, 2017)

    def test_tide_2026_rejected(self):
        self.reject(support.tide_time, "2026-10-26T00:00:00Z")

    def test_tide_expiry_rejected(self):
        self.reject(support.tide_time, "2025-12-28T00:00:00Z")

    def test_acquisitions_positive(self):
        dates, sensors = support.acquisitions(acquisitions())
        self.assertEqual(len(dates), 6)
        self.assertEqual(sensors.count("S1B"), 3)

    def test_acquisition_duplicate(self):
        items = acquisitions()
        items[1] = copy.deepcopy(items[0])
        self.reject(support.acquisitions, items)

    def test_acquisition_unsorted(self):
        self.reject(support.acquisitions, list(reversed(acquisitions())))

    def test_acquisition_sensor_mismatch(self):
        items = acquisitions()
        items[0]["sensor"] = "S1A"
        self.reject(support.acquisitions, items)

    def test_acquisition_polarization_mismatch(self):
        items = acquisitions()
        items[0]["polarization"] = "HH"
        self.reject(support.acquisitions, items)

    def test_acquisition_coregistration_mismatch(self):
        items = acquisitions()
        items[0]["coregistration_reference"] = "OTHER"
        self.reject(support.acquisitions, items)

    def test_acquisition_rgb_is_not_sar(self):
        items = acquisitions()
        items[0]["product_id"] = "Sentinel-2-RGB.tif"
        self.reject(support.acquisitions, items)

    def test_grid_positive(self):
        self.assertEqual(support.grid(grid()), [True, False])

    def test_grid_singular(self):
        item = grid()
        item["affine"] = [0, 0, 0, 0, 0, 0]
        self.reject(support.grid, item)

    def test_grid_no_crs(self):
        item = grid()
        del item["crs"]
        self.reject(support.grid, item)

    def test_grid_mask_must_be_boolean(self):
        item = grid()
        item["mask"] = [[1, 0]]
        self.reject(support.grid, item)

    def test_grid_empty_mask(self):
        item = grid()
        item["mask"] = [[False, False]]
        self.reject(support.grid, item)

    def test_grid_unknown_key(self):
        item = grid()
        item["module"] = "os"
        self.reject(support.grid, item)

    def test_grid_nodata_not_imputed(self):
        item = grid()
        item["nodata"] = 0
        self.reject(support.grid, item)

    def test_relative_path_positive(self):
        self.assertEqual(str(support.relative_path("scene/manifest.safe")), "scene/manifest.safe")

    def test_traversal(self):
        self.reject(support.relative_path, "../outside")

    def test_absolute_path(self):
        self.reject(support.relative_path, "/outside")

    def test_windows_drive(self):
        self.reject(support.relative_path, "C:/outside")

    def test_percent_encoded_traversal(self):
        self.reject(support.relative_path, "scene/%2e%2e/outside")

    def test_xml_entities(self):
        self.reject(support.xml_document, b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///x">]><x/>')

    def test_xml_utf16(self):
        self.reject(support.xml_document, "<x/>".encode("utf-16"))

    def test_xml_malformed(self):
        self.reject(support.xml_document, b"<x>")

    def test_safe_hash_reference_preflight(self):
        result = support.validate_safe_inventory(self.safe_files(), self.root, thermal_noise=False)
        self.assertEqual(result["file_count"], 5)
        self.assertEqual(result["sensor_metadata_content_acceptance"], "pending")

    def test_safe_hash_mismatch(self):
        records = self.safe_files()
        records[0]["sha256"] = "0" * 64
        self.reject(support.validate_safe_inventory, records, self.root, thermal_noise=False)

    def test_safe_missing_noise(self):
        self.reject(support.validate_safe_inventory, self.safe_files(), self.root, thermal_noise=True)

    def test_safe_reference_omission(self):
        records = self.safe_files()
        records.remove(next(x for x in records if x["role"] == "support"))
        # Still five entries so exercise exact-reference enforcement, not only min count.
        extra = self.root / (acquisition(0, "S1A")["product_id"] + "/extra.txt")
        extra.write_bytes(b"x")
        records.append({"path": str(extra.relative_to(self.root)).replace("\\", "/"),
                        "bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest(), "role": "support"})
        self.reject(support.validate_safe_inventory, records, self.root, thermal_noise=False)

    def test_weather_descriptor_positive(self):
        result = support.weather_inventory(weather(), ["2019-01-01T12:00:00Z"], [100, 20, 101, 21])
        self.assertEqual(result["slices"], 1)
        self.assertEqual(result["grib_content_and_vertical_dem_coverage"], "pending")

    def test_weather_time_mismatch(self):
        self.reject(support.weather_inventory, weather(), ["2019-01-01T12:01:00Z"], [100, 20, 101, 21])

    def test_weather_wrong_units(self):
        records = weather()
        records[0]["units"]["temperature"] = "degC"
        self.reject(support.weather_inventory, records, ["2019-01-01T12:00:00Z"], [100, 20, 101, 21])

    def test_weather_insufficient_coverage(self):
        self.reject(support.weather_inventory, weather(), ["2019-01-01T12:00:00Z"], [98, 20, 101, 21])

    def canopy(self):
        path = ROOT / "assets/expansion501-remote/blocked-r6-synthetic.json"
        return json.loads(path.read_text(encoding="utf-8"))["canopy_zero_lai"]["args"]

    def test_canopy_positive_contract(self):
        self.assertEqual(len(support.canopy_arguments(self.canopy())["soil_reflectance"]), 2101)

    def test_canopy_negative_soil(self):
        args = self.canopy()
        args["soil_reflectance"][0] = -0.1
        self.reject(support.canopy_arguments, args)

    def test_canopy_wrong_spectrum_length(self):
        args = self.canopy()
        args["soil_reflectance"].pop()
        self.reject(support.canopy_arguments, args)

    def test_canopy_wrong_units(self):
        args = self.canopy()
        args["units"]["angle"] = "rad"
        self.reject(support.canopy_arguments, args)

    def test_canopy_arbitrary_callable_rejected(self):
        args = self.canopy()
        args["function"] = "anything"
        self.reject(support.canopy_arguments, args)


class ScientificOracleTests(unittest.TestCase):
    """Authored only. The Flow runner deliberately does not load this suite."""

    def test_zero_lai_returns_supplied_soil(self):
        path = ROOT / "assets/expansion501-remote/blocked-r6-synthetic.json"
        args = json.loads(path.read_text(encoding="utf-8"))["canopy_zero_lai"]["args"]
        result = support.pending_canopy_kernel(args)
        self.assertEqual(result["wavelength_nm"], list(range(400, 2501)))
        for value in result["directional_reflectance_factor"]:
            self.assertAlmostEqual(value, 0.2, delta=1e-10)

    def test_s1b_plus_tenth_metre_offset(self):
        args = {"acquisitions": acquisitions(), "grid": grid(),
                "range_offsets": [[0.02 + i * 6 * 0.001 + (0.1 if i % 2 == 0 else 0), None]
                                  for i in range(6)],
                "units": {"range_offsets": "m"},
                "representation": "coregistered_range_offset_timeseries"}
        scratch = ROOT / "assets/expansion501-remote/local-contract-r6"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="scientific-SYNTHETIC-", dir=scratch) as directory:
            result = support.pending_s1ab_bias_kernel(args, str(Path(directory).resolve()))
        self.assertAlmostEqual(result["bias_m"][0], 0.1, delta=1e-6)
        self.assertIsNone(result["bias_m"][1])


if __name__ == "__main__":
    raise SystemExit("Run run_local_flow.py for the authorized contract-only scope; scientific suite is not run.")
