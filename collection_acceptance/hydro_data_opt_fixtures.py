"""Create small, explicitly synthetic assets for coordinator-run CPU acceptance."""
from pathlib import Path
import json

PREFIX = "assets/earth-collection/hydro_data_opt/"

WATERML1 = '''<?xml version="1.0" encoding="UTF-8"?>
<!-- SYNTHETIC: fabricated discharge, not observations -->
<timeSeriesResponse xmlns="http://www.cuahsi.org/waterML/1.1/">
<timeSeries><sourceInfo><siteName>SYNTHETIC station</siteName><siteCode network="SYNTHETIC">SYN001</siteCode></sourceInfo>
<variable><variableCode>00060</variableCode><variableName>SYNTHETIC discharge</variableName>
<unit><unitAbbreviation>m3/s</unitAbbreviation></unit><noDataValue>-9999</noDataValue></variable>
<values><value dateTime="2020-01-01T00:00:00Z" qualifiers="SYNTHETIC">1.5</value>
<value dateTime="2020-01-02T00:00:00Z" qualifiers="SYNTHETIC">-9999</value>
<value dateTime="2020-01-03T00:00:00Z" qualifiers="SYNTHETIC">3.5</value></values></timeSeries>
</timeSeriesResponse>
'''

FEWS = '''<?xml version="1.0" encoding="UTF-8"?>
<!-- SYNTHETIC: fabricated FEWS-PI events -->
<TimeSeries xmlns="http://www.wldelft.nl/fews/PI"><timeZone>0.0</timeZone><series><header>
<moduleInstanceId>SYNTHETIC</moduleInstanceId><locationId>SYN001</locationId><stationName>SYNTHETIC station</stationName>
<parameterId>Q.synthetic</parameterId><units>m3/s</units></header>
<event date="2020-01-01" time="00:00:00" value="1.25" flag="0" user="SYNTHETIC"/>
<event date="2020-01-02" time="00:00:00" value="2.5" flag="1" user="SYNTHETIC"/>
</series></TimeSeries>
'''

WATERML2 = '''<?xml version="1.0" encoding="UTF-8"?>
<!-- SYNTHETIC: fabricated BOM SOS / WaterML 2.0 observations -->
<sos:GetObservationResponse xmlns:sos="http://www.opengis.net/sos/2.0" xmlns:w="http://www.opengis.net/waterml/2.0"
 xmlns:om="http://www.opengis.net/om/2.0" xmlns:xlink="http://www.w3.org/1999/xlink">
<w:generationDate>2020-01-04T00:00:00Z</w:generationDate><sos:observationData><om:OM_Observation>
<om:procedure xlink:href="urn:synthetic:procedure" xlink:title="SYNTHETIC procedure"/>
<om:observedProperty xlink:href="urn:synthetic:discharge" xlink:title="SYNTHETIC discharge"/>
<om:featureOfInterest xlink:href="urn:synthetic:SYN001" xlink:title="SYNTHETIC station"/>
<om:result><w:MeasurementTimeseries><w:defaultPointMetadata><w:DefaultTVPMeasurementMetadata>
<w:uom code="m3/s"/></w:DefaultTVPMeasurementMetadata></w:defaultPointMetadata>
<w:point><w:MeasurementTVP><w:time>2020-01-01T00:00:00Z</w:time><w:value>4</w:value></w:MeasurementTVP></w:point>
<w:point><w:MeasurementTVP><w:time>2020-01-02T00:00:00Z</w:time><w:value>8</w:value></w:MeasurementTVP></w:point>
</w:MeasurementTimeseries></om:result></om:OM_Observation></sos:observationData></sos:GetObservationResponse>
'''


def fixture_contents():
    forecast = {
        "synthetic": True, "unit": "mm", "times": ["2020-01-01", "2020-01-02"],
        "station_ids": ["SYN001", "SYN002"], "lead_hours": [0, 24, 48],
        "values": [[[[1, 2, 3], [10, 20, 30]], [[4, 5, 6], [40, 50, 60]]],
                   [[[7, 8, 9], [70, 80, 90]], [[11, 12, 13], [110, 120, 130]]]],
    }
    return {
        "README_SYNTHETIC.txt": "All assets here are fabricated acceptance examples. No real observations, credentials or models.\n",
        "synthetic_waterml1.xml": WATERML1,
        "synthetic_fews_pi.xml": FEWS,
        "synthetic_bom_waterml2.xml": WATERML2,
        "synthetic_camels.csv": "year,month,day,SYN001,SYN002\n2020,1,1,1,10\n2020,1,2,-9999,20\n2020,1,3,3,30\n",
        "synthetic_htimeseries.csv": "2020-01-01 00:00,1.5,SYNTHETIC\n2020-01-02 00:00,,SYNTHETIC_MISSING\n2020-01-03 00:00,3.5,SYNTHETIC\n",
        "synthetic_efts.json": json.dumps(forecast, indent=2) + "\n",
        "synthetic_forbidden_dtd.xml": '<!DOCTYPE x [<!ENTITY e "SYNTHETIC">]><x>&e;</x>\n',
        "synthetic_duplicate_records.csv": "2020-01-01 00:00,1,SYNTHETIC\n2020-01-01 00:00,2,SYNTHETIC\n",
        "synthetic_oversize.txt": "SYNTHETIC_OVERSIZE\n" + "x" * (2 * 1024 * 1024),
    }


def create(root: Path):
    root = Path(root).resolve()
    destination = root / "assets" / "earth-collection" / "hydro_data_opt"
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.resolve().is_relative_to(root):
        raise ValueError("Synthetic fixture destination escapes the supplied root")
    written = []
    for name, content in fixture_contents().items():
        path = destination / name
        if path.exists() or path.is_symlink():
            continue
        with path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(content)
        written.append(PREFIX + name)
    return written
