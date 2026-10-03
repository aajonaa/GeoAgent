from ToolsFuns.OceanPhysics.ocean_physics_tools import (
    argo_float_profile_data_fetch,
    argo_profile_qc_flag_filter,
    ctd_temperature_salinity_depth_parse,
    duplicate_ocean_profile_detection,
    hycom_ocean_model_data_fetch,
    satellite_altimeter_sea_surface_height_fetch,
    satellite_sea_surface_temperature_fetch,
    temperature_salinity_depth_outlier_qc,
)


OCEANPHYSICS_TOOLS_DICT = {
    "Argo浮标温盐剖面数据获取": argo_float_profile_data_fetch,
    "科考船CTD温盐深数据解析": ctd_temperature_salinity_depth_parse,
    "卫星高度计海面高度数据获取": satellite_altimeter_sea_surface_height_fetch,
    "卫星海表温度数据获取": satellite_sea_surface_temperature_fetch,
    "HYCOM全球海洋模式数据获取": hycom_ocean_model_data_fetch,
    "温盐深数据异常值检测与剔除": temperature_salinity_depth_outlier_qc,
    "Argo浮标剖面质控标记筛选": argo_profile_qc_flag_filter,
    "重复海洋剖面数据检测与去重": duplicate_ocean_profile_detection,
}
