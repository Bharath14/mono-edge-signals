"""Cobble detector: a small state machine over processed readings.

What a cobble looks like in the data
------------------------------------
The strip jams, so motor speed collapses within a fraction of a second and the
stand starts shaking (vibration jumps). Current, torque and force spike briefly.
Speed then wobbles back to its setpoint over several seconds.

What must NOT alert
-------------------
* A load change: current, torque and force rise, but speed and vibration stay
  flat. The detector needs speed AND vibration, so load alone never fires.
* A speed setpoint change: speed moves smoothly (about 5 rpm/s). Speed is
  compared with its own recent baseline, not a fixed number, so a slow change
  just moves the baseline along with it.

Rules
-----
* Baseline: rolling median of the last BASELINE_S seconds of normal samples,
  per signal. Median, so a few noisy or spiky samples do not move it. The
  baseline is frozen while an incident is open, so the incident cannot drag it
  down.
* Open: speed below SPEED_DROP_RATIO of baseline AND vibration more than
  VIB_RISE above baseline, for OPEN_SAMPLES consecutive samples (0.2 s). One
  noisy reading cannot open an incident.
* Close: speed back within SPEED_OK_RATIO of baseline AND vibration within
  VIB_OK of baseline, continuously for CLOSE_S seconds (hysteresis). Speed
  wobbles while it recovers, so a single good sample is not enough.
* One cobble gives one incident with start, end, affected signals, peaks and a
  reason text.

Missing values (NULL after cleaning) are skipped: the last known value is
reused, which is fine for a gap of a few samples.
"""

from bisect import insort, bisect_left
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta

# Readings arrive as (ts, speed, current, torque, force, vibration, temperature)
SIGNALS = ("motor_speed", "motor_current", "torque", "rolling_force", "vibration", "temperature")

BASELINE_S = 5.0
WARMUP_S = 2.0              # need this much normal data before judging anything
SPEED_DROP_RATIO = 0.80     # open when speed < 80 percent of baseline ...
VIB_RISE = 1.5              # ... and vibration > baseline + 1.5 mm/s
OPEN_SAMPLES = 10           # for 10 consecutive samples (0.2 s at 50 Hz)
SPEED_OK_RATIO = 0.95       # close when speed >= 95 percent of baseline ...
VIB_OK = 1.0                # ... and vibration < baseline + 1.0 mm/s
CLOSE_S = 3.0               # continuously for 3 s
SPIKE_RATIO = 1.15          # current/torque/force count as affected above +15 percent


class RollingMedian:
    """Median over a time window, using a sorted list (window is small)."""

    def __init__(self, seconds):
        self.window = timedelta(seconds=seconds)
        self.items = deque()  # (ts, value) in arrival order
        self.sorted = []

    def add(self, ts, value):
        self.items.append((ts, value))
        insort(self.sorted, value)
        while self.items and ts - self.items[0][0] > self.window:
            _, old = self.items.popleft()
            del self.sorted[bisect_left(self.sorted, old)]

    def span(self):
        if len(self.items) < 2:
            return timedelta(0)
        return self.items[-1][0] - self.items[0][0]

    def value(self):
        n = len(self.sorted)
        if n == 0:
            return None
        mid = n // 2
        return self.sorted[mid] if n % 2 else (self.sorted[mid - 1] + self.sorted[mid]) / 2.0


@dataclass
class Incident:
    started_at: object
    baseline: dict
    ended_at: object = None
    peaks: dict = field(default_factory=dict)

    def observe(self, values):
        p = self.peaks
        speed, current, torque, force, vib, _ = values
        p["min_speed"] = min(p.get("min_speed", speed), speed)
        p["max_vibration"] = max(p.get("max_vibration", vib), vib)
        p["max_current"] = max(p.get("max_current", current), current)
        p["max_torque"] = max(p.get("max_torque", torque), torque)
        p["max_force"] = max(p.get("max_force", force), force)

    def affected_signals(self):
        b, p = self.baseline, self.peaks
        out = ["motor_speed", "vibration"]
        for sig, key in (("motor_current", "max_current"), ("torque", "max_torque"), ("rolling_force", "max_force")):
            if b[sig] and p[key] > b[sig] * SPIKE_RATIO:
                out.append(sig)
        return out

    def reason(self):
        b, p = self.baseline, self.peaks
        drop_pct = 100.0 * (1.0 - p["min_speed"] / b["motor_speed"])
        text = (
            f"Cobble pattern: motor speed fell from {b['motor_speed']:.0f} to "
            f"{p['min_speed']:.0f} rpm (-{drop_pct:.0f}%) while vibration rose to "
            f"{p['max_vibration']:.1f} mm/s (normal {b['vibration']:.1f})"
        )
        spikes = [
            f"{label} +{100.0 * (p[key] / b[sig] - 1.0):.0f}%"
            for sig, key, label in (
                ("motor_current", "max_current", "current"),
                ("torque", "max_torque", "torque"),
                ("rolling_force", "max_force", "force"),
            )
            if sig in self.affected_signals()
        ]
        if spikes:
            text += "; " + ", ".join(spikes)
        return text + "."

    def as_record(self):
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "affected_signals": self.affected_signals(),
            "reason": self.reason(),
            "peak_values": {
                **{k: round(v, 3) for k, v in self.peaks.items()},
                "baseline": {k: round(v, 3) for k, v in self.baseline.items()},
            },
        }


class CobbleDetector:
    """Feed readings in time order with update(); finished incidents come back.

    The same object works for a batch (loop over stored rows) and for live data
    (call update() as each batch arrives).
    """

    def __init__(self):
        self.medians = {sig: RollingMedian(BASELINE_S) for sig in SIGNALS}
        self.last = [None] * len(SIGNALS)
        self.open = None
        self.suspect_run = 0
        self.ok_since = None

    def _baseline(self):
        return {sig: m.value() for sig, m in self.medians.items()}

    def update(self, row):
        """Process one reading. Returns a closed Incident, or None."""
        ts, *values = row
        for i, v in enumerate(values):
            if v is not None:
                self.last[i] = v
        if any(v is None for v in self.last):
            return None  # not every signal seen yet
        values = list(self.last)
        speed, vib = values[0], values[4]

        if self.open is not None:
            return self._while_open(ts, values, speed, vib)

        warm = self.medians["motor_speed"].span() >= timedelta(seconds=WARMUP_S)
        if warm:
            base = self._baseline()
            suspect = (
                speed < SPEED_DROP_RATIO * base["motor_speed"]
                and vib > base["vibration"] + VIB_RISE
            )
            if suspect:
                if self.suspect_run == 0:
                    self.suspect_start = ts
                    self.suspect_values = []
                self.suspect_run += 1
                self.suspect_values.append(values)
                if self.suspect_run >= OPEN_SAMPLES:
                    self.open = Incident(started_at=self.suspect_start, baseline=base)
                    for v in self.suspect_values:
                        self.open.observe(v)
                    self.ok_since = None
                    self.suspect_run = 0
                # suspect samples never feed the baseline
                return None
            self.suspect_run = 0

        for sig, v in zip(SIGNALS, values):
            self.medians[sig].add(ts, v)
        return None

    def _while_open(self, ts, values, speed, vib):
        inc = self.open
        inc.observe(values)
        base = inc.baseline
        normal = (
            speed >= SPEED_OK_RATIO * base["motor_speed"]
            and vib < base["vibration"] + VIB_OK
        )
        if not normal:
            self.ok_since = None
            return None
        if self.ok_since is None:
            self.ok_since = ts
        if ts - self.ok_since >= timedelta(seconds=CLOSE_S):
            # The incident ended when signals first came back to normal.
            inc.ended_at = self.ok_since
            self.open = None
            self.ok_since = None
            return inc
        return None


def detect(rows):
    """Run the detector over rows in time order.

    Returns (closed incidents, still open incident or None).
    """
    det = CobbleDetector()
    closed = []
    for row in rows:
        inc = det.update(row)
        if inc is not None:
            closed.append(inc)
    return closed, det.open
