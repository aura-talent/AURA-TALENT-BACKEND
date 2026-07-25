import pytest

from app.services.fairpay_math import (
    Band,
    band_from_anchors,
    blend_bands,
    confidence_for,
    experience_position,
    growth_factor,
    smoothstep,
    university_weight,
)

MY_ROLE_BAND = {
    "typical": {"lo": 5250, "hi": 7750},
    "junior": 6000,
    "senior": 20000,
    "currency": "MYR",
    "period": "month",
}


class TestExperiencePosition:
    def test_zero_years_is_zero(self):
        assert experience_position(0) == 0.0

    def test_cap_years_is_one(self):
        assert experience_position(10) == 1.0

    def test_beyond_cap_stays_one(self):
        assert experience_position(25) == 1.0

    def test_negative_years_clamps_to_zero(self):
        assert experience_position(-3) == 0.0

    def test_monotonic(self):
        samples = [experience_position(y) for y in range(0, 11)]
        assert samples == sorted(samples)

    def test_smoothstep_midpoint(self):
        assert smoothstep(0.5) == pytest.approx(0.5)


class TestBandFromAnchors:
    def test_fresh_grad_centers_on_junior_anchor(self):
        b = band_from_anchors(MY_ROLE_BAND, 0)
        assert b["p50"] == pytest.approx(6000)
        assert b["currency"] == "MYR" and b["period"] == "month"

    def test_ten_years_centers_on_senior_anchor(self):
        b = band_from_anchors(MY_ROLE_BAND, 10)
        assert b["p50"] == pytest.approx(20000)

    def test_band_is_ordered(self):
        for years in (0, 2.5, 5, 8, 12):
            b = band_from_anchors(MY_ROLE_BAND, years)
            assert b["p25"] < b["p50"] < b["p75"]

    def test_width_comes_from_typical_range(self):
        b = band_from_anchors(MY_ROLE_BAND, 0)
        r = (7750 - 5250) / (7750 + 5250)  # relative half-width
        assert b["p25"] == pytest.approx(6000 * (1 - r))
        assert b["p75"] == pytest.approx(6000 * (1 + r))

    def test_missing_anchors_falls_back_to_typical(self):
        rb = {"typical": {"lo": 4000, "hi": 6000}, "junior": None, "senior": None,
              "currency": "MYR", "period": "month"}
        b = band_from_anchors(rb, 5)
        assert (b["p25"], b["p50"], b["p75"]) == (4000, 5000, 6000)

    def test_no_data_returns_none(self):
        assert band_from_anchors({"typical": {}, "junior": None, "senior": None}, 3) is None


class TestUniversityWeight:
    def test_fresh_grad_full_weight(self):
        assert university_weight(0) == 1.0

    def test_half_weight_at_one_point_five_years(self):
        assert university_weight(1.5) == pytest.approx(0.5)

    def test_zero_at_three_years_and_beyond(self):
        assert university_weight(3) == 0.0
        assert university_weight(12) == 0.0


class TestBlendBands:
    DEG = Band(p25=5300, p50=6400, p75=7500, currency="SGD", period="month")
    ROLE = Band(p25=6000, p50=8000, p75=10000, currency="SGD", period="month")

    def test_full_weight_returns_degree_band(self):
        assert blend_bands(self.DEG, self.ROLE, 1.0) == self.DEG

    def test_zero_weight_returns_role_band(self):
        assert blend_bands(self.DEG, self.ROLE, 0.0) == self.ROLE

    def test_half_weight_is_elementwise_mean(self):
        b = blend_bands(self.DEG, self.ROLE, 0.5)
        assert b["p50"] == pytest.approx(7200)

    def test_degree_band_stands_alone_when_no_role_band(self):
        assert blend_bands(self.DEG, None, 0.7) == self.DEG

    def test_currency_mismatch_returns_role_band(self):
        myr = Band(p25=5000, p50=6000, p75=7000, currency="MYR", period="month")
        assert blend_bands(self.DEG, myr, 0.5) == myr

    def test_both_none_is_none(self):
        assert blend_bands(None, None, 0.5) is None


class TestGrowthFactor:
    def test_now_is_identity(self):
        assert growth_factor(MY_ROLE_BAND, 4, 0) == pytest.approx(1.0)

    def test_grows_toward_senior_anchor(self):
        assert growth_factor(MY_ROLE_BAND, 2, 3) > 1.0

    def test_flat_once_capped(self):
        assert growth_factor(MY_ROLE_BAND, 10, 5) == pytest.approx(1.0)

    def test_generic_fallback_without_anchors(self):
        assert growth_factor(None, 4, 3) == pytest.approx(1.05 ** 3)


class TestConfidence:
    def test_llm_mode_is_low(self):
        assert confidence_for("llm", "US", None, False) == {"level": "low", "reason": "LLM_ONLY"}

    def test_my_data_is_high(self):
        c = confidence_for("data", "MY", None, False)
        assert c == {"level": "high", "reason": "JOBSTREET+HAYS_BAND"}

    def test_sg_adzuna_thresholds(self):
        assert confidence_for("data", "SG", 30, False)["level"] == "high"
        assert confidence_for("data", "SG", 8, False)["level"] == "medium"
        assert confidence_for("data", "SG", 7, False)["level"] == "low"
        assert confidence_for("data", "SG", 30, False)["reason"] == "ADZUNA_N=30"

    def test_sg_degree_band_only_is_medium(self):
        c = confidence_for("data", "SG", None, True)
        assert c == {"level": "medium", "reason": "GES_2025_DEGREE_BAND"}
