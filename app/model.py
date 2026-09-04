from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from scipy.ndimage import gaussian_filter

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_FILE = DATA_DIR / "spatial_maps.npz"

# Scientific structure explicitly provided for the web-app.
TRAIT_SD = 1.0

# Visualization / simulator defaults. All listed model parameters are user-editable in the UI.
DEFAULTS = {
    "D": 500.0,         # spatial Gaussian variance in km^2
    "beta0": 5e-8,
    "beta1": 2e-8,
    "b0": 0.5,
    "d0": 0.3,
    "max_chain_length": 50,
    "optimum": 1.0,
    "duration": 50.0,   # model-time units
    "frames": 181,
    "seed": 2030,
}

MAX_SEEDS = 1000
MAX_BRANCH_EVENTS_PER_CLUSTER = 250_000
MAX_CLUSTER_ACTIVE = 200_000


@dataclass(frozen=True)
class MapData:
    Ks: np.ndarray
    Kr: np.ndarray
    alpha: np.ndarray
    mask: np.ndarray
    lons: np.ndarray
    lats: np.ndarray
    viridis: np.ndarray
    dx_deg: float
    dy_deg: float
    cell_area_km2: float


@lru_cache(maxsize=1)
def load_maps() -> MapData:
    z = np.load(DATA_FILE)
    Ks = z["Ks"].astype(np.float64)
    Kr = z["Kr"].astype(np.float64)
    alpha = z["alpha"].astype(np.float64)
    mask = z["mask"].astype(bool)
    lons = z["lons"].astype(np.float64)
    lats = z["lats"].astype(np.float64)
    viridis = z["viridis"].astype(np.float64)

    dx = float(np.mean(np.diff(lons)))
    dy = float(np.mean(np.diff(lats)))
    mean_lat = float(np.mean(lats))
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * np.cos(np.deg2rad(mean_lat))
    cell_area = abs(dx * km_per_deg_lon * dy * km_per_deg_lat)

    return MapData(Ks, Kr, alpha, mask, lons, lats, viridis, dx, dy, cell_area)


def convolved_reservoir(D: float, maps: MapData | None = None) -> np.ndarray:
    """Compute J_D * K_r, extending K_r by zero outside the map support."""
    maps = maps or load_maps()
    kr0 = np.where(maps.mask, np.nan_to_num(maps.Kr, nan=0.0), 0.0)
    if D <= 0:
        out = kr0.copy()
    else:
        sd_km = float(np.sqrt(D))
        mean_lat = float(np.mean(maps.lats))
        km_per_deg_lat = 111.32
        km_per_deg_lon = 111.32 * np.cos(np.deg2rad(mean_lat))
        cell_y_km = abs(maps.dy_deg) * km_per_deg_lat
        cell_x_km = abs(maps.dx_deg) * km_per_deg_lon
        sigma_y = sd_km / cell_y_km
        sigma_x = sd_km / cell_x_km
        out = gaussian_filter(kr0, sigma=(sigma_y, sigma_x), mode="constant", cval=0.0)
    out[~maps.mask] = np.nan
    return out


def spatial_intensity(D: float, beta0: float, beta1: float, maps: MapData | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return intensity density per km^2 per model-time and the convolved reservoir map.

    Integrating over theta removes G(theta), because G is a standard Gaussian density.
    """
    maps = maps or load_maps()
    conv = convolved_reservoir(D, maps)
    contact = beta0 + beta1 * maps.alpha
    density = contact * maps.Ks * conv
    density = np.where(maps.mask, np.maximum(density, 0.0), np.nan)
    return density, conv


def trait_death_rate(theta: float, optimum: float, d0: float = DEFAULTS["d0"]) -> float:
    return d0 + (theta - optimum) ** 2


def _branch_trajectory(
    rng: np.random.Generator,
    arrival: float,
    theta: float,
    optimum: float,
    b0: float,
    d0: float,
    max_chain_length: int,
    frame_times: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Exact Gillespie simulation of a linear birth-death transmission process from one primary infection."""
    birth = b0
    death = trait_death_rate(theta, optimum, d0)

    event_times = [arrival]
    active_values = [1]
    cumulative_values = [1]

    t = arrival
    active = 1
    cumulative = 1
    n_events = 0
    capped = False

    # A value of 0 means no onward transmission: the spillover case can still be removed.
    # For positive values, max_chain_length is the maximum number of people ever infected
    # in this local chain, including the primary spillover case.
    max_cases = 1 if max_chain_length <= 0 else max_chain_length

    while t < frame_times[-1] and active > 0:
        births_allowed = cumulative < max_cases
        birth_rate = active * birth if births_allowed else 0.0
        death_rate = active * death
        total_rate = birth_rate + death_rate
        if total_rate <= 0:
            break
        t_next = t + float(rng.exponential(1.0 / total_rate))
        if t_next > frame_times[-1]:
            break
        if birth_rate > 0 and rng.random() < birth_rate / total_rate:
            active += 1
            cumulative += 1
        else:
            active -= 1
        t = t_next
        event_times.append(t)
        active_values.append(active)
        cumulative_values.append(cumulative)
        n_events += 1
        if n_events >= MAX_BRANCH_EVENTS_PER_CLUSTER or active >= MAX_CLUSTER_ACTIVE:
            capped = True
            break

    event_times_arr = np.asarray(event_times, dtype=float)
    active_arr = np.asarray(active_values, dtype=np.int32)
    cumulative_arr = np.asarray(cumulative_values, dtype=np.int32)

    # Value after the latest event at each frame; zero before spillover arrival.
    idx = np.searchsorted(event_times_arr, frame_times, side="right") - 1
    before = frame_times < arrival
    idx = np.clip(idx, 0, len(event_times_arr) - 1)
    frame_active = active_arr[idx].copy()
    frame_cumulative = cumulative_arr[idx].copy()
    frame_active[before] = 0
    frame_cumulative[before] = 0
    return frame_active, frame_cumulative, capped


def simulate(
    D: float,
    beta0: float,
    beta1: float,
    b0: float,
    d0: float,
    optimum: float,
    duration: float,
    frames: int,
    seed: int,
    max_chain_length: int = DEFAULTS["max_chain_length"],
) -> dict[str, Any]:
    if max_chain_length < 0 or max_chain_length > 500:
        raise ValueError("Max length of transmission chains must be between 0 and 500.")

    maps = load_maps()
    density, conv = spatial_intensity(D, beta0, beta1, maps)

    cell_rates = np.nan_to_num(density, nan=0.0) * maps.cell_area_km2
    total_rate = float(cell_rates.sum())
    expected_seeds = total_rate * duration

    if not np.isfinite(expected_seeds):
        raise ValueError("The selected parameters produce a non-finite Poisson intensity.")
    if expected_seeds > 5_000:
        raise ValueError(
            f"Expected spillovers ({expected_seeds:.0f}) are too large for an interactive animation. "
            "Reduce beta0, beta1, or the duration."
        )

    rng = np.random.default_rng(seed)
    n_seeds = int(rng.poisson(expected_seeds))
    if n_seeds > MAX_SEEDS:
        raise ValueError(
            f"This random draw contains {n_seeds} spillovers; the interactive limit is {MAX_SEEDS}. "
            "Reduce beta0, beta1, or the duration."
        )

    frame_times = np.linspace(0.0, duration, frames, dtype=float)
    warnings: list[str] = []

    flat_rates = cell_rates.ravel()
    if n_seeds and total_rate > 0:
        probs = flat_rates / total_rate
        chosen = rng.choice(flat_rates.size, size=n_seeds, replace=True, p=probs)
        iy, ix = np.unravel_index(chosen, cell_rates.shape)
        arrivals = np.sort(rng.uniform(0.0, duration, size=n_seeds))
        thetas = rng.normal(0.0, TRAIT_SD, size=n_seeds)
    else:
        iy = np.array([], dtype=int)
        ix = np.array([], dtype=int)
        arrivals = np.array([], dtype=float)
        thetas = np.array([], dtype=float)

    clusters: list[dict[str, Any]] = []
    total_active = np.zeros(frames, dtype=np.int64)
    total_reached = np.zeros(frames, dtype=np.int64)
    active_clusters = np.zeros(frames, dtype=np.int32)

    for k in range(n_seeds):
        # Uniform jitter inside the selected grid cell.
        lon = float(maps.lons[ix[k]] + rng.uniform(-0.5, 0.5) * maps.dx_deg)
        lat = float(maps.lats[iy[k]] + rng.uniform(-0.5, 0.5) * maps.dy_deg)
        theta = float(thetas[k])
        arrival = float(arrivals[k])
        death = trait_death_rate(theta, optimum, d0)
        active, reached, capped = _branch_trajectory(rng, arrival, theta, optimum, b0, d0, max_chain_length, frame_times)
        if capped:
            warnings.append(
                "At least one transmission chain hit the safety cap; its later trajectory is held at the capped state."
            )
        total_active += active
        total_reached += reached
        active_clusters += (active > 0).astype(np.int32)
        clusters.append(
            {
                "id": k + 1,
                "lon": round(lon, 5),
                "lat": round(lat, 5),
                "arrival": round(arrival, 5),
                "theta": round(theta, 5),
                "birth_rate": b0,
                "death_rate": round(death, 5),
                "net_growth": round(b0 - death, 5),
                "supercritical": bool(b0 > death),
                "active": active.tolist(),
                "reached": reached.tolist(),
            }
        )

    # Risk display scale: robust positive quantiles for a legible log heatmap.
    positive = density[np.isfinite(density) & (density > 0)]
    if positive.size:
        qlo, qhi = np.quantile(positive, [0.02, 0.995])
        risk_scale = {"min": float(qlo), "max": float(qhi)}
    else:
        risk_scale = {"min": 0.0, "max": 0.0}

    # Smoothed reservoir scale remains linear and query-specific.
    conv_valid = conv[np.isfinite(conv)]
    conv_scale = {
        "min": float(np.nanmin(conv_valid)) if conv_valid.size else 0.0,
        "max": float(np.nanmax(conv_valid)) if conv_valid.size else 0.0,
    }

    # Remove duplicate warning messages.
    warnings = list(dict.fromkeys(warnings))

    return {
        "parameters": {
            "D": D,
            "beta0": beta0,
            "beta1": beta1,
            "b0": b0,
            "d0": d0,
            "max_chain_length": max_chain_length,
            "optimum": optimum,
            "duration": duration,
            "frames": frames,
            "seed": seed,
        },
        "poisson": {
            "total_rate": total_rate,
            "expected_spillovers": expected_seeds,
            "realized_spillovers": n_seeds,
        },
        "frame_times": np.round(frame_times, 5).tolist(),
        "totals": {
            "active": total_active.tolist(),
            "reached": total_reached.tolist(),
            "active_clusters": active_clusters.tolist(),
        },
        "clusters": clusters,
        "risk_scale": risk_scale,
        "convolved_scale": conv_scale,
        "warnings": warnings,
    }


def model_metadata() -> dict[str, Any]:
    maps = load_maps()
    valid_ks = maps.Ks[np.isfinite(maps.Ks)]
    approx_population = float(np.nansum(maps.Ks) * maps.cell_area_km2)
    return {
        "defaults": DEFAULTS,
        "fixed": {
            "trait_distribution": "standard normal N(0, 1)",
            "birth_rate_form": "b(theta) = b0",
            "death_rate_form": "d(theta) = d0 + (theta - O_s)^2",
        },
        "map": {
            "lon_min": float(maps.lons[0]),
            "lon_max": float(maps.lons[-1]),
            "lat_min": float(maps.lats[0]),
            "lat_max": float(maps.lats[-1]),
            "nx": int(maps.lons.size),
            "ny": int(maps.lats.size),
            "cell_area_km2": maps.cell_area_km2,
            "approx_Ks_population_integral": approx_population,
            "Ks_min": float(np.nanmin(valid_ks)),
            "Ks_max": float(np.nanmax(valid_ks)),
        },
        "parameter_bounds": {
            "D": {"min": 0.0, "max": 10000.0},
            "beta0": {"min": 0.0, "max": 1e-6},
            "beta1": {"min": 0.0, "max": 1e-6},
            "b0": {"min": 0.0, "max": 5.0},
            "d0": {"min": 0.0, "max": 5.0},
            "max_chain_length": {"min": 0, "max": 500},
            "optimum": {"min": 0, "max": 3.0},
            "duration": {"min": 1.0, "max": 50.0},
            "frames": {"min": 61, "max": 301},
        },
    }
