"""Authored CPU acceptance SOURCE ONLY. NOT RUN by the spatial contributor.

Every fixture is synthetic. Tests exercise real pinned upstream packages, not
substitute implementations. Catalog lookup is patched before integration; negative
GEOS-gate tests additionally patch version metadata, never scientific kernels.
Parent may run: python -m unittest discover -s tests_local -p test_github_expansion_spatial.py
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError

from geological_agent.geology import github_expansion_spatial as spatial
from geological_agent.geology import collection_contracts as contracts
from legacy.ToolsAgent.ToolsFuns import source_contracts
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

ROOT = Path(__file__).resolve().parents[1]
GROUP = ROOT / "catalog/source_delivery/github-expansion-20261025/groups/spatial"
FUNCTIONS = {
    "GeoSpatialRasterReproject": spatial.raster_reproject,
    "GeoSpatialPolygonRasterize": spatial.polygon_rasterize,
    "GeoSpatialRasterPolygonize": spatial.raster_polygonize,
    "GeoSpatialPolygonIntersection": spatial.polygon_intersection,
    "GeoSpatialCoverageUnion": spatial.coverage_union,
    "GeoSpatialConstrainedTriangulation": spatial.constrained_triangulation,
    "GeoSpatialDepressionFill": spatial.depression_fill,
    "GeoSpatialHeightAboveDrainage": spatial.height_above_drainage,
    "GeoSpatialDistanceToOutlet": spatial.distance_to_outlet,
    "GeoSpatialDistanceToRidge": spatial.distance_to_ridge,
    "GeoSpatialStrahlerOrder": spatial.strahler_order,
    "GeoSpatialTerrainContours": spatial.terrain_contours,
    "GeoSpatialLocalMoran": spatial.local_moran,
    "GeoSpatialBivariateLocalMoran": spatial.bivariate_local_moran,
    "GeoSpatialLocalGetisOrd": spatial.local_getis_ord,
    "GeoSpatialGlobalGeary": spatial.global_geary,
    "GeoSpatialBinaryJoinCounts": spatial.binary_join_counts,
    "GeoSpatialLocalGeary": spatial.local_geary,
    "GeoSpatialLeastCostPath": spatial.least_cost_path,
    "GeoSpatialCostAllocation": spatial.cost_allocation,
    "GeoSpatialEuclideanProximity": spatial.euclidean_proximity,
    "GeoSpatialResistanceDistance": spatial.resistance_distance,
    "GeoSpatialCostCorridor": spatial.cost_corridor,
    "GeoSpatialCapacityMaxFlow": spatial.capacity_max_flow,
    "GeoSpatialEllipsoidalPolygonArea": spatial.ellipsoidal_polygon_area,
    "GeoSpatialGeodesicTransect": spatial.geodesic_transect,
    "GeoSpatialProjectionDistortion": spatial.projection_distortion,
    "GeoSpatialMaximumInscribedCircle": spatial.maximum_inscribed_circle,
    "GeoSpatialSiteVoronoi": spatial.site_voronoi,
    "GeoSpatialSiteParcelSplit": spatial.site_parcel_split,
}


def shoelace(wkt):
    """Independent ring-area oracle for the simple synthetic polygon outputs."""
    coordinates = re.findall(r"([-+\d.eE]+)\s+([-+\d.eE]+)", wkt)
    xy = [(float(x), float(y)) for x, y in coordinates]
    return abs(sum(a[0]*b[1] - a[1]*b[0] for a, b in zip(xy, xy[1:]))) / 2


class SpatialSourceAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bundle = json.loads((GROUP / "catalog-additions.json").read_text(encoding="utf-8"))
        cls.bundle = bundle
        cls.specs = {t["id"]: t for t in bundle["tools"]}
        cls.fixtures = {name: json.loads((ROOT / spec["example_arguments"]["data_path"]).read_text(encoding="utf-8"))
                        for name, spec in cls.specs.items()}

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="spatial-source-acceptance-")))
        for module in (source_contracts, contracts, spatial):
            self.stack.enter_context(patch.object(module, "definition", side_effect=lambda name: self.specs[name]))

    def call(self, short, data=None, as_json=False):
        name = short if short.startswith("GeoSpatial") else "GeoSpatial" + short
        path = self.directory / (name + ".json")
        value = deepcopy(self.fixtures[name]) if data is None else data
        path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
        args = {"data_path": str(path)}
        return FUNCTIONS[name](json.dumps(args) if as_json else args)

    def supplemental(self, filename):
        return json.loads((ROOT / "assets/github-expansion-spatial" / filename).read_text(encoding="utf-8"))

    def numbers(self, observed, expected, tolerance=1e-9):
        self.assertEqual(len(observed), len(expected))
        for actual, target in zip(observed, expected):
            self.assertAlmostEqual(actual, target, delta=tolerance)

    def bad(self, name, value, code="invalid_arguments"):
        with self.assertRaises(ScientificToolError) as caught:
            self.call(name, value)
        self.assertEqual(caught.exception.code, code)

    # Thirty independent numerical oracles; none calls the tested upstream
    # algorithm to calculate its own expected answer.
    def test_oracle_raster_reproject(self):
        r = self.call("RasterReproject")["data"]
        self.assertEqual(r["values"], [[None, None], [4, None]])
        self.assertEqual(r["valid_mask"], [[False, False], [True, False]])
        self.assertEqual(r["origin_xy"], [1, 2])

    def test_oracle_raster_reproject_cross_crs(self):
        # Independent analytic coordinate: longitude 3 deg, latitude 0.
        # UTM31N center=(500000,0); Web Mercator center=(a*pi/60,0).
        # No upstream transform computes the expected answer.
        value = self.supplemental("raster_reproject_cross_crs.json")
        self.assertEqual(value["crs"], "EPSG:32631")
        self.assertEqual(value["dst_crs"], "EPSG:3857")
        self.assertNotEqual(value["crs"], value["dst_crs"])
        result = self.call("RasterReproject", value)
        self.assertEqual(result["crs"], "EPSG:3857")
        self.assertEqual(result["source_crs"], "EPSG:32631")
        self.assertEqual(result["data"]["dst_crs"], "EPSG:3857")
        self.assertEqual(result["data"]["values"], [[17]])
        self.assertEqual(result["data"]["valid_mask"], [[True]])
        self.assertEqual(result["data"]["shape"], [1, 1])
        x0 = 6378137.0 * math.pi / 60 - 0.5
        self.numbers(result["data"]["origin_xy"], [x0, 0.5], tolerance=1e-8)
        self.numbers(result["data"]["affine"], [1, 0, x0, 0, -1, 0.5], tolerance=1e-8)
        self.assertEqual(result["units"]["coordinates"], "m")
        self.assertEqual(result["source"], value["source"])
        Draft202012Validator(self.specs["GeoSpatialRasterReproject"]["output_schema"]).validate(result)

    def test_oracle_polygon_rasterize(self):
        self.assertEqual(self.call("PolygonRasterize")["data"]["values"], [[7, 0], [7, 0]])

    def test_oracle_raster_polygonize(self):
        f = self.call("RasterPolygonize")["data"]["features"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["class_id"], 2)
        self.assertEqual(f[0]["area_m2"], 3)
        self.assertEqual(shoelace(f[0]["wkt"]), 3)

    def test_oracle_polygon_intersection(self):
        d = self.call("PolygonIntersection")["data"]
        self.assertEqual(d["area_m2"], 2)
        self.assertEqual(shoelace(d["wkt"]), 2)

    def test_oracle_coverage_union(self):
        d = self.call("CoverageUnion")["data"]
        self.assertEqual(d["area_m2"], 4)
        self.assertEqual(shoelace(d["wkt"]), 4)

    def test_oracle_constrained_triangulation(self):
        d = self.call("ConstrainedTriangulation")["data"]
        self.assertEqual(len(d["triangles_wkt"]), 2)
        self.numbers(d["areas_m2"], [2, 2])
        self.numbers([shoelace(wkt) for wkt in d["triangles_wkt"]], [2, 2])

    def test_oracle_depression_fill(self):
        d = self.call("DepressionFill")["data"]
        self.assertEqual(d["filled_m"], [[5]*3 for _ in range(3)])
        self.assertEqual(d["fill_depth_m"], [[0,0,0], [0,4,0], [0,0,0]])
        self.assertEqual(d["fill_volume_m3"], 4)

    def test_oracle_height_above_drainage(self):
        d = self.call("HeightAboveDrainage")["data"]
        self.assertEqual(d["hand_m"][2], [None,3,2,0,None])
        self.assertEqual(d["reachable_mask"][2], [False,True,True,True,False])
        self.assertTrue(all(v is None for v in d["hand_m"][0]))

    def test_oracle_distance_to_outlet(self):
        d = self.call("DistanceToOutlet")["data"]
        self.assertEqual(d["distance_steps"][2], [None,2,1,0,None])

    def test_oracle_distance_to_ridge(self):
        d = self.call("DistanceToRidge")["data"]
        self.assertEqual(d["longest_upstream_steps"][2], [None,0,1,2,None])

    def test_oracle_strahler_order(self):
        order = self.call("StrahlerOrder")["data"]["order"]
        self.assertEqual(order[1][1], 1)
        self.assertEqual(order[1][3], 1)
        self.assertEqual(order[2][2], 2)
        self.assertEqual(order[3][2], 2)
        self.assertIsNone(order[0][0])

    def test_oracle_strahler_three_tributaries_221(self):
        # Two independent first-order pairs feed two order-2 tributaries.
        # A third order-1 tributary must NOT suppress the promotion to 3.
        value = self.supplemental("strahler_order_multi_221.json")
        result = self.call("StrahlerOrder", value)
        order = result["data"]["order"]
        self.assertEqual([order[2][2], order[2][4], order[2][3]], [2, 2, 1])
        self.assertEqual(order[3][3], 3)
        self.assertEqual(value["values"][4][3], 0)
        self.assertEqual(order[4][3], 3)
        self.assertEqual(result["provenance"]["reviewed_archive_commit"],
                         "4e598e77611232bbf5fc620919d914de5bfd2cdb")
        self.assertEqual(result["provenance"]["installed_versions"]["pyflwdir"], "0.5.12")
        for row, flags in zip(order, value["channels"]):
            self.assertEqual([v is not None for v in row], flags)

    def test_oracle_strahler_three_tributaries_112(self):
        # Only ONE tributary has the maximum order 2, so the result remains 2.
        # Combining the two order-1 branches first must not create a false 3.
        value = self.supplemental("strahler_order_multi_112.json")
        order = self.call("StrahlerOrder", value)["data"]["order"]
        self.assertEqual([order[2][2], order[2][3], order[2][4]], [1, 1, 2])
        self.assertEqual(order[3][3], 2)
        self.assertEqual(value["values"][4][3], 0)
        self.assertEqual(order[4][3], 2)

    def test_strahler_retains_cycle_and_channel_closure_rejections(self):
        value = deepcopy(self.fixtures["GeoSpatialStrahlerOrder"])
        value["values"][3][2] = 64  # Terminal points north, creating a cycle.
        self.bad("StrahlerOrder", value)
        value = deepcopy(self.fixtures["GeoSpatialStrahlerOrder"])
        value["channels"][3][2] = False
        self.bad("StrahlerOrder", value)

    def test_oracle_terrain_contours(self):
        lines = self.call("TerrainContours")["data"]["lines"]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["level_m"], .5)
        xy = lines[0]["coordinates"]
        self.numbers([x for x, _ in xy], [1]*len(xy))
        self.assertAlmostEqual(max(y for _, y in xy) - min(y for _, y in xy), 2)

    def test_oracle_local_moran(self):
        d = self.call("LocalMoran")["data"]
        self.numbers(d["local_i"], [-.45,.15,.15,-.45])
        self.assertEqual(d["quadrant"], [2,3,1,4])

    def test_oracle_bivariate_local_moran(self):
        self.numbers(self.call("BivariateLocalMoran")["data"]["local_i"], [.45,-.15,-.15,.45])

    def test_oracle_local_getis_ord(self):
        self.numbers(self.call("LocalGetisOrd")["data"]["gi"], [6/9, 4/8, 6/7, 4/6])

    def test_oracle_global_geary(self):
        self.assertAlmostEqual(self.call("GlobalGeary")["data"]["geary_c"], .9)

    def test_oracle_binary_join_counts(self):
        d = self.call("BinaryJoinCounts")["data"]
        self.assertEqual([d[k] for k in ["black_black", "white_white", "mixed", "total_edges"]], [1,1,2,4])

    def test_oracle_local_geary(self):
        self.numbers(self.call("LocalGeary")["data"]["local_c"], [4,.8,.8,4])

    def test_oracle_least_cost_path(self):
        d = self.call("LeastCostPath")["data"]
        self.assertEqual(d["path_rc"], [[0,0], [0,1], [0,2]])
        self.assertEqual(d["cost_s"], 2)

    def test_oracle_cost_allocation(self):
        d = self.call("CostAllocation")["data"]
        self.assertEqual(d["owner_index"], [[0,0,1]])
        self.assertEqual(d["cost_s"], [[0,1,0]])

    def test_oracle_euclidean_proximity(self):
        d = self.call("EuclideanProximity")["data"]["distance_m"]
        self.numbers(d[0], [0,1])
        self.numbers(d[1], [1,math.sqrt(2)])

    def test_oracle_resistance_distance(self):
        d = self.call("ResistanceDistance")["data"]
        # Two independent length-two unit-resistance routes in parallel.
        self.assertAlmostEqual(d["effective_resistance_s"], 1)
        self.assertEqual(d["connected_cells"], 4)

    def test_oracle_cost_corridor(self):
        d = self.call("CostCorridor")["data"]
        self.assertEqual(d["excess_cost_s"], [[0,0,0], [2,2,2]])
        self.assertEqual(d["corridor_mask"], [[True]*3, [False]*3])
        self.assertEqual(d["optimal_cost_s"], 2)

    def test_oracle_capacity_max_flow(self):
        self.assertEqual(self.call("CapacityMaxFlow")["data"]["maximum_flow_tonne_day"], 3)

    def test_oracle_ellipsoidal_polygon_area(self):
        a, f = 6378137.0, 1 / 298.257223563
        e = math.sqrt(f * (2-f))
        spheroid_area = 2 * math.pi * a*a * (1 + (1-e*e) / e * math.atanh(e))
        r = self.call("EllipsoidalPolygonArea")["data"]
        self.assertAlmostEqual(r["signed_area_m2"] / (spheroid_area/8), 1, delta=1e-11)
        self.assertGreater(r["perimeter_m"], 3e7)

    def test_oracle_geodesic_transect(self):
        d = self.call("GeodesicTransect")["data"]
        self.numbers([p[0] for p in d["points_lonlat"]], [0,1,2,3,4])
        self.numbers([p[1] for p in d["points_lonlat"]], [0]*5)
        self.assertAlmostEqual(d["length_m"], 6378137 * math.pi * 4 / 180, delta=1e-6)

    def test_oracle_projection_distortion(self):
        d = self.call("ProjectionDistortion")["data"]
        self.numbers(d["meridional_scale"], [.9996], tolerance=1e-8)
        self.numbers(d["parallel_scale"], [.9996], tolerance=1e-8)
        self.numbers(d["areal_scale"], [.9996**2], tolerance=1e-8)
        self.numbers(d["angular_distortion_degrees"], [0], tolerance=1e-4)
        self.numbers(d["meridian_convergence_degrees"], [0], tolerance=1e-8)

    def test_oracle_maximum_inscribed_circle(self):
        d = self.call("MaximumInscribedCircle")["data"]
        self.numbers(d["center_xy"], [1,1], tolerance=.001)
        self.assertAlmostEqual(d["radius_m"], 1, delta=.001)

    def test_oracle_site_voronoi(self):
        d = self.call("SiteVoronoi")["data"]
        self.numbers(d["areas_m2"], [2,2])
        self.numbers([shoelace(wkt) for wkt in d["cells_wkt"]], [2,2])

    def test_oracle_site_parcel_split(self):
        d = self.call("SiteParcelSplit")["data"]
        self.assertEqual(len(d["parcels_wkt"]), 2)
        self.numbers(d["areas_m2"], [2,2])
        self.numbers([shoelace(wkt) for wkt in d["parcels_wkt"]], [2,2])

    def test_grid_and_path_georeferencing_and_closed_schema(self):
        # Nine repaired outputs, plus the two raster construction/warp outputs.
        names = ["DepressionFill", "HeightAboveDrainage", "DistanceToOutlet",
                 "DistanceToRidge", "StrahlerOrder", "LeastCostPath",
                 "CostAllocation", "EuclideanProximity", "CostCorridor",
                 "RasterReproject", "PolygonRasterize"]
        for short in names:
            with self.subTest(tool=short):
                value = deepcopy(self.fixtures["GeoSpatial" + short])
                value["origin_xy"] = [432100.25, 5678900.75]
                value["cell_size_m"] = 3.5
                if short == "RasterReproject":
                    value["dst_origin_xy"] = [432103.75, 5678900.75]
                    value["dst_cell_size_m"] = 3.5
                    expected_origin = value["dst_origin_xy"]
                    expected_shape = value["dst_shape"]
                    expected_crs = value["dst_crs"]
                else:
                    expected_origin = value["origin_xy"]
                    expected_shape = value["shape"] if "shape" in value else [len(value["values"]), len(value["values"][0])]
                    expected_crs = value["crs"]
                result = self.call(short, value)
                data = result["data"]
                self.assertEqual(result["crs"], expected_crs)
                self.assertEqual(data["origin_xy"], expected_origin)
                self.assertEqual(data["cell_size_m"], 3.5)
                self.assertEqual(data["shape"], expected_shape)
                self.numbers(data["affine"], [3.5, 0, expected_origin[0], 0, -3.5, expected_origin[1]])
                a, b, c, d, e, f = data["affine"]
                row, col = expected_shape[0] - 1, expected_shape[1] - 1
                self.numbers([a*(col+.5) + b*(row+.5) + c, d*(col+.5) + e*(row+.5) + f],
                             [expected_origin[0] + 3.5*(col+.5), expected_origin[1] - 3.5*(row+.5)])
                if "path_rc" in data:
                    self.assertEqual(data["path_rc"][0], value["start_rc"])
                    self.assertEqual(data["path_rc"][-1], value["end_rc"])
                validator = Draft202012Validator(self.specs["GeoSpatial" + short]["output_schema"])
                validator.validate(result)
                for field in ("origin_xy", "cell_size_m", "affine", "shape"):
                    broken = deepcopy(result)
                    del broken["data"][field]
                    with self.assertRaises(ValidationError):
                        validator.validate(broken)
                broken = deepcopy(result)
                broken["data"]["undeclared_grid_parameter"] = 1
                with self.assertRaises(ValidationError):
                    validator.validate(broken)

    def test_geos_312_gate_is_explicit(self):
        import shapely
        # Negative capability metadata only; no scientific result is mocked.
        with patch.object(shapely, "geos_version", (3, 11, 9)):
            for short in ("CoverageUnion", "ConstrainedTriangulation",
                          "MaximumInscribedCircle", "SiteVoronoi"):
                with self.subTest(tool=short):
                    self.bad(short, deepcopy(self.fixtures["GeoSpatial" + short]),
                             code="incompatible_dependency")

    def test_every_candidate_dict_json_schema_units_and_provenance(self):
        for name in FUNCTIONS:
            with self.subTest(tool=name):
                result = self.call(name)
                from_json = self.call(name, as_json=True)
                self.assertEqual(result, from_json)
                Draft202012Validator(self.specs[name]["output_schema"]).validate(result)
                self.assertEqual(result["source"]["kind"], "synthetic")
                expected_crs = self.fixtures[name]["dst_crs"] if name == "GeoSpatialRasterReproject" else self.fixtures[name]["crs"]
                self.assertEqual(result["crs"], expected_crs)
                if name == "GeoSpatialRasterReproject":
                    self.assertEqual(result["source_crs"], self.fixtures[name]["crs"])
                self.assertEqual(result["units"]["coordinates"], self.fixtures[name]["coordinate_unit"])
                self.assertTrue(result["units"]["value"])
                self.assertEqual(result["artifacts"], [])
                p = result["provenance"]
                source_bytes = (self.directory / (name + ".json")).read_bytes()
                canonical = {"data_path": {"content_sha256": hashlib.sha256(source_bytes).hexdigest(),
                                           "bytes": len(source_bytes), "suffix": ".json"}}
                expected = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()
                self.assertEqual(p["input_sha256"], expected)
                self.assertEqual(p["implementation_sha256"], hashlib.sha256(Path(spatial.__file__).read_bytes()).hexdigest())
                self.assertEqual(p["reviewed_archive_commit"], self.specs[name]["registration_metadata"]["source_commit"])
                self.assertFalse(p["network_required"])
                for pin in self.specs[name]["metadata"]["upstream"]["requirements"]:
                    package, expected_version = pin.split("==")
                    self.assertEqual(p["installed_versions"][package], expected_version)
                    self.assertEqual(metadata.version(package), expected_version)

    def test_every_candidate_negative_unit_crs_and_source(self):
        for name, original in self.fixtures.items():
            mutations = [
                ("unknown-field", {**deepcopy(original), "undeclared": 7}),
                ("unit", {**deepcopy(original), "coordinate_unit": "feet"}),
                ("crs", {**deepcopy(original), "crs": "EPSG:32631" if original["coordinate_unit"] == "degree" else "EPSG:4326"}),
                ("blank-source", {**deepcopy(original), "source": {"kind": "synthetic", "citation": "    "}}),
                ("source-kind", {**deepcopy(original), "source": {"kind": "invented", "citation": "Synthetic data"}}),
            ]
            missing = deepcopy(original)
            del missing["source"]
            mutations.append(("missing-source", missing))
            for check, value in mutations:
                with self.subTest(tool=name, check=check):
                    self.bad(name, value)

    def test_every_candidate_task_specific_negative(self):
        # These domain errors supplement, rather than replace, the per-tool
        # schema/unit/CRS/source checks above.
        alterations = {
            "RasterReproject": {"dst_crs": "EPSG:4326"},
            "PolygonRasterize": {"class_ids": [7,8]},
            "RasterPolygonize": {"values": [[2.5,2], [2,None]]},
            "PolygonIntersection": {"polygon_a_wkt": "POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))"},
            "CoverageUnion": {"polygons_wkt": ["POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"]*2},
            "ConstrainedTriangulation": {"polygon_wkt": "POINT (0 0)"},
            "DepressionFill": {"values": [[5,None,5],[5,1,5],[5,5,5]]},
            "HeightAboveDrainage": {"channels": [[False]*5 for _ in range(5)]},
            "DistanceToOutlet": {"outlet_rc": [0,0]},
            "DistanceToRidge": {"values": [[0]*5 for _ in range(5)]},
            "StrahlerOrder": {"channels": [[False]*5 for _ in range(5)]},
            "TerrainContours": {"levels_m": [1,1]},
            "LocalMoran": {"values": [1,1,1,1]},
            "BivariateLocalMoran": {"other_values": [1,1,1,1]},
            "LocalGetisOrd": {"values": [-1,2,3,4]},
            "GlobalGeary": {"radius_m": .1},
            "BinaryJoinCounts": {"values": [0,0,2,1]},
            "LocalGeary": {"points_xy": [[0,0],[0,0],[1,1],[0,1]]},
            "LeastCostPath": {"start_rc": [0,2]},
            "CostAllocation": {"sources_rc": [[0,0],[0,0]]},
            "EuclideanProximity": {"values": [[0,0],[0,0]]},
            "ResistanceDistance": {"values": [[-1,1],[1,1]]},
            "CostCorridor": {"max_excess_s": -1},
            "CapacityMaxFlow": {"values": [[5,2.5,4]]},
            "EllipsoidalPolygonArea": {"polygon_wkt": "POLYGON ((0 91, 2 91, 2 92, 0 92, 0 91))"},
            "GeodesicTransect": {"end_lonlat": [0,0]},
            "ProjectionDistortion": {"projection_crs": "EPSG:4326"},
            "MaximumInscribedCircle": {"tolerance_m": 3},
            "SiteVoronoi": {"points_xy": [[.5,1],[.5,1]]},
            "SiteParcelSplit": {"splitter_wkt": "POINT (1 1)"},
        }
        self.assertEqual({"GeoSpatial"+s for s in alterations}, set(FUNCTIONS))
        for short, changes in alterations.items():
            with self.subTest(tool=short):
                self.bad(short, {**deepcopy(self.fixtures["GeoSpatial"+short]), **changes})

    def test_routing_cycles_are_errors_and_no_mask_is_inferred(self):
        value = deepcopy(self.fixtures["GeoSpatialDistanceToRidge"])
        value["values"][2][2] = 16  # The two interior cells point at each other.
        self.bad("DistanceToRidge", value)
        value = deepcopy(self.fixtures["GeoSpatialHeightAboveDrainage"])
        value["values"][2][2] = 8  # Uphill successor from the 5 m source.
        self.bad("HeightAboveDrainage", value)
        for name in ["GeoSpatialRasterReproject", "GeoSpatialEuclideanProximity", "GeoSpatialLeastCostPath"]:
            value = deepcopy(self.fixtures[name])
            value["valid_mask"][0][0] = False
            self.bad(name, value)

    def test_dimensional_scaling_has_physical_meaning(self):
        value = deepcopy(self.fixtures["GeoSpatialDepressionFill"])
        value["cell_size_m"] = 2
        self.assertEqual(self.call("DepressionFill", value)["data"]["fill_volume_m3"], 16)
        value = deepcopy(self.fixtures["GeoSpatialLeastCostPath"])
        value["cell_size_m"] = 10
        self.assertEqual(self.call("LeastCostPath", value)["data"]["cost_s"], 20)
        value = deepcopy(self.fixtures["GeoSpatialEuclideanProximity"])
        value["cell_size_m"] = 10
        self.assertAlmostEqual(self.call("EuclideanProximity", value)["data"]["distance_m"][1][1], math.sqrt(200))

    def test_cost_barrier_allocation_and_resistance_disconnect(self):
        value = deepcopy(self.fixtures["GeoSpatialCostAllocation"])
        value["values"] = [[1,None,1]]
        value["valid_mask"] = [[True,False,True]]
        d = self.call("CostAllocation", value)["data"]
        self.assertEqual(d["cost_s"], [[0,None,0]])
        self.assertEqual(d["owner_index"], [[0,None,1]])
        value = deepcopy(self.fixtures["GeoSpatialResistanceDistance"])
        value["values"] = [[1,None],[None,1]]
        value["valid_mask"] = [[True,False],[False,True]]
        self.bad("ResistanceDistance", value, code="unsupported_conditions")

    def test_transport_and_resource_bounds(self):
        for name in FUNCTIONS:
            with self.subTest(tool=name, check="unknown-argument"):
                with self.assertRaises(ScientificToolError):
                    FUNCTIONS[name]({"data_path": "unused.json", "function": "os.system"})
            with self.subTest(tool=name, check="missing-file"):
                with self.assertRaises(ScientificToolError) as caught:
                    FUNCTIONS[name]({"data_path": str(self.directory / "missing.json")})
                self.assertEqual(caught.exception.code, "missing_input")
        name = "GeoSpatialLocalMoran"
        path = self.directory / "oversize.json"
        path.write_text(" "*262145, encoding="utf-8")
        with self.assertRaises(ScientificToolError) as caught:
            FUNCTIONS[name]({"data_path": str(path)})
        self.assertEqual(caught.exception.code, "resource_limit")
        with self.assertRaises(ScientificToolError):
            FUNCTIONS[name]('{"data_path":"a","data_path":"b"}')

    def test_manifests_one_to_one_sources_licenses_and_closed_schemas(self):
        candidates = json.loads((GROUP / "candidate-operations.json").read_text(encoding="utf-8"))
        examples = json.loads((GROUP / "examples-additions.json").read_text(encoding="utf-8"))
        sources = json.loads((GROUP / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(set(candidates), {"group", "operations"})
        self.assertEqual(candidates["group"], "spatial")
        self.assertEqual(len(candidates["operations"]), 30)
        self.assertEqual({r["tool_id"] for r in candidates["operations"]}, set(FUNCTIONS))
        self.assertEqual(set(examples), set(FUNCTIONS))
        self.assertEqual(set(self.specs), set(FUNCTIONS))
        self.assertEqual(len(self.bundle["skills"]), 5)
        for skill in self.bundle["skills"]:
            self.assertEqual(len(skill["tool_references"]), 6)
            self.assertTrue((ROOT / skill["skill_file"]).is_file())
        rows = {r["package"]: r for r in sources["sources"]}
        candidate_fields = {"tool_id", "capability_key", "upstream_callable", "scientific_task",
                            "distinct_from_existing", "numeric_oracle", "status"}
        for candidate in candidates["operations"]:
            name = candidate["tool_id"]
            with self.subTest(tool=name):
                self.assertEqual(set(candidate), candidate_fields)
                self.assertEqual(candidate["status"], "source_authored_unverified")
                spec = self.specs[name]
                upstream = spec["metadata"]["upstream"]
                evidence = rows[upstream["package"]]
                self.assertEqual(candidate["upstream_callable"], upstream["callable"])
                self.assertEqual(upstream["version"], evidence["version"])
                self.assertEqual(upstream["source_commit"], evidence["source_commit"])
                self.assertRegex(evidence["source_commit"], r"^[a-f0-9]{40}$")
                self.assertTrue(evidence["license_url"].startswith(evidence["repository"] + "/blob/"))
                self.assertGreater(len((GROUP / evidence["license_evidence_file"]).read_bytes()), 100)
                self.assertTrue(examples[name]["data_path"].startswith("assets/github-expansion-spatial/"))
                self.assertEqual(spec["source_interface"]["kind"], "github_expansion_spatial")
                self.assertEqual(spec["source_interface"]["entrypoint"]["callable"],
                                 "geological_agent.geology.github_expansion_spatial:" + FUNCTIONS[name].__name__)
                for schema in (spec["input_schema"], spec["output_schema"], spec["metadata"]["scientific_contract"]["data_schema"]):
                    Draft202012Validator.check_schema(schema)
                    self.closed_objects(schema)
                Draft202012Validator(spec["metadata"]["scientific_contract"]["data_schema"]).validate(self.fixtures[name])

    def closed_objects(self, schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                self.assertIs(schema.get("additionalProperties"), False)
            for child in schema.values():
                self.closed_objects(child)
        elif isinstance(schema, list):
            for child in schema:
                self.closed_objects(child)


if __name__ == "__main__":
    unittest.main()
