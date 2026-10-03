from ToolsFuns.Meteorology.meteorology_tools import (
    meteorological_derived_quantity_calculation,
    meteorological_spatial_mapping,
    meteorological_spatiotemporal_interpolation,
    meteorological_time_series_statistics,
    meteorological_vertical_profile_analysis,
    meteorology_batch_format_conversion,
    meteorology_data_quality_control,
    meteorology_data_read_decode,
    meteorology_station_spatial_visualization,
    numerical_model_post_processing,
    precipitation_extreme_event_detection,
    wind_field_analysis_visualization,
)


METEOROLOGY_TOOLS_DICT = {
    "气象数据读取与格式解码": meteorology_data_read_decode,
    "气象数据质量控制": meteorology_data_quality_control,
    "气象要素时空插值": meteorological_spatiotemporal_interpolation,
    "气象时间序列统计分析": meteorological_time_series_statistics,
    "气象要素空间制图": meteorological_spatial_mapping,
    "风场分析与可视化": wind_field_analysis_visualization,
    "气象垂直剖面分析": meteorological_vertical_profile_analysis,
    "数值模式数据后处理": numerical_model_post_processing,
    "降水数据处理与极端事件识别": precipitation_extreme_event_detection,
    "气象数据批量格式转换": meteorology_batch_format_conversion,
    "气象衍生量计算": meteorological_derived_quantity_calculation,
    "气象站点数据空间可视化": meteorology_station_spatial_visualization,
}
