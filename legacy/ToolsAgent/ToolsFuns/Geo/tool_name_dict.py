from .geoscienceTools import (
    clean_and_classify_earthquake_data,
    usgs_earthquake_data_fetch,
    visualize_earthquake_event_map,
)

GEO_TOOLS_DICT = {
    "USGS 地震数据获取": usgs_earthquake_data_fetch,
    "地震数据清洗与分级": clean_and_classify_earthquake_data,
    "地震事件地图可视化": visualize_earthquake_event_map,
}
