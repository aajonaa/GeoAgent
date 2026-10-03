"""GIS tools added in the SciToolAgent tool-function style."""

from __future__ import annotations

from ToolsFuns.utils.workflow_tool_runtime import (
    WorkflowToolSpec,
    build_kg_rows,
    run_workflow_tool,
    tool_names,
)


GIS_CATEGORY = "GISTools"
GIS_SOURCE = "PPT: 工具(1).pptx / 地理信息系统; ToolsAgent/ToolsFuns/GIS/gis_tools.py"


GIS_SPECS: list[WorkflowToolSpec] = [
    {
        "name": "多源空间数据格式转换与标准化",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-数据转换",
        "function": "将 SHP、GeoJSON、TIFF、NetCDF 等多源空间数据统一为标准格式与投影。",
        "workflow": "数据读取 -> 格式识别 -> 坐标系读取 -> 投影转换 -> 格式转换 -> 结果输出",
        "common_tools": ["GDAL/OGR", "GeoPandas", "Rasterio", "PyProj", "QGIS"],
        "import_modules": ["osgeo", "geopandas", "rasterio", "pyproj"],
        "input": "空间数据路径,目标格式,目标投影",
        "output": "标准化空间数据,统一投影空间数据",
        "source": GIS_SOURCE,
        "next_tools": ["矢量数据质量控制与拓扑修复", "栅格数据预处理", "矢量数据批量处理"],
    },
    {
        "name": "矢量数据质量控制与拓扑修复",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-质量控制",
        "function": "检测并修复自相交、重叠、缝隙、悬挂节点等矢量拓扑错误。",
        "workflow": "矢量读取 -> 拓扑错误检测 -> 错误分类 -> 批量修复 -> 结果验证 -> 输出",
        "common_tools": ["GeoPandas", "Shapely", "WhiteboxTools", "QGIS拓扑检查器"],
        "import_modules": ["geopandas", "shapely", "whitebox"],
        "input": "统一投影空间数据,拓扑检查规则",
        "output": "修复矢量数据,拓扑报告",
        "source": GIS_SOURCE,
        "next_tools": ["空间叠加分析", "缓冲区分析与空间邻近计算", "空间距离与邻近分析", "栅格分区统计"],
    },
    {
        "name": "栅格数据预处理",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-栅格预处理",
        "function": "统一 DEM 和遥感影像的空间范围、坐标系与分辨率，完成裁剪、重投影和重采样。",
        "workflow": "栅格读取 -> 研究区裁剪 -> 重投影 -> 分辨率重采样 -> 标准化输出",
        "common_tools": ["Rasterio", "GDAL", "xarray", "WhiteboxTools"],
        "import_modules": ["rasterio", "osgeo", "xarray", "whitebox"],
        "input": "空间数据路径,研究区边界,目标投影,目标分辨率",
        "output": "预处理栅格数据,统一投影空间数据",
        "source": GIS_SOURCE,
        "next_tools": ["地形参数提取与水文分析", "栅格代数运算", "栅格分区统计"],
    },
    {
        "name": "地形参数提取与水文分析",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-地形水文",
        "function": "基于 DEM 计算坡度、坡向、曲率，提取流域、河网和汇流累积量。",
        "workflow": "DEM读取 -> 填洼 -> 流向计算 -> 汇流累积量 -> 地形参数 -> 河网/流域提取",
        "common_tools": ["GDAL", "Rasterio", "WhiteboxTools", "PyGMT"],
        "import_modules": ["osgeo", "rasterio", "whitebox", "pygmt"],
        "input": "预处理栅格数据,水文分析参数",
        "output": "地形参数栅格,水文分析结果",
        "source": GIS_SOURCE,
        "next_tools": ["自动化专题地图制图"],
    },
    {
        "name": "空间叠加分析",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-空间分析",
        "function": "对多图层矢量执行交集、并集、差集和联合计算，分析空间关联关系。",
        "workflow": "多图层读取 -> 投影统一 -> 叠加运算 -> 属性合并 -> 结果输出",
        "common_tools": ["GeoPandas", "Shapely", "PySAL"],
        "import_modules": ["geopandas", "shapely", "libpysal|pysal"],
        "input": "修复矢量数据,统一投影空间数据,叠加运算类型",
        "output": "空间叠加结果图层",
        "source": GIS_SOURCE,
        "next_tools": ["自动化专题地图制图", "栅格分区统计"],
    },
    {
        "name": "缓冲区分析与空间邻近计算",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-空间分析",
        "function": "对点、线、面生成指定距离缓冲区，用于影响范围和风险区分析。",
        "workflow": "数据读取 -> 平面投影 -> 缓冲区生成 -> 合并去重 -> 结果输出",
        "common_tools": ["GeoPandas", "Shapely"],
        "import_modules": ["geopandas", "shapely"],
        "input": "修复矢量数据,缓冲距离,距离单位",
        "output": "缓冲区图层,邻近分析摘要",
        "source": GIS_SOURCE,
        "next_tools": ["自动化专题地图制图", "空间叠加分析"],
    },
    {
        "name": "空间插值",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-空间插值",
        "function": "将离散站点数据通过 IDW、克里金或样条方法转换为连续栅格面。",
        "workflow": "点数据读取 -> 投影转换 -> 插值方法选择 -> 网格生成 -> 栅格输出",
        "common_tools": ["SciPy", "PyKrige", "Rasterio", "GeoPandas"],
        "import_modules": ["scipy", "pykrige", "rasterio", "geopandas"],
        "input": "点数据路径,插值字段,插值方法,网格参数",
        "output": "空间插值栅格,预处理栅格数据",
        "source": GIS_SOURCE,
        "next_tools": ["栅格代数运算", "栅格分区统计", "自动化专题地图制图"],
    },
    {
        "name": "自动化专题地图制图",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-地图制图",
        "function": "自动生成带图例、比例尺、指北针和标准符号的专题地图。",
        "workflow": "数据读取 -> 投影统一 -> 样式配置 -> 元素添加 -> 图片导出",
        "common_tools": ["Matplotlib", "Folium", "PyGMT", "Cartopy"],
        "import_modules": ["matplotlib", "folium", "pygmt", "cartopy"],
        "input": "空间叠加结果图层,缓冲区图层,地形参数栅格,地图样式",
        "output": "专题地图图片,HTML地图",
        "source": GIS_SOURCE,
        "next_tools": [],
    },
    {
        "name": "栅格分区统计",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-栅格统计",
        "function": "按矢量边界计算栅格均值、最大值、最小值、总和等分区统计量。",
        "workflow": "栅格读取 -> 分区矢量读取 -> 分区统计 -> 属性关联 -> 结果输出",
        "common_tools": ["Rasterio", "xarray", "GeoPandas", "WhiteboxTools"],
        "import_modules": ["rasterio", "xarray", "geopandas", "whitebox"],
        "input": "预处理栅格数据,修复矢量数据,统计字段",
        "output": "分区统计表,关联图层",
        "source": GIS_SOURCE,
        "next_tools": ["自动化专题地图制图"],
    },
    {
        "name": "矢量数据批量处理",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-批处理",
        "function": "批量完成矢量数据重投影、裁剪、属性更新和格式转换。",
        "workflow": "批量读取 -> 批量投影 -> 批量裁剪 -> 批量更新 -> 批量输出",
        "common_tools": ["GeoPandas", "GDAL/OGR", "Python"],
        "import_modules": ["geopandas", "osgeo"],
        "input": "矢量文件目录,批处理规则,输出目录",
        "output": "统一投影空间数据,批处理矢量数据集",
        "source": GIS_SOURCE,
        "next_tools": ["矢量数据质量控制与拓扑修复", "空间叠加分析"],
    },
    {
        "name": "空间距离与邻近分析",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-邻近分析",
        "function": "计算点要素间距离、最近设施和邻近要素检索结果。",
        "workflow": "数据读取 -> 投影转换 -> 距离计算 -> 邻近筛选 -> 结果输出",
        "common_tools": ["GeoPandas", "Shapely", "PySAL"],
        "import_modules": ["geopandas", "shapely", "libpysal|pysal"],
        "input": "修复矢量数据,邻近半径,最近邻数量",
        "output": "距离矩阵,邻近要素结果",
        "source": GIS_SOURCE,
        "next_tools": ["自动化专题地图制图"],
    },
    {
        "name": "栅格代数运算",
        "category": GIS_CATEGORY,
        "problem_type": "地理信息系统-栅格计算",
        "function": "执行栅格加减乘除、归一化、阈值分割和掩膜运算。",
        "workflow": "栅格读取 -> 代数运算 -> 阈值处理 -> 掩膜生成 -> 结果输出",
        "common_tools": ["Rasterio", "GDAL", "xarray", "NumPy"],
        "import_modules": ["rasterio", "osgeo", "xarray", "numpy"],
        "input": "预处理栅格数据,代数表达式,掩膜规则",
        "output": "栅格代数结果,预处理栅格数据",
        "source": GIS_SOURCE,
        "next_tools": ["地形参数提取与水文分析", "栅格分区统计", "自动化专题地图制图"],
    },
]


_GIS_SPEC_BY_NAME = {spec["name"]: spec for spec in GIS_SPECS}


def _run_gis_tool(tool_name: str, input_text: str) -> str:
    return run_workflow_tool(_GIS_SPEC_BY_NAME[tool_name], input_text)


def multi_source_spatial_data_standardization(input_text: str) -> str:
    return _run_gis_tool("多源空间数据格式转换与标准化", input_text)


def vector_topology_quality_repair(input_text: str) -> str:
    return _run_gis_tool("矢量数据质量控制与拓扑修复", input_text)


def raster_data_preprocessing(input_text: str) -> str:
    return _run_gis_tool("栅格数据预处理", input_text)


def terrain_hydrology_analysis(input_text: str) -> str:
    return _run_gis_tool("地形参数提取与水文分析", input_text)


def spatial_overlay_analysis(input_text: str) -> str:
    return _run_gis_tool("空间叠加分析", input_text)


def buffer_and_proximity_analysis(input_text: str) -> str:
    return _run_gis_tool("缓冲区分析与空间邻近计算", input_text)


def spatial_interpolation(input_text: str) -> str:
    return _run_gis_tool("空间插值", input_text)


def thematic_map_automation(input_text: str) -> str:
    return _run_gis_tool("自动化专题地图制图", input_text)


def raster_zonal_statistics(input_text: str) -> str:
    return _run_gis_tool("栅格分区统计", input_text)


def vector_batch_processing(input_text: str) -> str:
    return _run_gis_tool("矢量数据批量处理", input_text)


def spatial_distance_proximity_analysis(input_text: str) -> str:
    return _run_gis_tool("空间距离与邻近分析", input_text)


def raster_algebra(input_text: str) -> str:
    return _run_gis_tool("栅格代数运算", input_text)


GIS_TOOL_NAMES = tool_names(GIS_SPECS)
GIS_KG_ROWS = build_kg_rows(GIS_SPECS)
