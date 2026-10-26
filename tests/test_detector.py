from datetime import timedelta

import pytest

from detector.cobble import CobbleDetector, detect
from simulator import config as c
from simulator import generator as g
from simulator.cleaning import clean_message


def to_rows(data):
    return [
        (c.LOOP_START + timedelta(milliseconds=c.TICK_MS * i), *[float(data[s][i]) for s in c.SIGNALS])
        for i in range(len(data["t"]))
    ]


def seconds(ts):
    return (ts - c.LOOP_START).total_seconds()


@pytest.fixture(scope="module")
def result():
    return detect(to_rows(g.generate_loop()))


def test_one_incident_per_cobble(result):
    closed, still_open = result
    truth = g.ground_truth()["cobbles"]
    assert still_open is None
    assert len(closed) == len(truth) == 10
    for inc, cob in zip(closed, truth):
        assert cob["start_s"] <= seconds(inc.started_at) < cob["start_s"] + 0.5
        assert seconds(inc.ended_at) <= cob["end_s"]


def test_no_incident_during_load_change_or_speed_step(result):
    closed, _ = result
    truth = g.ground_truth()
    cobble_starts = [cob["start_s"] for cob in truth["cobbles"]]
    for inc in closed:
        start = seconds(inc.started_at)
        # every incident belongs to a cobble, none to the legitimate changes
        assert any(0 <= start - s < 0.5 for s in cobble_starts)


def test_record_has_reason_signals_and_peaks(result):
    rec = result[0][0].as_record()
    assert rec["affected_signals"][:2] == ["motor_speed", "vibration"]
    assert "motor_current" in rec["affected_signals"]
    assert rec["peak_values"]["min_speed"] < 0.5 * rec["peak_values"]["baseline"]["motor_speed"]
    assert rec["peak_values"]["max_vibration"] > 6.0
    assert rec["reason"].startswith("Cobble pattern: motor speed fell from 1000")


@pytest.mark.parametrize("seed", [1, 7, 2024])
def test_other_noise_seeds_with_data_faults(seed):
    data = g.generate_loop(seed=seed)
    messages, _ = g.inject_faults(g.build_messages(data), seed=seed + 1)
    rows = [r.row[1:] for r in map(clean_message, messages) if r.row is not None]
    closed, still_open = detect(rows)
    assert len(closed) == 10 and still_open is None


def _steady(n, start=0, **override):
    base = dict(speed=1000.0, current=150.0, torque=40.0, force=2000.0, vib=2.0, temp=75.0)
    rows = []
    for i in range(start, start + n):
        v = dict(base)
        v.update({k: (f(i) if callable(f) else f) for k, f in override.items()})
        rows.append((c.LOOP_START + timedelta(milliseconds=20 * i),
                     v["speed"], v["current"], v["torque"], v["force"], v["vib"], v["temp"]))
    return rows


def test_short_glitch_does_not_open_an_incident():
    rows = _steady(500) + _steady(5, 500, speed=300.0, vib=9.0) + _steady(500, 505)
    assert detect(rows) == ([], None)


def test_speed_drop_without_vibration_is_not_a_cobble():
    rows = _steady(500) + _steady(500, 500, speed=500.0) + _steady(500, 1000)
    assert detect(rows) == ([], None)


def test_vibration_alone_is_not_a_cobble():
    rows = _steady(500) + _steady(500, 500, vib=9.0) + _steady(500, 1000)
    assert detect(rows) == ([], None)


def test_open_incident_is_reported_until_it_recovers():
    rows = _steady(500) + _steady(200, 500, speed=300.0, vib=9.0)
    closed, still_open = detect(rows)
    assert closed == [] and still_open is not None and still_open.ended_at is None


def test_null_values_are_skipped():
    det = CobbleDetector()
    rows = _steady(500)
    rows[250] = (rows[250][0], None, None, None, None, None, None)
    for row in rows:
        assert det.update(row) is None
