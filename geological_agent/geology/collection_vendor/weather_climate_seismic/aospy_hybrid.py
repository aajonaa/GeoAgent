# Adaptation: isolated upstream function bodies with import/class glue added.
# Copyright aospy contributors; Apache-2.0
# Original algorithms unchanged; full upstream license in licenses/.

def phalf_from_ps(bk, pk, ps):
    """Compute pressure of half levels of hybrid sigma-pressure coordinates."""
    return ps*bk + pk


