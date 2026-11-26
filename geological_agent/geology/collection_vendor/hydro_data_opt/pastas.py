# Integration scaffold around unchanged upstream source excerpts.
from __future__ import annotations
import numpy as np
class Exponential:
    @staticmethod
    def impulse(t: ArrayLike, p: ArrayLike) -> ArrayLike:
        """Return the impulse response function for Exponential.

        Parameters
        ----------
        t : array_like
            Time array in days.
        p : array_like
            Response function parameters [A, a].

        Returns
        -------
        impulse : array_like
            Impulse response at times t.
        """
        A, a = p
        return A / a * np.exp(-t / a)


