# Integration scaffold around unchanged upstream source excerpts.
import numpy as np
def R(Z):
    return np.power(Z / 200., 0.625)


class Rain(object):
    """ Do calculations from dBZ to rain """
    def __init__(self, dBZ):
        self._dBZ = dBZ.copy()

    def _clip_hail(self):
        self._dBZ[np.greater(self._dBZ, 55)] = 55

    def _make_Z(self):
        self._Z = np.power(10, self._dBZ / 10)

    def _remove_noise(self):
        self._Z[np.less(self._dBZ, 7)] = 0

    def get(self):
        self._clip_hail()
        self._make_Z()
        self._remove_noise()
        return R(self._Z)


