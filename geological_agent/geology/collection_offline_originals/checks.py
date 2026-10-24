"""Independent numerical oracles, not copies of the kernels under test."""
import math


def check(name, result, args, directory=None):
    assert isinstance(result.get("units"), dict) and result["units"]
    if name == "EarthPyOWMBeaufortWind":
        limits = [0.2, 1.5, 3.3, 5.4, 7.9, 10.7, 13.8, 17.1, 20.7, 24.4, 28.4, 32.6]
        expected = [sum(value > limit for limit in limits) for value in args["wind_speed_m_s"]]
        assert result["beaufort"] == expected
        assert result["wind_speed_m_s"] == args["wind_speed_m_s"]
    elif name == "EarthSimRasterCrossSection":
        assert result["values"] == [0, 6, 18, 24]
        assert len(result["distance"]) == 4
        assert abs(result["distance"][-1] - math.sqrt(32)) < 1e-10
        assert result["x"][0] == 0.5 and result["y"][-1] == 0.5
    elif name == "EarthERA5LocalMonthlyClimate":
        assert result["months"] == list(range(1, 13))
        assert result["point_series"] == [270 + 4 * index for index in range(24)]
        expected = [[[294 + month * 4 + row * 2 + col for col in range(2)] for row in range(2)] for month in range(12)]
        assert result["monthly_mean"] == expected
        assert result["selected_longitude"] == 116.4 and result["selected_latitude"] == 39.9
    elif name == "EarthPangaeaGeographicGrid":
        assert result["rows_reversed"] is True
        assert result["values"] == [[3, 4], [1, 2]]
        assert result["latitude"] == [[20, 20], [10, 10]]
        assert result["longitude"] == [[-10, -5], [-10, -5]]
        assert result["center_longitude"] == -7.5 and result["center_latitude"] == 15
    elif name == "EarthGeoNotebookPolygonSubset":
        expected = [[6, 7, 8], [11, 12, 13], [16, 17, 18]]
        assert result["values"] == expected
        assert result["valid_cells"] == 9 and result["mean"] == 12
        assert result["minimum"] == 6 and result["maximum"] == 18
    elif name == "EarthHydroShareRasterBandRanges":
        band = result["bands"]["1"]
        assert band["minimumValue"] == 0 and band["maximumValue"] == 24
        assert band["variableUnit"] == "m" and band["noDataValue"] == -9999
    else:
        raise AssertionError("Every proposed operation must have an independent oracle")

