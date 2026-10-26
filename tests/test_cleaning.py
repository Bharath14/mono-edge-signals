from datetime import datetime, timezone

from simulator.cleaning import clean_message, parse_timestamp

GOOD = {
    "mill_id": "RM-01",
    "timestamp": "2026-01-01T00:00:00.020Z",
    "motor_speed": 1000.0,
    "motor_current": 150.0,
    "torque": 40.0,
    "rolling_force": 2000.0,
    "vibration": 2.0,
    "temperature": 75.0,
}


def msg(**changes):
    out = dict(GOOD)
    out.update(changes)
    return out


def reasons(result):
    return [r["reason"] for r in result.rejects]


def test_valid_message_passes_untouched():
    r = clean_message(GOOD)
    assert r.rejects == []
    assert r.row == (
        "RM-01",
        datetime(2026, 1, 1, 0, 0, 0, 20000, tzinfo=timezone.utc),
        1000.0, 150.0, 40.0, 2000.0, 2.0, 75.0,
    )


def test_null_value_is_kept_as_null_and_not_logged():
    r = clean_message(msg(vibration=None))
    assert r.row[6] is None
    assert r.rejects == []


def test_missing_field_is_treated_as_null():
    m = dict(GOOD)
    del m["torque"]
    r = clean_message(m)
    assert r.row[4] is None and r.rejects == []


def test_numeric_text_is_converted():
    r = clean_message(msg(motor_current="126.5"))
    assert r.row[3] == 126.5 and r.rejects == []


def test_non_numeric_text_is_nulled_and_logged():
    r = clean_message(msg(motor_current="ERR"))
    assert r.row[3] is None
    assert reasons(r) == ["non_numeric:motor_current"]


def test_sentinel_is_nulled_and_logged_but_row_is_kept():
    r = clean_message(msg(motor_speed=-9999.0))
    assert r.row is not None and r.row[2] is None
    assert reasons(r) == ["out_of_range:motor_speed"]


def test_nan_and_infinity_are_rejected_per_field():
    r = clean_message(msg(torque=float("nan"), rolling_force=float("inf")))
    assert r.row[4] is None and r.row[5] is None
    assert sorted(reasons(r)) == ["non_finite:rolling_force", "non_finite:torque"]


def test_bad_timestamp_rejects_whole_message():
    for bad in ("not-a-timestamp", "", None, 12345):
        r = clean_message(msg(timestamp=bad))
        assert r.row is None
        assert reasons(r) == ["bad_timestamp"]


def test_missing_mill_id_rejects_whole_message():
    r = clean_message(msg(mill_id="  "))
    assert r.row is None and reasons(r) == ["missing_mill_id"]


def test_not_an_object():
    for bad in ("hello", 5, [1, 2], None):
        r = clean_message(bad)
        assert r.row is None and reasons(r) == ["not_an_object"]


def test_all_signals_invalid_rejects_whole_message():
    r = clean_message(
        {"mill_id": "RM-01", "timestamp": "2026-01-01T00:00:00Z"}
    )
    assert r.row is None and "no_valid_signals" in reasons(r)


def test_naive_timestamp_is_assumed_utc():
    ts = parse_timestamp("2026-01-01T05:30:00")
    assert ts == datetime(2026, 1, 1, 5, 30, tzinfo=timezone.utc)


def test_offset_timestamp_is_converted_to_utc():
    ts = parse_timestamp("2026-01-01T05:30:00+05:30")
    assert ts == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
