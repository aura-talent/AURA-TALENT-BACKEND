from app.services import animal


def _vec(**kw):
    return dict.fromkeys(animal.AXES, 0.0) | kw


def test_twelve_prototypes():
    assert set(animal.PROTOTYPES) == {
        "owl", "beaver", "fox", "octopus", "wolf", "hawk",
        "shark", "lion", "dolphin", "deer", "tortoise", "chameleon",
    }
    for proto in animal.PROTOTYPES.values():
        assert set(proto) == set(animal.AXES)


def test_heads_down_craft_is_owl():
    v = _vec(social=-0.8, motion=-0.7, visibility=-0.8, autonomy=-0.5)
    name, conf = animal.classify(v, swipe_count=15)
    assert name == "owl"
    assert 0.0 <= conf <= 1.0


def test_spotlight_persuasion_is_lion():
    v = _vec(social=0.9, motion=0.9, visibility=0.9, autonomy=0.5)
    name, _ = animal.classify(v, swipe_count=15)
    assert name == "lion"


def test_stability_seeker_is_tortoise():
    v = _vec(environment=-0.9, north_star=-0.4, social=-0.4, motion=-0.4, visibility=-0.4)
    name, _ = animal.classify(v, swipe_count=15)
    assert name == "tortoise"


def test_flat_vector_with_enough_swipes_is_chameleon():
    name, conf = animal.classify(animal.zero_vector(), swipe_count=12)
    assert name == "chameleon"
    assert conf == 0.6


def test_flat_vector_few_swipes_is_not_chameleon():
    # Too few swipes to call "low fixation" — fall through to nearest prototype.
    name, _ = animal.classify(animal.zero_vector(), swipe_count=3)
    assert name != "chameleon"


def test_deterministic():
    v = _vec(environment=0.8, motion=-0.3)
    assert animal.classify(v, 15) == animal.classify(v, 15)
