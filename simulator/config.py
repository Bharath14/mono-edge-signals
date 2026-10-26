"""Shared constants for the simulator, cleaning rules and tests.

Everything about the seed loop lives here so the generator, the detector
(later) and the tests all agree on where the events are.
"""

import os
from datetime import datetime, timezone

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://mill:mill@localhost:5432/millsignals"
)

MILL_ID = "RM-01"

# Sampling: one reading of every signal every 20 ms.
SAMPLE_HZ = 50
TICK_MS = 1000 // SAMPLE_HZ
LOOP_SECONDS = 600
LOOP_TICKS = LOOP_SECONDS * SAMPLE_HZ

# The loop is stored at a fixed, obviously synthetic date. The API maps the
# real clock onto this window to replay it.
LOOP_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
SEED = 42

SIGNALS = (
    "motor_speed",
    "motor_current",
    "torque",
    "rolling_force",
    "vibration",
    "temperature",
)

UNITS = {
    "motor_speed": "rpm",
    "motor_current": "A",
    "torque": "kN.m",
    "rolling_force": "kN",
    "vibration": "mm/s",
    "temperature": "degC",
}

# Physical plausibility bounds used by the cleaning step. A value outside its
# range is treated as a sensor fault (set to NULL and logged), not as data.
VALID_RANGES = {
    "motor_speed": (0.0, 1500.0),
    "motor_current": (0.0, 600.0),
    "torque": (0.0, 150.0),
    "rolling_force": (0.0, 6000.0),
    "vibration": (0.0, 50.0),
    "temperature": (-20.0, 200.0),
}

# Short prefixes used by the rollup columns (speed_avg, vib_max, ...).
ROLLUP_PREFIX = {
    "motor_speed": "speed",
    "motor_current": "current",
    "torque": "torque",
    "rolling_force": "force",
    "vibration": "vib",
    "temperature": "temp",
}

# ---- Nominal operating point -------------------------------------------------
BASE_SPEED_RPM = 1000.0
BASE_CURRENT_A = 150.0
BASE_TORQUE = 40.0
BASE_FORCE_KN = 2000.0
BASE_VIBRATION = 2.0
BASE_TEMPERATURE = 75.0

# ---- Events in the 10 minute loop (seconds from loop start) -----------------
# Cobble: every 60 s, at 0:30, 1:30, ... 9:30.
COBBLE_STARTS_S = tuple(range(30, LOOP_SECONDS, 60))
COBBLE_DURATION_S = 9.0  # time after which signals are back inside normal noise

# Legitimate load change (placeholder numbers, easy to change):
# ramp up 2:15 to 2:30, hold, ramp down 3:15 to 3:30, +40 percent load.
LOAD_RAMP_UP_S = (135.0, 150.0)
LOAD_RAMP_DOWN_S = (195.0, 210.0)
LOAD_FACTOR = 1.4

# Legitimate speed setpoint change: -10 percent from 7:00, back by 8:10.
SPEED_STEP_DOWN_S = (420.0, 440.0)
SPEED_STEP_UP_S = (470.0, 490.0)
SPEED_STEP_FACTOR = 0.9

# ---- Data faults injected by the seeder to exercise the cleaning step -------
FAULT_RATES = {
    "dropped_tick": 0.0005,     # sample never arrives
    "null_value": 0.0015,       # one signal is null
    "sentinel_value": 0.0005,   # one signal reads -9999 (PLC error value)
    "string_value": 0.0005,     # one signal arrives as "126.5" text
    "bad_timestamp": 0.0003,    # timestamp is garbage
}
SENTINEL = -9999.0
