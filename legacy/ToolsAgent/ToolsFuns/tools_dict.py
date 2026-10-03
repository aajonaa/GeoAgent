from ToolsFuns.GIS.gis_tools import GIS_TOOL_NAMES
from ToolsFuns.Meteorology.meteorology_tools import METEOROLOGY_TOOL_NAMES
from ToolsFuns.OceanPhysics.ocean_physics_tools import OCEAN_PHYSICS_TOOL_NAMES


TOOLS_MAPPING = {
    "GeoscienceTools": [
        "GeoCheckCRSConsistency",
        "GeoHaversineDistance",
        "GeoMagnitudeToEnergy",
        "GeoBearing",
        "GeoDecimalToDMS",
        "GeoWGS84BBoxAreaKm2",
    ],
    "GeoTools": [
        "USGS 地震数据获取",
        "地震数据清洗与分级",
        "地震事件地图可视化",
        "ObsPy数据获取",
        "ObsPy波形可视化",
        "ObsPy数据预处理",
        "ObsPy震相拾取",
        "Pyrocko地震定位",
        "ObsPy震级计算",
        "SKHASH震源机制反演",
        "PyGMT地震成果制图",
        "surfQuake集成地震处理",
        "SeisBench深度学习震相",
        "EQTransformer深度学习震相",
        "QuakeMigrate地震成像",
        "Qseek地震成像",
        "SAIPy震相与震级",
        "ObsPy地震数据格式转换",
        "Pooch与Verde数据网格化",
        "Boule标准重力与正常位",
        "Harmonica布格与区域改正",
        "Harmonica重磁正演",
        "pyGIMLi地球物理反演",
        "SimPEG地球物理反演",
        "pyGMI重磁集成处理",
        "PyGMT重磁成果制图",
        "Pymaginverse卫星磁反演",
        "MasconCubes卫星磁反演",
        "PyGMI大地电磁一维反演",
        "PyGMT专业地学制图",
        "CIGVis地震测井可视化",
        "GemPy三维地质建模",
        "GSTool模型不确定性分析",
    ],
    "OceanPhysicsTools": OCEAN_PHYSICS_TOOL_NAMES,
    "GISTools": GIS_TOOL_NAMES,
    "MeteorologyTools": METEOROLOGY_TOOL_NAMES,
}

# GeoToolEval tools are maintained in one catalog shared by the runtime and KG
# builder. Legacy categories above remain available for backward compatibility.
from ToolsFuns.GeoEval.catalog import TOOLS_MAPPING as GEOEVAL_TOOLS_MAPPING

TOOLS_MAPPING.update(GEOEVAL_TOOLS_MAPPING)
