"""Constant-velocity Kalman filter on (cx, cy, aspect, height), as used by ByteTrack.

Zhang et al. (2022), "ByteTrack: Multi-Object Tracking by Associating Every
Detection Box", ECCV. Noise weights follow the reference implementation.
"""

from __future__ import annotations

import numpy as np

_STD_POS = 1.0 / 20
_STD_VEL = 1.0 / 160


class KalmanXYAH:
    def __init__(self) -> None:
        self.F = np.eye(8)
        self.F[:4, 4:] = np.eye(4)
        self.H = np.eye(4, 8)

    def initiate(self, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean = np.r_[z, np.zeros(4)]
        h = z[3]
        std = [2 * _STD_POS * h, 2 * _STD_POS * h, 1e-2, 2 * _STD_POS * h,
               10 * _STD_VEL * h, 10 * _STD_VEL * h, 1e-5, 10 * _STD_VEL * h]
        return mean, np.diag(np.square(std))

    def predict(self, mean: np.ndarray, cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h = mean[3]
        q = np.diag(np.square([_STD_POS * h, _STD_POS * h, 1e-2, _STD_POS * h,
                               _STD_VEL * h, _STD_VEL * h, 1e-5, _STD_VEL * h]))
        return self.F @ mean, self.F @ cov @ self.F.T + q

    def update(self, mean: np.ndarray, cov: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h = mean[3]
        r = np.diag(np.square([_STD_POS * h, _STD_POS * h, 1e-1, _STD_POS * h]))
        s = self.H @ cov @ self.H.T + r
        k = np.linalg.solve(s, (cov @ self.H.T).T).T
        return mean + k @ (z - self.H @ mean), cov - k @ s @ k.T


def xyxy_to_xyah(b: np.ndarray) -> np.ndarray:
    w, h = b[2] - b[0], b[3] - b[1]
    return np.array([b[0] + w / 2, b[1] + h / 2, w / max(h, 1e-6), h])


def xyah_to_xyxy(m: np.ndarray) -> np.ndarray:
    cx, cy, a, h = m[:4]
    w = a * h
    return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
