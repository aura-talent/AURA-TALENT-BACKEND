from app.services import animal


def _job(i):
    return {"company": f"Co{i}", "title": f"Role {i}", "url": f"https://x.com/{i}",
            "location": "Remote", "source": "greenhouse"}


def _traits():
    return dict.fromkeys(animal.AXES, 0.1)


def test_card_id_stable_and_short():
    a = animal.card_id("https://x.com/1")
    assert a == animal.card_id("https://x.com/1")
    assert len(a) == 12
    assert a != animal.card_id("https://x.com/2")


def test_seed_deck_loads_15_tagged_cards():
    seed = animal.load_seed_deck()
    assert len(seed) == 15
    for card in seed:
        assert set(card["traits"]) == set(animal.AXES)
        assert card["id"] == animal.card_id(card["url"])
        assert card["source"] == "seed"


def test_build_deck_zips_jobs_with_traits():
    jobs = [_job(i) for i in range(15)]
    deck = animal.build_deck(jobs, [_traits()] * 15, count=15)
    assert len(deck) == 15
    assert deck[0]["company"] == "Co0"
    assert deck[0]["id"] == animal.card_id("https://x.com/0")
    assert deck[0]["traits"] == _traits()


def test_build_deck_tops_up_from_seed_when_short():
    jobs = [_job(i) for i in range(4)]
    deck = animal.build_deck(jobs, [_traits()] * 4, count=15)
    assert len(deck) == 15
    assert sum(1 for c in deck if c["source"] == "seed") == 11


def test_build_deck_empty_jobs_is_all_seed():
    deck = animal.build_deck([], [], count=15)
    assert len(deck) == 15
    assert all(c["source"] == "seed" for c in deck)


def test_build_deck_caps_at_count():
    jobs = [_job(i) for i in range(30)]
    deck = animal.build_deck(jobs, [_traits()] * 30, count=15)
    assert len(deck) == 15
