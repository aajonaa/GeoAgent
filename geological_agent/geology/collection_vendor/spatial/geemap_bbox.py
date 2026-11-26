from typing import Sequence, Any


def bbox_to_geojson(bounds: Sequence[float]) -> dict[str, Any]:
    """Convert coordinates of a bounding box to a geojson.

    Args:
        bounds: A list of coordinates representing [left, bottom, right, top].

    Returns:
        A geojson feature.
    """
    return {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [bounds[0], bounds[3]],
                    [bounds[0], bounds[1]],
                    [bounds[2], bounds[1]],
                    [bounds[2], bounds[3]],
                    [bounds[0], bounds[3]],
                ]
            ],
        },
        "type": "Feature",
    }

