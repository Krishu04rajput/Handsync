from app.smoothing import ExponentialSmoother, ServoSmoother


def test_exponential_first_value_and_convergence():
    s = ExponentialSmoother(0.5)
    assert s.update(10) == 10
    assert s.update(20) == 15


def test_step_limit_enforced():
    sm = ServoSmoother([90] * 8, alpha=1.0, max_step=3.0, deadband=0.0)
    out = sm.step([180] * 8)
    assert all(abs(v - 93) < 1e-9 for v in out)


def test_deadband_ignores_tiny_changes():
    sm = ServoSmoother([90] * 8, alpha=0.5, max_step=5, deadband=1.0)
    assert sm.step([90.5] * 8) == [90.0] * 8


def test_reaches_target_eventually():
    sm = ServoSmoother([90] * 8, alpha=0.2, max_step=3, deadband=0.6)
    for _ in range(200):
        sm.step([140] * 8)
    assert all(abs(v - 140) <= 0.6 for v in sm.values)


def test_never_overshoots():
    sm = ServoSmoother([90.0], alpha=0.9, max_step=50, deadband=0.0)
    for _ in range(20):
        assert sm.step([100.0])[0] <= 100.0
