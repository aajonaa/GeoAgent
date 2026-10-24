# Original EarthSim method. BSD-3-Clause notice in originals/26.
import numpy as np

class LineCrossSectionKernel:

    def _gen_samples(self, geom):
        """
        Interpolates a LineString geometry to the defined
        resolution. Returning the x- and y-coordinates along
        with the distance along the path.
        """
        xs, ys, distance = [], [], []
        dist = geom.length
        for d in np.linspace(0, dist, int(dist/self.resolution)):
            point = geom.interpolate(d)
            xs.append(point.x)
            ys.append(point.y)
            distance.append(d)
        return xs, ys, distance
