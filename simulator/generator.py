"""Deterministic generator for the 10 minute rolling mill loop.

The model is deliberately simple but physically motivated:

* A hidden "load" drives motor current, torque and rolling force together
  (plus a shared noise term so they stay correlated).
* The speed controller holds motor speed at its setpoint, so a legitimate load
  change does NOT move speed or vibration.
* A cobble is a sudden speed dip with a wobble while it recovers, a vibration
  jump that stays high until speed settles, and a short current/torque/force
  spike.
"""

from datetime import timedelta

import numpy as np

from . import config as c


# ---------------------------------------------------------------- helpers ---
def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _ramp(t, window):
    start, end = window
    return _smoothstep((t - start) / (end - start))


def _ar1(rng, n, phi, sigma):
    """Autocorrelated noise with stationary standard deviation `sigma`."""
    innovations = rng.normal(0.0, sigma * np.sqrt(1.0 - phi * phi), n)
    out = np.empty(n)
    out[0] = rng.normal(0.0, sigma)
    for i in range(1, n):
        out[i] = phi * out[i - 1] + innovations[i]
    return out


def load_profile(t):
    """1.0 normally, rising smoothly to LOAD_FACTOR during the load change."""
    return 1.0 + (c.LOAD_FACTOR - 1.0) * (
        _ramp(t, c.LOAD_RAMP_UP_S) - _ramp(t, c.LOAD_RAMP_DOWN_S)
    )


def speed_setpoint(t):
    """Speed setpoint in rpm, with one legitimate step down and back up."""
    drop = (1.0 - c.SPEED_STEP_FACTOR) * (
        _ramp(t, c.SPEED_STEP_DOWN_S) - _ramp(t, c.SPEED_STEP_UP_S)
    )
    return c.BASE_SPEED_RPM * (1.0 - drop)


def cobble_components(t, t0):
    """Envelopes for one cobble starting at t0 (seconds).

    Returns (env, dip, fast), each 0 outside the event:
      env  smooth 0..1 envelope, drives vibration
      dip  same envelope times a wobble, drives the speed dip
      fast quickly decaying envelope, drives the current/torque/force spike
    """
    rise = 0.3        # speed collapses within 0.3 s
    tau = 1.8         # recovery time constant
    wobble_hz = 1.5
    k = t - t0
    after = np.clip(k - rise, 0.0, None)
    onset = np.clip(k / rise, 0.0, 1.0)
    active = k >= 0
    decay = np.exp(-after / tau)
    env = np.where(active, onset * decay, 0.0)
    wobble = 0.55 + 0.45 * np.cos(2.0 * np.pi * wobble_hz * after)
    dip = env * wobble
    fast = np.where(active, onset * np.exp(-after / 1.0), 0.0)
    return env, dip, fast


# ------------------------------------------------------------- generation ---
def generate_loop(seed=c.SEED):
    """Return {'t': seconds array, <signal>: values} for one full loop."""
    rng = np.random.default_rng(seed)
    n = c.LOOP_TICKS
    t = np.arange(n) / c.SAMPLE_HZ

    load = load_profile(t)
    sp = speed_setpoint(t)

    env = np.zeros(n)
    dip = np.zeros(n)
    fast = np.zeros(n)
    for t0 in c.COBBLE_STARTS_S:
        e, d, f = cobble_components(t, float(t0))
        env += e
        dip += d
        fast += f

    # Shared multiplicative noise keeps current, torque and force correlated.
    shared = _ar1(rng, n, 0.97, 0.01)
    load_eff = load * (1.0 + shared)

    speed = sp + _ar1(rng, n, 0.95, 2.5) - 0.65 * sp * dip

    current_base = c.BASE_CURRENT_A * load_eff * (sp / c.BASE_SPEED_RPM)
    current = current_base + rng.normal(0, 0.8, n) + 0.6 * current_base * fast

    torque_base = c.BASE_TORQUE * load_eff
    torque = torque_base + rng.normal(0, 0.15, n) + 0.5 * torque_base * fast

    force_base = c.BASE_FORCE_KN * load_eff
    force = force_base + rng.normal(0, 8.0, n) + 0.25 * force_base * fast

    vibration = (
        c.BASE_VIBRATION
        + 0.1 * (load - 1.0)
        + rng.normal(0, 0.12, n)
        + 5.0 * env
        + env * rng.normal(0, 0.8, n)
    )
    vibration = np.clip(vibration, 0.05, None)

    # Temperature follows load slowly (first order lag, 60 s time constant).
    target = c.BASE_TEMPERATURE + 8.0 * (load - 1.0)
    alpha = (1.0 / c.SAMPLE_HZ) / 60.0
    temperature = np.empty(n)
    temperature[0] = c.BASE_TEMPERATURE
    for i in range(1, n):
        temperature[i] = temperature[i - 1] + (target[i] - temperature[i - 1]) * alpha
    temperature += rng.normal(0, 0.05, n)

    return {
        "t": t,
        "motor_speed": np.round(speed, 3),
        "motor_current": np.round(current, 3),
        "torque": np.round(torque, 3),
        "rolling_force": np.round(force, 3),
        "vibration": np.round(vibration, 3),
        "temperature": np.round(temperature, 3),
        "setpoint": sp,
    }


def ground_truth():
    """Known events in the loop, for testing the detector later."""
    return {
        "cobbles": [
            {"start_s": float(s), "end_s": float(s) + c.COBBLE_DURATION_S}
            for s in c.COBBLE_STARTS_S
        ],
        "load_change": {
            "start_s": c.LOAD_RAMP_UP_S[0],
            "end_s": c.LOAD_RAMP_DOWN_S[1],
        },
        "speed_step": {
            "start_s": c.SPEED_STEP_DOWN_S[0],
            "end_s": c.SPEED_STEP_UP_S[1],
        },
    }


# --------------------------------------------------------------- messages ---
def format_ts(tick, start=c.LOOP_START):
    """ISO 8601 UTC timestamp with millisecond precision for a tick index."""
    ts = start + timedelta(milliseconds=int(tick) * c.TICK_MS)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def build_messages(data, mill_id=c.MILL_ID, start=c.LOOP_START):
    """One wide message per tick, as a PLC gateway would send it."""
    messages = []
    for i in range(len(data["t"])):
        msg = {"mill_id": mill_id, "timestamp": format_ts(i, start)}
        for sig in c.SIGNALS:
            msg[sig] = float(data[sig][i])
        messages.append(msg)
    return messages


def inject_faults(messages, seed=c.SEED + 1, rates=None):
    """Return (faulty_messages, counts). Deterministic for a given seed."""
    rates = rates or c.FAULT_RATES
    rng = np.random.default_rng(seed)
    n = len(messages)
    draws = {name: rng.random(n) < rate for name, rate in rates.items()}
    sig_pick = rng.integers(0, len(c.SIGNALS), n)

    out = []
    counts = {name: 0 for name in rates}
    for i, original in enumerate(messages):
        if draws["dropped_tick"][i]:
            counts["dropped_tick"] += 1
            continue
        msg = dict(original)
        sig = c.SIGNALS[sig_pick[i]]
        # A message gets at most one fault, checked in a fixed order.
        if draws["bad_timestamp"][i]:
            msg["timestamp"] = "not-a-timestamp"
            counts["bad_timestamp"] += 1
        elif draws["null_value"][i]:
            msg[sig] = None
            counts["null_value"] += 1
        elif draws["sentinel_value"][i]:
            msg[sig] = c.SENTINEL
            counts["sentinel_value"] += 1
        elif draws["string_value"][i]:
            msg[sig] = str(msg[sig])
            counts["string_value"] += 1
        out.append(msg)
    return out, counts
