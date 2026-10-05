"""Synthetic hand landmarks for gesture tests (upright hand, wrist at bottom)."""
import numpy as np


def make_hand(extended=(True, True, True, True), pinch=False, wrist=(0.5, 0.8), tilt_x=0.0):
    lm = np.zeros((21, 3))
    wx, wy = wrist
    lm[0] = (wx, wy, 0)
    mcp_x = {5: -0.045, 9: -0.015, 13: 0.015, 17: 0.045}
    tips = {5: 8, 9: 12, 13: 16, 17: 20}
    for (mcp, tip), ext in zip(tips.items(), extended):
        lm[mcp] = (wx + mcp_x[mcp] + tilt_x, wy - 0.12, 0)
        length = 0.12 if ext else -0.02          # curled: tip folds back toward the palm
        lm[tip] = (wx + mcp_x[mcp] + tilt_x, wy - 0.12 - length, 0)
        lm[tip - 1] = (lm[tip][0], (lm[mcp][1] + lm[tip][1]) / 2, 0)
    lm[1] = (wx - 0.04, wy - 0.03, 0)
    lm[2] = (wx - 0.07, wy - 0.06, 0)
    lm[3] = (wx - 0.09, wy - 0.09, 0)
    lm[4] = (wx - 0.12, wy - 0.12, 0)
    if pinch:
        lm[4] = lm[8] + np.array([-0.005, 0.005, 0])
    return lm
