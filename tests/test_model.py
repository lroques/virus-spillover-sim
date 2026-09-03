import math

import numpy as np

from app.model import DEFAULTS, convolved_reservoir, load_maps, simulate, trait_death_rate


def test_spatial_maps_share_grid_and_have_expected_ranges():
    maps = load_maps()
    assert maps.Ks.shape == maps.Kr.shape == maps.alpha.shape == maps.mask.shape
    assert maps.Ks.shape == (305, 360)
    assert maps.mask.sum() > 10_000
    assert np.nanmax(maps.Ks) > 1e5
    assert 0.0 <= np.nanmin(maps.alpha) < np.nanmax(maps.alpha) <= 1.0
    assert 0.0 <= np.nanmin(maps.Kr) < np.nanmax(maps.Kr) <= 1.0


def test_requested_defaults():
    assert DEFAULTS["beta0"] == 5e-8
    assert DEFAULTS["b0"] == 0.5
    assert DEFAULTS["d0"] == 0.3
    assert DEFAULTS["duration"] == 50.0


def test_birth_death_rule_uses_editable_d0():
    assert trait_death_rate(0.0, 0.0) == 0.3
    assert math.isclose(trait_death_rate(1.0, 0.0), 1.3)
    assert trait_death_rate(0.0, 0.0, d0=0.7) == 0.7
    assert trait_death_rate(math.sqrt(0.2), 0.0) == 0.5


def test_gaussian_smoothing_preserves_shape_and_mask():
    maps = load_maps()
    smoothed = convolved_reservoir(DEFAULTS["D"], maps)
    assert smoothed.shape == maps.Kr.shape
    assert np.isnan(smoothed[~maps.mask]).all()
    assert np.isfinite(smoothed[maps.mask]).all()


def test_simulation_is_reproducible():
    kwargs = dict(
        D=DEFAULTS["D"],
        beta0=DEFAULTS["beta0"],
        beta1=DEFAULTS["beta1"],
        b0=DEFAULTS["b0"],
        d0=DEFAULTS["d0"],
        optimum=DEFAULTS["optimum"],
        duration=DEFAULTS["duration"],
        frames=DEFAULTS["frames"],
        seed=DEFAULTS["seed"],
    )
    a = simulate(**kwargs)
    b = simulate(**kwargs)
    assert a["poisson"] == b["poisson"]
    assert a["totals"] == b["totals"]
    assert a["clusters"] == b["clusters"]
    assert a["poisson"]["realized_spillovers"] > 0
    assert a["parameters"]["b0"] == 0.5
    assert a["parameters"]["d0"] == 0.3
