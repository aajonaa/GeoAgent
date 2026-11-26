"""Synthetic checks of reporting gates; these are not scientific tool cases."""
import unittest
import xml.etree.ElementTree as ET

from run_cpu_acceptance import (
    DIAGNOSTIC_CLASS, DIAGNOSTIC_NODE, DIAGNOSTIC_TEST, GEOPHYSICS_MODULE,
    classify_historical_diagnostic, group_selections,
)


class ReportingGateTests(unittest.TestCase):
    def case(self):
        case = ET.Element("testcase", name=DIAGNOSTIC_TEST, classname="tests_local.test_github_expansion_geophysics." + DIAGNOSTIC_CLASS)
        ET.SubElement(case, "skipped", type="pytest.xfail")
        return case

    def test_expected_failure_is_not_a_pass_or_available_tool(self):
        outcome = classify_historical_diagnostic(0, [self.case()])
        self.assertEqual(outcome["expected_failures"], 1)
        self.assertEqual(outcome["passed_cases"], 0)
        self.assertFalse(outcome["counted_as_available_tool"])
        self.assertTrue(outcome["recorded"])

    def test_ordinary_skip_rejected(self):
        case = self.case()
        case.find("skipped").set("type", "pytest.skip")
        with self.assertRaises(ValueError):
            classify_historical_diagnostic(0, [case])

    def test_unexpected_success_rejected(self):
        case = self.case()
        case.remove(case.find("skipped"))
        with self.assertRaises(ValueError):
            classify_historical_diagnostic(0, [case])

    def test_different_test_rejected(self):
        case = self.case()
        case.set("name", "test_other")
        with self.assertRaises(ValueError):
            classify_historical_diagnostic(0, [case])

    def test_different_class_rejected(self):
        case = self.case()
        case.set("classname", "unrelated.Test")
        with self.assertRaises(ValueError):
            classify_historical_diagnostic(0, [case])

    def test_nonzero_exit_rejected(self):
        with self.assertRaises(ValueError):
            classify_historical_diagnostic(1, [self.case()])

    def test_missing_or_extra_cases_rejected(self):
        for cases in ([], [self.case(), self.case()]):
            with self.subTest(count=len(cases)), self.assertRaises(ValueError):
                classify_historical_diagnostic(0, cases)

    def test_failure_and_error_are_not_hidden(self):
        for tag in ("failure", "error"):
            case = self.case()
            ET.SubElement(case, tag)
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                classify_historical_diagnostic(0, [case])

    def test_only_exact_historical_node_is_separated(self):
        self.assertEqual(group_selections("geophysics"), [GEOPHYSICS_MODULE, "--deselect=" + DIAGNOSTIC_NODE])
        for group in ("remote", "geology", "spatial"):
            self.assertEqual(group_selections(group), ["tests_local/test_github_expansion_" + group + ".py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
