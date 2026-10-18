"""Stock-to-flow arithmetic (ACC-01, ACC-02)."""

import numpy as np

FX_MOVEMENT = 0.0  # EUR only: FX movements are zero by scope (ACC-02, AT-21)


def charge(opening, closing):
    """Impairment charge = closing allowance - opening allowance; the stock is never expensed
    again (ACC-01, AT-07)."""
    return np.asarray(closing, dtype=float) - np.asarray(opening, dtype=float)
