"""Local artifact-accounting/source tests only, never native engine acceptance."""
import ast
from copy import deepcopy
import importlib
import json
import math
import os
from pathlib import Path
import sys
import types
import unittest

GROUP=Path(__file__).resolve().parents[1]; ROOT=GROUP.parents[4]
package=types.ModuleType("_spatial_continuation_r7")
package.__path__=[str(ROOT/"geological_agent/geology/expansion501_spatial_support")]
sys.modules[package.__name__]=package
native=importlib.import_module(package.__name__+".native")
Error=importlib.import_module(package.__name__+".common").ContractError
IDS={"GeoSpatialRigidPointCloudRegistration","GeoSpatialNavigationBasedLidarGeoreference",
     "GeoSpatialSurveyPoissonSurface","GeoSpatialTerrainSolarIrradiance"}


def tetrahedron(open_mesh=False):
    faces=["3 0 2 1","3 0 1 3","3 0 3 2","3 1 2 3"]
    if open_mesh: faces=faces[:-1]
    return ("ply\nformat ascii 1.0\nelement vertex 4\nproperty double X\nproperty double Y\nproperty double Z\n"
            "element face "+str(len(faces))+"\nproperty list uchar int vertex_indices\nend_header\n"
            "0 0 0\n1 0 0\n0 1 0\n0 0 1\n"+"\n".join(faces)+"\n").encode()


class ArtifactAccounting(unittest.TestCase):
    def test_tetrahedron_independent_area_volume(self):
        result=native._ply_mesh_summary(tetrahedron())
        self.assertEqual(result["vertex_count"],4)
        self.assertEqual(result["triangle_count"],4)
        self.assertAlmostEqual(result["surface_area_m2"],(3+math.sqrt(3))/2,delta=1e-12)
        self.assertAlmostEqual(result["oriented_volume_m3"],1/6,delta=1e-12)
        self.assertTrue(result["closed_two_manifold_edges"])
        self.assertTrue(result["consistent_edge_orientation"])

    def test_open_mesh_never_claims_enclosed_volume(self):
        result=native._ply_mesh_summary(tetrahedron(True))
        self.assertFalse(result["closed_two_manifold_edges"])
        self.assertIsNone(result["oriented_volume_m3"])

    def test_mesh_bad_indices_and_nonfinite_vertices(self):
        for blob in (tetrahedron().replace(b"3 1 2 3",b"3 1 2 9"),
                     tetrahedron().replace(b"0 0 1\n",b"0 0 nan\n")):
            with self.subTest(blob=blob[-40:]),self.assertRaises(Error):
                native._ply_mesh_summary(blob)

    def test_csv_point_identity_restoration(self):
        rows=native._ordered_point_rows(b"X,Y,Z,PointId\n4,5,6,1\n1,2,3,0\n",["X","Y","Z","PointId"],2)
        self.assertEqual(rows,[[1,2,3,0],[4,5,6,1]])

    def test_csv_identity_and_finite_negatives(self):
        for blob in (b"X,Y,Z,PointId\n1,2,3,0\n4,5,6,0\n",b"X,Y,Z,PointId\n1,2,inf,0\n"):
            with self.subTest(blob=blob),self.assertRaises(Error):
                native._ordered_point_rows(blob,["X","Y","Z","PointId"],2)

    def test_raster_extent_and_nodata_not_silently_changed(self):
        header={"north":2,"south":0,"east":2,"west":0,"rows":2,"cols":2}
        blob=b"north: 2\nsouth: 0\neast: 2\nwest: 0\nrows: 2\ncols: 2\n0 1\n2 3\n"
        self.assertEqual(native._grass_numeric(blob,header),[[0,1],[2,3]])
        for invalid in (blob.replace(b"north: 2",b"north: 3"),blob.replace(b"2 3\n",b"2 *\n"),blob.replace(b"2 3\n",b"2 -1\n")):
            with self.subTest(blob=invalid),self.assertRaises(Error): native._grass_numeric(invalid,header)


class SourceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pending=json.loads((GROUP/"pending-contracts.json").read_text())
        cls.examples=json.loads((GROUP/"pending-examples.json").read_text())
        cls.evidence=json.loads((GROUP/"continuation-r7-evidence.json").read_text())

    def test_exact_four_defined_entrypoints(self):
        tree=ast.parse((ROOT/"geological_agent/geology/expansion501_spatial.py").read_text())
        defined={d.args[0].value:node.name for node in tree.body if isinstance(node,ast.FunctionDef)
                 for d in node.decorator_list if isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id=="operation"}
        self.assertEqual({row["id"] for row in self.evidence["operations"]},IDS)
        for tool in IDS:
            self.assertEqual(defined[tool],self.pending[tool]["entrypoint"]["function"])
            self.assertTrue(callable(getattr(native,self.pending[tool]["private_kernel"]["function"])))

    def test_closed_schemas_no_arbitrary_dispatch(self):
        for tool in IDS:
            with self.subTest(tool=tool):
                spec=self.pending[tool]
                for kind in ("input_schema","output_schema"):
                    self.assertIs(spec[kind]["additionalProperties"],False)
                self.assertTrue({"units","artifacts","provenance"} <= set(spec["output_schema"]["required"]))
                self.assertFalse({"pipeline","shell","command","executable","module","function","install","profile"} & set(spec["input_schema"]["properties"]))
                self.assertEqual(self.examples[tool]["fixture_kind"],"synthetic")
                self.assertEqual(self.examples[tool]["status"],"not_run")

    def test_native_units_and_null_identity_honest(self):
        georef=self.pending["GeoSpatialNavigationBasedLidarGeoreference"]["output_schema"]["properties"]
        self.assertEqual(georef["units"]["properties"]["X"]["const"],"degree_longitude")
        self.assertEqual(georef["units"]["properties"]["Z"]["const"],"m_ellipsoidal")
        solar=self.pending["GeoSpatialTerrainSolarIrradiance"]["output_schema"]["properties"]
        self.assertEqual(solar["units"]["properties"]["irradiance"]["const"],"W/m2")
        for row in self.evidence["operations"]:
            self.assertIsNone(row["binary_sha256"])
            self.assertFalse(row["native_license_closure_complete"])

    def test_existing_eleven_numeric_contracts_preserved(self):
        original=json.loads((GROUP/"continuation-r7-prior-contracts.json").read_text())
        self.assertEqual(len(original["pending"]),11)
        for tool,spec in original["pending"].items():
            self.assertEqual(self.pending[tool],spec)
            self.assertEqual(self.examples[tool],original["examples"][tool])

    def test_counts_still_blocked_unregistered(self):
        status=json.loads((GROUP/"resolution-status.json").read_text())
        self.assertEqual((len(self.pending),status["scientific_adapters_still_incomplete"]),(15,4))
        catalog={row["id"] for row in json.loads((GROUP/"catalog-additions.json").read_text())["tools"]}
        self.assertFalse(IDS & catalog)
        adaptation={row["id"]:row for row in json.loads((GROUP/"adaptation-status.json").read_text())["operations"]}
        for tool in IDS: self.assertEqual(adaptation[tool]["state"],"blocked")
        self.assertEqual(self.evidence["native_scientific_tests_run"],0)
        self.assertEqual(self.evidence["new_accepted"],0)
        self.assertEqual(self.evidence["remote_environment_preparations"],0)

    def test_delivery_contains_no_fifth_helper(self):
        files=json.loads((GROUP/"delivery-files.json").read_text())["files"]
        prefix="geological_agent/geology/expansion501_spatial_support/"
        self.assertEqual({path for path in files if path.startswith(prefix)},
                         {prefix+name for name in ("common.py","landlab_state.py","native.py","grass_task.py")})


if __name__=="__main__":
    result=unittest.main(verbosity=2,exit=False).result
    report={"scope":"local_artifact_accounting_and_source_contracts_only","tests_run":result.testsRun,
            "failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),
            "native_scientific_tests_run":0,"main_runtime_bridge_tests_run":0,"new_accepted":0}
    if os.environ.get("SPATIAL_R7_LOCAL_REPORT"):
        Path(os.environ["SPATIAL_R7_LOCAL_REPORT"]).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
