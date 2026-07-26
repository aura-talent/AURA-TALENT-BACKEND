import pytest

from app.services import animal


def test_axes_canonical_order():
    assert animal.AXES == [
        "social", "motion", "visibility", "environment", "autonomy", "north_star"
    ]


def test_zero_vector():
    v = animal.zero_vector()
    assert set(v) == set(animal.AXES)
    assert all(x == 0.0 for x in v.values())


def test_right_swipe_pulls_toward_traits():
    v = animal.zero_vector()
    traits = dict.fromkeys(animal.AXES, 0.0) | {"social": 1.0}
    out = animal.update_vector(v, traits, "right")
    assert out["social"] == pytest.approx(0.25)   # lr_right * (1.0 - 0.0)
    assert out["motion"] == 0.0
    assert v["social"] == 0.0                      # input not mutated


def test_left_swipe_pushes_away():
    v = animal.zero_vector()
    traits = dict.fromkeys(animal.AXES, 0.0) | {"visibility": 1.0}
    out = animal.update_vector(v, traits, "left")
    assert out["visibility"] == pytest.approx(-0.12)  # -lr_left * trait


def test_values_clamped():
    v = dict.fromkeys(animal.AXES, 0.0) | {"social": 0.95}
    traits = dict.fromkeys(animal.AXES, 0.0) | {"social": 1.0}
    out = animal.update_vector(v, traits, "right")
    assert out["social"] <= 1.0
    v2 = dict.fromkeys(animal.AXES, 0.0) | {"social": -0.99}
    out2 = animal.update_vector(v2, traits, "left")
    assert out2["social"] >= -1.0


def test_bad_direction_raises():
    with pytest.raises(ValueError):
        animal.update_vector(animal.zero_vector(), animal.zero_vector(), "up")
