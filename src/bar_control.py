# Portado de 1vtt (youtube.com/@1-vtt). Decide segurar/soltar o clique prevendo o movimento do quadrado.
from __future__ import annotations

TRACK_DEFAULTS = {
    "accel_hold": 900.0,
    "accel_release": 900.0,
    "ball_ref_px": 24.0,
    "latency_s": 0.10,
    "hysteresis_px": 6.0,
    "aim_offset": 0.0,
    "zone_hold_s": 1.0,
    "lost_timeout_s": 1.5,
}


class Motion:
    def __init__(self, alpha: float = 0.8, beta: float = 0.6) -> None:
        self.alpha, self.beta = alpha, beta
        self.y = self.v = None
        self.t = None

    def reset(self, y: float, t: float) -> None:
        self.y, self.v, self.t = float(y), 0.0, t

    def predict(self, t: float, a: float) -> tuple[float, float]:
        dt = max(0.0, t - self.t)
        return self.y + self.v * dt + 0.5 * a * dt * dt, self.v + a * dt

    def update(self, y_meas: float, t: float, a: float, jump: float) -> None:
        if self.y is None:
            self.reset(y_meas, t)
            return
        yp, vp = self.predict(t, a)
        dt = max(1e-3, t - self.t)
        r = y_meas - yp
        if abs(r) > jump:
            self.y, self.v = float(y_meas), vp
        else:
            self.y = yp + self.alpha * r
            self.v = vp + self.beta * r / dt
        self.t = t


class TrackController:
    def __init__(self) -> None:
        self.configure({})
        self.reset()

    def configure(self, adv: dict) -> None:
        for k, d in TRACK_DEFAULTS.items():
            try:
                setattr(self, k, float(adv.get(k, d)))
            except (TypeError, ValueError):
                setattr(self, k, float(d))
        self.ball_ref_px = max(1.0, self.ball_ref_px)

    def reset(self) -> None:
        self.ball = Motion()
        self.zone = Motion(alpha=0.6, beta=0.3)
        self.held = False
        self.bh = 0.0
        self._last_read = None
        self._last_new = 0.0
        self.zone_seen = 0.0

    def start(self, ball_y: float, zone_y: float | None, ball_h: float, now: float) -> None:
        self.reset()
        self.ball.reset(ball_y, now)
        self.zone.reset(zone_y if zone_y is not None else ball_y, now)
        self.bh = float(ball_h)
        self.zone_seen = now

    def observe(self, ball_y: float, ball_h: float, zone_top: float | None, zone_y: float | None, now: float) -> bool:
        self.bh = 0.8 * self.bh + 0.2 * float(ball_h) if self.bh > 0 else float(ball_h)
        inside = False
        read = (ball_y, zone_top)
        same = read == self._last_read and now - self._last_new < 0.15
        if not same:
            self._last_read = read
            self._last_new = now
            s = self.bh / self.ball_ref_px
            a_applied = -self.accel_hold * s if self.held else self.accel_release * s
            self.ball.update(ball_y, now, a_applied, jump=4 * self.bh)
            if zone_y is not None:
                self.zone.update(zone_y, now, 0.0, jump=4 * self.bh)
                self.zone_seen = now
        return inside

    def decide(self, now: float) -> bool | None:
        if now - self.zone_seen > self.zone_hold_s:
            self.held = False
            return None
        if now - self.zone_seen > 0.1:
            self.zone.v = 0.0
        s = self.bh / self.ball_ref_px
        a_up = self.accel_hold * s
        a_dn = self.accel_release * s
        a_now = -a_up if self.held else a_dn
        y, v = self.ball.predict(now + self.latency_s, a_now)
        ty, tv = self.zone.predict(now + self.latency_s, 0.0)
        target = ty + self.aim_offset * self.bh
        v_rel = v - tv
        if v_rel < 0:
            stop = y - v_rel * v_rel / (2 * a_dn)
        else:
            stop = y + v_rel * v_rel / (2 * a_up)
        band = self.hysteresis_px * s
        if self.held:
            self.held = stop > target - band
        else:
            self.held = stop > target + band
        return self.held
