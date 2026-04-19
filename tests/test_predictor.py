"""Tests for the EMA predictor."""

import pytest

from nexus.telemetry import SimplePredictor


def test_first_observation_is_identity():
    p = SimplePredictor(alpha=0.3)
    assert p.predict(50.0) == 50.0


def test_ema_converges_toward_observation():
    p = SimplePredictor(alpha=0.5)
    # alpha=0.5 makes the math easy to verify.
    assert p.predict(100.0) == 100.0
    assert p.predict(90.0) == 95.0   # 0.5*90 + 0.5*100
    assert p.predict(80.0) == 87.5   # 0.5*80 + 0.5*95


def test_constant_input_predicts_constant_output():
    p = SimplePredictor(alpha=0.3)
    for _ in range(50):
        out = p.predict(42.0)
    assert out == pytest.approx(42.0, abs=1e-9)


def test_invalid_alpha_rejected():
    with pytest.raises(ValueError):
        SimplePredictor(alpha=0.0)
    with pytest.raises(ValueError):
        SimplePredictor(alpha=1.0)
    with pytest.raises(ValueError):
        SimplePredictor(alpha=1.5)


def test_alpha_zero_not_permitted_so_memory_always_partial():
    # Design note: alpha in (0,1) exclusive means predictor can't be "pure memory"
    # (alpha=0) or "pure observation" (alpha=1). If that changes, update this test.
    p = SimplePredictor(alpha=0.1)
    p.predict(100.0)
    p.predict(0.0)
    # After one observation of 0, the EMA should have moved toward 0 but not reached it.
    assert 0.0 < p.predicted < 100.0
