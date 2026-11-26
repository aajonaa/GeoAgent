# Copyright (c) J. Schellekens 2005-2011
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from numba import jit
import math

@jit(nopython=True)
def kinematic_wave(Qin, Qold, q, alpha, beta, deltaT, deltaX):

    epsilon = 1e-12
    MAX_ITERS = 3000

    if (Qin + Qold + q) == 0.0:
        return 0.0
    else:
        # common terms
        ab_pQ = alpha * beta * pow(((Qold + Qin) / 2.0), beta - 1.0)
        deltaTX = deltaT / deltaX
        C = deltaTX * Qin + alpha * pow(Qold, beta) + deltaT * q

        Qkx = (deltaTX * Qin + Qold * ab_pQ + deltaT * q) / (deltaTX + ab_pQ)

        if math.isnan(Qkx):
            Qkx = 0.0

        Qkx = max(Qkx, 1e-30)
        fQkx = deltaTX * Qkx + alpha * pow(Qkx, beta) - C
        dfQkx = deltaTX + alpha * beta * pow(Qkx, beta - 1.0)
        Qkx = Qkx - fQkx / dfQkx
        Qkx = max(Qkx, 1e-30)
        count = 0

        while abs(fQkx) > epsilon and count < MAX_ITERS:
            fQkx = deltaTX * Qkx + alpha * pow(Qkx, beta) - C
            dfQkx = deltaTX + alpha * beta * pow(Qkx, beta - 1.0)
            Qkx = Qkx - fQkx / dfQkx
            Qkx = max(Qkx, 1e-30)
            count = count + 1

        return Qkx
