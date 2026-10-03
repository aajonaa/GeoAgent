from ToolsFuns.GIS.gis_tools import (
    buffer_and_proximity_analysis,
    multi_source_spatial_data_standardization,
    raster_algebra,
    raster_data_preprocessing,
    raster_zonal_statistics,
    spatial_distance_proximity_analysis,
    spatial_interpolation,
    spatial_overlay_analysis,
    terrain_hydrology_analysis,
    thematic_map_automation,
    vector_batch_processing,
    vector_topology_quality_repair,
)


GIS_TOOLS_DICT = {
    "多源空间数据格式转换与标准化": multi_source_spatial_data_standardization,
    "矢量数据质量控制与拓扑修复": vector_topology_quality_repair,
    "栅格数据预处理": raster_data_preprocessing,
    "地形参数提取与水文分析": terrain_hydrology_analysis,
    "空间叠加分析": spatial_overlay_analysis,
    "缓冲区分析与空间邻近计算": buffer_and_proximity_analysis,
    "空间插值": spatial_interpolation,
    "自动化专题地图制图": thematic_map_automation,
    "栅格分区统计": raster_zonal_statistics,
    "矢量数据批量处理": vector_batch_processing,
    "空间距离与邻近分析": spatial_distance_proximity_analysis,
    "栅格代数运算": raster_algebra,
}
