# Original PyOWM kernel. MIT license retained in originals/126.

def metric_wind_dict_to_beaufort(d):
    """
    Converts all the wind values in a dict from meters/sec
    to the corresponding Beaufort scale level (which is not an exact number but rather
    represents a range of wind speeds - see: https://en.wikipedia.org/wiki/Beaufort_scale).
    Conversion table: https://www.windfinder.com/wind/windspeed.htm

    :param d: the dictionary containing metric values
    :type d: dict
    :returns: a dict with the same keys as the input dict and values converted
        to Beaufort level

    """
    result = {}
    for key, value in d.items():
        if key != 'deg':  # do not convert wind degree
            if value <= 0.2:
                bf = 0
            elif 0.2 < value <= 1.5:
                bf = 1
            elif 1.5 < value <= 3.3:
                bf = 2
            elif 3.3 < value <= 5.4:
                bf = 3
            elif 5.4 < value <= 7.9:
                bf = 4
            elif 7.9 < value <= 10.7:
                bf = 5
            elif 10.7 < value <= 13.8:
                bf = 6
            elif 13.8 < value <= 17.1:
                bf = 7
            elif 17.1 < value <= 20.7:
                bf = 8
            elif 20.7 < value <= 24.4:
                bf = 9
            elif 24.4 < value <= 28.4:
                bf = 10
            elif 28.4 < value <= 32.6:
                bf = 11
            else:
                bf = 12
            result[key] = bf
        else:
            result[key] = value
    return result
