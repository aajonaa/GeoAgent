# Integration scaffold around unchanged upstream source excerpts.
import numpy as np
class ExpVario:
    def _h_function(self, h):
        """private method exponential variogram "h" function"""
        return self.contribution * np.exp(-1.0 * h / self.a)


