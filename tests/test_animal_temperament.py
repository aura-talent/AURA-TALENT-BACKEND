from app.services import animal


def _swipes(n_right, n_left, ms=3000, changes=0):
    s = [{"direction": "right", "decision_ms": ms, "direction_changes": changes}] * n_right
    s += [{"direction": "left", "decision_ms": ms, "direction_changes": changes}] * n_left
    return s


def test_low_right_rate_is_selective():
    assert animal.temperament(_swipes(2, 10)) == "selective"


def test_slow_or_wavering_is_analytical():
    assert animal.temperament(_swipes(6, 6, ms=6000)) == "analytical"
    assert animal.temperament(_swipes(6, 6, ms=3000, changes=2)) == "analytical"


def test_high_right_rate_is_exploratory():
    assert animal.temperament(_swipes(10, 3, ms=2500)) == "exploratory"


def test_default_is_decisive():
    assert animal.temperament(_swipes(6, 7, ms=1500)) == "decisive"


def test_empty_swipes_is_decisive():
    assert animal.temperament([]) == "decisive"


def test_alignment_identical_is_100():
    v = dict.fromkeys(animal.AXES, 0.5)
    assert animal.alignment(v, v) == 100


def test_alignment_opposite_is_0():
    v = dict.fromkeys(animal.AXES, 0.5)
    w = dict.fromkeys(animal.AXES, -0.5)
    assert animal.alignment(v, w) == 0


def test_alignment_none_when_no_stated():
    assert animal.alignment(dict.fromkeys(animal.AXES, 0.5), None) is None


def test_selective_beats_analytical_when_both_match():
    # right_rate 2/12 = 0.167 <= 0.25 AND median_ms 6000 >= 5000 -> selective wins
    assert animal.temperament(_swipes(2, 10, ms=6000)) == "selective"


def test_analytical_beats_exploratory_when_both_match():
    # right_rate 10/13 = 0.77 >= 0.6 AND median_ms 6000 >= 5000 -> analytical wins
    assert animal.temperament(_swipes(10, 3, ms=6000)) == "analytical"
