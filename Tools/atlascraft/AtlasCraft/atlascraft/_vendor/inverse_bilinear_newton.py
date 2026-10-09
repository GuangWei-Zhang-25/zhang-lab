"""Damped Newton inverse of a shared piecewise-bilinear partial warp.

The field is [2,H,W] in Y,X coordinates. This solves x+w*flow(x)=target
using exact within-cell derivatives, a bounded Newton step, and independent
per-point residual-decreasing line search. It does not repair a folded field.
"""
import numpy as np


def evaluate(field, coordinate, derivatives=False):
    h, w = field.shape[1:]
    y, x = coordinate
    y0 = np.clip(np.floor(y).astype(np.int64), 0, h - 2)
    x0 = np.clip(np.floor(x).astype(np.int64), 0, w - 2)
    fy, fx = np.clip(y - y0, 0, 1), np.clip(x - x0, 0, 1)
    a, b = field[:, y0, x0], field[:, y0 + 1, x0]
    c, d = field[:, y0, x0 + 1], field[:, y0 + 1, x0 + 1]
    value = ((1 - fy) * (1 - fx) * a + fy * (1 - fx) * b +
             (1 - fy) * fx * c + fy * fx * d)
    if not derivatives:
        return value
    derivative_y = (1 - fx) * (b - a) + fx * (d - c)
    derivative_x = (1 - fy) * (c - a) + fy * (d - b)
    return value, derivative_y, derivative_x


def inverse_partial(flow, weight, iterations=80, tolerance=1e-4, return_details=False):
    flow = np.asarray(flow, dtype=np.float64)
    if flow.ndim != 3 or flow.shape[0] != 2 or min(flow.shape[1:]) < 2:
        raise ValueError('Expected finite flow[2,H,W] with H,W>=2.')
    if not np.isfinite(flow).all() or not 0 <= weight <= 1:
        raise ValueError('Invalid flow or partial weight.')
    h, w = flow.shape[1:]
    target = np.mgrid[:h, :w].reshape(2, -1).astype(np.float64)
    coordinate = target.copy()
    squared_tolerance = tolerance * tolerance
    total_backtracks = 0
    for iteration in range(iterations):
        value = evaluate(flow, coordinate)
        residual = coordinate + weight * value - target
        squared = np.sum(residual * residual, axis=0)
        active = np.flatnonzero(squared > squared_tolerance)
        if not len(active):
            break
        point = coordinate[:, active]
        _, dy, dx = evaluate(flow, point, True)
        j00, j01 = 1 + weight * dy[0], weight * dx[0]
        j10, j11 = weight * dy[1], 1 + weight * dx[1]
        determinant = j00 * j11 - j01 * j10
        if np.any(determinant <= 0):
            raise RuntimeError('Inverse requested for a folded/nonpositive-Jacobian sampling cell.')
        ry, rx = residual[:, active]
        step = np.stack([(j11 * ry - j01 * rx) / determinant,
                         (j00 * rx - j10 * ry) / determinant])
        step /= np.maximum(1, np.hypot(*step) / 8)
        pending = np.arange(len(active))
        alpha = np.ones(len(active), dtype=np.float64)
        for _ in range(16):
            if not len(pending):
                break
            candidate = point[:, pending] - step[:, pending] * alpha[pending]
            candidate[0] = np.clip(candidate[0], 0, h - 1)
            candidate[1] = np.clip(candidate[1], 0, w - 1)
            rr = candidate + weight * evaluate(flow, candidate) - target[:, active[pending]]
            new_squared = np.sum(rr * rr, axis=0)
            old_squared = squared[active[pending]]
            accepted = (new_squared < old_squared * (1 - 1e-5 * alpha[pending])) | (new_squared <= squared_tolerance)
            coordinate[:, active[pending[accepted]]] = candidate[:, accepted]
            pending = pending[~accepted]
            alpha[pending] *= .5
            total_backtracks += len(pending)
        if len(pending):
            raise RuntimeError(f'Newton inverse line search failed at {len(pending)} points; field needs review.')
    residual = coordinate + weight * evaluate(flow, coordinate) - target
    maximum = float(np.hypot(*residual).max())
    if maximum > tolerance * 1.01:
        raise RuntimeError(f'Newton inverse did not converge: {maximum:g}px at weight={weight:g}.')
    coordinate = coordinate.reshape(2, h, w)
    if return_details:
        return coordinate, maximum, {'iterations': iteration + 1,
                                    'perPointBacktrackingSteps': total_backtracks,
                                    'maximumResidualPixels': maximum,
                                    'method': 'Exact bilinear 2x2 Jacobian, bounded Newton step, per-point residual-decreasing line search.'}
    return coordinate, maximum
