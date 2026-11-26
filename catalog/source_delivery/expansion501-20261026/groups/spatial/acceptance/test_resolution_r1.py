"""Independent pending-source checks. No fabricated native/scientific passes."""
import ast
from copy import deepcopy
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

GROUP=Path(__file__).resolve().parents[1]
ROOT=GROUP.parents[4]
SUPPORT=ROOT/"geological_agent/geology/expansion501_spatial_support"
package=types.ModuleType("_resolution_test_support")
package.__path__=[str(SUPPORT)]
sys.modules[package.__name__]=package
common=importlib.import_module(package.__name__+".common")


class SourceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs=json.loads((GROUP/"pending-contracts.json").read_text())
        cls.examples=json.loads((GROUP/"pending-examples.json").read_text())

    def test_all_pending_entries_closed_and_unregistered(self):
        ids={t["id"] for t in json.loads((GROUP/"catalog-additions.json").read_text())["tools"]}
        self.assertEqual(len(self.specs),11)
        self.assertFalse(ids.intersection(self.specs))
        for spec in self.specs.values():
            for key in ("input_schema","output_schema"):
                self.assertIs(spec[key]["additionalProperties"],False)
            self.assertTrue({"units","artifacts","provenance"}.issubset(spec["output_schema"]["required"]))
            self.assertFalse(spec["formal_eligible"])
            self.assertEqual(spec["metadata_profile"],"scientific")

    def test_named_entrypoint_definitions_match_pending_contracts(self):
        tree=ast.parse((ROOT/"geological_agent/geology/expansion501_spatial.py").read_text())
        decorated={}
        for node in tree.body:
            if isinstance(node,ast.FunctionDef):
                for d in node.decorator_list:
                    if isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id=="operation":
                        decorated[d.args[0].value]=node.name
        for tool,spec in self.specs.items():
            self.assertEqual(decorated[tool],spec["entrypoint"]["function"])

    def test_every_fixture_is_synthetic_and_has_oracle(self):
        self.assertEqual(set(self.examples),set(self.specs))
        for fixture in self.examples.values():
            self.assertEqual(fixture["fixture_kind"],"synthetic")
            self.assertEqual(fixture["status"],"not_run")
            self.assertTrue(fixture["numeric_oracle"])

    def test_no_user_native_dispatch_fields(self):
        forbidden={"executable","command","shell","pipeline","profile","function","module","install","options"}
        for spec in self.specs.values():
            self.assertFalse(forbidden.intersection(spec["input_schema"]["properties"]))

    def test_no_fabricated_binary_identity(self):
        evidence=json.loads((GROUP/"resolution-evidence.json").read_text())
        self.assertFalse(evidence["license_closure_complete"])
        self.assertIsNone(evidence["native_binary_hashes"])
        self.assertFalse((SUPPORT/"native-profile.json").exists())

    def test_finite_negative_cases(self):
        for v in (float("nan"),float("inf"),float("-inf")):
            with self.subTest(value=repr(v)),self.assertRaises(common.ContractError):
                common.finite({"nested":[v]})
        common.finite({"nested":[1,2.5,None]})

    def test_exact_dependency_does_not_silently_substitute(self):
        with self.assertRaises(common.ContractError) as found:
            common.exact(["spatial-absent-synthetic-distribution==1.0.0"])
        self.assertEqual(found.exception.code,"missing_dependency")

    def test_artifact_digest_bytes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            result=common.artifact(d,"fixture.csv",b"X,Y\n1,2\n","text/csv")
            self.assertEqual(result["sha256"],hashlib.sha256(b"X,Y\n1,2\n").hexdigest())
            self.assertEqual(result["bytes"],8)
            with self.assertRaises(FileExistsError):
                common.artifact(d,"fixture.csv",b"different","text/csv")

    def test_artifact_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(common.ContractError):
                common.artifact(d,"../escape",b"data","text/plain")

    def test_blocked_accounting_preserved(self):
        status=json.loads((GROUP/"resolution-status.json").read_text())
        self.assertEqual((status["assigned_blocked"],status["new_concrete_kernels"],status["scientific_adapters_still_incomplete"]),(19,11,8))
        self.assertEqual(status["new_accepted"],0)
        adaptations={r["id"]:r for r in json.loads((GROUP/"adaptation-status.json").read_text())["operations"]}
        for tool in self.specs:
            self.assertEqual(adaptations[tool]["state"],"blocked")


def exact_available(requirements):
    try:
        return all(importlib.metadata.version(r.split("==")[0])==r.split("==")[1] for r in requirements)
    except importlib.metadata.PackageNotFoundError:
        return False


class ScientificOracles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs=json.loads((GROUP/"pending-contracts.json").read_text())
        cls.examples=json.loads((GROUP/"pending-examples.json").read_text())
        if not exact_available(cls.specs["GeoTidalCycleFlow"]["requirements"]):
            raise unittest.SkipTest("Exact Landlab private dependency profile unavailable; no scientific acceptance")
        cls.impl=importlib.import_module(package.__name__+".landlab_state")

    def test_tidal_independent_volume_rate(self):
        args=deepcopy(self.examples["GeoTidalCycleFlow"]["input"])
        result=self.impl.tidal_cycle_flow(args)
        cycle=result["cycles"][0]
        self.assertAlmostEqual(cycle["boundary_inflow_m3_s"],.0012,delta=1e-10)
        for f,e in zip(cycle["flood_velocity_m_s"],cycle["ebb_velocity_m_s"]):
            self.assertAlmostEqual(f,-e,delta=1e-12)
        args["cycles"][0]["range_m"]=0
        for value in self.impl.tidal_cycle_flow(args)["cycles"][0]["flood_velocity_m_s"]:
            self.assertAlmostEqual(value,0,delta=1e-12)

    def test_landslide_empty_events_conserve_state(self):
        args=deepcopy(self.examples["GeoBedrockLandslideEvolution"]["input"])
        result=self.impl.bedrock_landslide_evolution(args)
        self.assertEqual(result["bedrock_elevation_m"],args["bedrock_elevation_m"])
        self.assertEqual(result["soil_depth_m"],args["soil_depth_m"])
        self.assertEqual(result["suspended_volume_m3"],0)
        self.assertEqual(result["exported_volume_m3"],0)

    def test_parcel_zero_shear_and_actual_time_records(self):
        args=deepcopy(self.examples["GeoRiverSedimentParcelTransport"]["input"])
        result=self.impl.river_sediment_parcel_transport(args)
        self.assertEqual([r["time_s"] for r in result["history"]],[0,1,3])
        for record in result["history"]:
            self.assertEqual(record["retained_mass_kg"],7950)
            self.assertEqual(record["exported_mass_kg"],0)
            self.assertEqual(record["abrasion_loss_kg"],0)
            for i,p in enumerate(record["parcels"]):
                self.assertEqual(p["link"],i)
                self.assertEqual(p["location_fraction"],.25)
                self.assertEqual(p["diameter_m"],.05)


if __name__=="__main__":
    unittest.main(verbosity=2)
