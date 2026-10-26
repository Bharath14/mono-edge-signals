import numpy as np
import pytest

from simulator import config as c
from simulator import generator as g


@pytest.fixture(scope="module")
def data():
    return g.generate_loop()


def window(data, start, end):
    t = data["t"]
    return (t >= start) & (t < end)


def outside_cobbles(data, margin=1.0):
    t = data["t"]
    mask = np.ones(len(t), dtype=bool)
    for s in c.COBBLE_STARTS_S:
        mask &= ~((t >= s) & (t < s + c.COBBLE_DURATION_S + margin))
    return mask


def test_shape_and_timestamps(data):
    assert len(data["t"]) == 30_000
    assert g.format_ts(0) == "2026-01-01T00:00:00.000Z"
    assert g.format_ts(1) == "2026-01-01T00:00:00.020Z"
    assert g.format_ts(29_999) == "2026-01-01T00:09:59.980Z"


def test_deterministic(data):
    again = g.generate_loop()
    for sig in c.SIGNALS:
        assert np.array_equal(data[sig], again[sig])


def test_different_seed_changes_noise(data):
    other = g.generate_loop(seed=7)
    assert not np.array_equal(data["motor_speed"], other["motor_speed"])


def test_normal_operation_is_stable(data):
    mask = outside_cobbles(data)
    speed_error = np.abs(data["motor_speed"][mask] - data["setpoint"][mask])
    assert speed_error.max() < 30          # rpm
    assert data["vibration"][mask].max() < 4.0


def test_cobble_signature_every_minute(data):
    t = data["t"]
    assert len(c.COBBLE_STARTS_S) == 10
    for s in c.COBBLE_STARTS_S:
        w = (t >= s) & (t < s + c.COBBLE_DURATION_S)
        ratio = data["motor_speed"][w] / data["setpoint"][w]
        assert ratio.min() < 0.5           # sudden speed dip
        assert data["vibration"][w].max() > 6.0
        # wobble: speed recovers but not monotonically
        recovery = data["motor_speed"][(t >= s + 0.5) & (t < s + 4.0)]
        assert (np.diff(recovery) > 0).any() and (np.diff(recovery) < 0).any()


def test_speed_recovers_after_cobble(data):
    t = data["t"]
    for s in c.COBBLE_STARTS_S:
        after = (t >= s + c.COBBLE_DURATION_S + 1) & (t < s + c.COBBLE_DURATION_S + 3)
        assert np.abs(data["motor_speed"][after] - data["setpoint"][after]).max() < 30


def test_load_change_raises_load_signals_but_not_speed_or_vibration(data):
    base = window(data, 40, 80)
    hold = window(data, 165, 190)  # inside the hold, after the 2:30 cobble ends
    for sig in ("motor_current", "torque", "rolling_force"):
        ratio = data[sig][hold].mean() / data[sig][base].mean()
        assert 1.3 < ratio < 1.5, sig
    assert abs(data["motor_speed"][hold].mean() - data["motor_speed"][base].mean()) < 5
    assert abs(data["vibration"][hold].mean() - data["vibration"][base].mean()) < 0.3


def test_load_change_never_looks_like_a_cobble(data):
    hold = window(data, 135, 210) & outside_cobbles(data)
    ratio = data["motor_speed"][hold] / data["setpoint"][hold]
    assert ratio.min() > 0.97
    assert data["vibration"][hold].max() < 4.0


def test_speed_step_is_smooth_not_a_dip(data):
    step = window(data, 440, 470)
    plateau = data["motor_speed"][step & outside_cobbles(data)]
    assert 880 < plateau.mean() < 920       # about -10 percent
    # largest 1 second change during the step stays small compared to a cobble
    per_second = data["motor_speed"].reshape(-1, 50).mean(axis=1)
    sec = np.arange(600)
    mask = (sec >= 418) & (sec < 442)
    assert np.abs(np.diff(per_second[mask])).max() < 40


def test_current_torque_force_are_correlated(data):
    mask = outside_cobbles(data)
    cur, tq, fr = (data[s][mask] for s in ("motor_current", "torque", "rolling_force"))
    assert np.corrcoef(cur, tq)[0, 1] > 0.9
    assert np.corrcoef(cur, fr)[0, 1] > 0.9


def test_build_messages_shape(data):
    msgs = g.build_messages(data)
    assert len(msgs) == 30_000
    assert set(msgs[0]) == {"mill_id", "timestamp", *c.SIGNALS}


def test_fault_injection_is_deterministic_and_counted(data):
    msgs = g.build_messages(data)
    a, counts_a = g.inject_faults(msgs)
    b, counts_b = g.inject_faults(msgs)
    assert a == b and counts_a == counts_b
    assert len(a) == len(msgs) - counts_a["dropped_tick"]
    assert sum(counts_a.values()) > 0
    assert any(m["timestamp"] == "not-a-timestamp" for m in a)
