# Portado de 1vtt (youtube.com/@1-vtt), macro original em ../slayers-2-fishing-windows. Detecta o quadrado branco e a zona verde.
from dataclasses import dataclass
from typing import Optional
import time

import cv2
import numpy as np

BALL_MIN = 90
BALL_MAX = 150
BALL_SAT = 120
BRIDGE = 7
ERODE = 5
SIDE_MIN, SIDE_MAX = 8, 90
FILL_MIN = 0.6
CANDIDATES = 8

HW_LO, HW_HI = 0.95, 1.75
ZH_LO, ZH_HI = 1.1, 2.6
ZH_GUESS = 1.8
PAD = 0.25
THICK = 0.125
KERNEL = 0.22

TINT = 50.0
LINE = 40.0
TINT_CAP, LINE_CAP = 60.0, 100.0
TINT_FLOOR, LINE_FLOOR = -20.0, -20.0
LINE_MIN = 10.0
SCORE_MIN = 1.0
NEAR_BONUS = 0.25
NEAR_AGE = 0.4
LOCK_HITS = 3
LOCK_AGE = 1.5
PEEK = 0.5
HW_GUESS = 1.35
EDGE_ON = 12.0
EDGE_RUN = 0.5
EDGES_MIN = 2

OVERLAY_BGR = ((255, 80, 255), (255, 255, 80))
OVERLAY_TOL = 10
OVERLAY_DARK = 30
FILL_REACH = 16


@dataclass
class Game:
    ball_x: float
    ball_y: float
    ball_w: int
    ball_h: int
    zone_x0: Optional[int]
    zone_x1: Optional[int]
    zone_top: Optional[int]
    zone_bot: Optional[int]

    @property
    def has_zone(self):
        return self.zone_top is not None

    @property
    def zone_y(self):
        if self.zone_top is None:
            return None
        return (self.zone_top + self.zone_bot) / 2.0

    @property
    def zone_h(self):
        if self.zone_top is None:
            return None
        return self.zone_bot - self.zone_top + 1

    @property
    def zone_x(self):
        if self.zone_x0 is None:
            return None
        return (self.zone_x0 + self.zone_x1) / 2.0


def ball_mask(bgr):
    b, g, r = cv2.split(bgr)
    mn = cv2.min(cv2.min(b, g), r)
    mx = cv2.max(cv2.max(b, g), r)
    sat = cv2.subtract(mx, mn)
    m = (mn >= BALL_MIN) & (mx >= BALL_MAX) & (sat <= BALL_SAT)
    m = m.view(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((BRIDGE, 1), np.uint8))
    return cv2.erode(m, np.ones((ERODE, ERODE), np.uint8))


def greenness(bgr):
    b, g, r = cv2.split(bgr)
    return cv2.subtract(cv2.max(r, g), b, dtype=cv2.CV_32F)


def overlay_mask(bgr):
    solid = None
    for col in OVERLAY_BGR:
        lo = np.array([max(0, c - OVERLAY_TOL) for c in col], np.uint8)
        hi = np.array([min(255, c + OVERLAY_TOL) for c in col], np.uint8)
        part = cv2.inRange(bgr, lo, hi)
        solid = part if solid is None else cv2.bitwise_or(solid, part)
    if not solid.any():
        return None
    dark = cv2.inRange(bgr, np.array([0, 0, 0], np.uint8), np.array([OVERLAY_DARK] * 3, np.uint8))
    rim = cv2.bitwise_and(cv2.dilate(solid, np.ones((3, 3), np.uint8)), dark)
    return cv2.bitwise_or(solid, rim)


def fill_masked(G, mask):
    high = G.copy()
    high[mask != 0] = 1e6
    low = cv2.erode(high, np.ones((1, 2 * FILL_REACH + 1), np.uint8))
    low[low > 1e5] = 0.0
    return np.where(mask != 0, low, G)


def _run(covered):
    if covered.all():
        return 1.0
    d = np.diff(np.concatenate(([0], covered.view(np.uint8), [0])))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    return (ends - starts).max() / float(len(covered)) if len(starts) else 0.0


def _edges(T, unk, xl, xr, t, zh):
    bands = (
        (T[t - 1:t + 3, xl:xr + 1], unk[t - 1:t + 3, xl:xr + 1], 0),
        (T[t + zh - 3:t + zh + 1, xl:xr + 1], unk[t + zh - 3:t + zh + 1, xl:xr + 1], 0),
        (T[t:t + zh, xl - 1:xl + 3], unk[t:t + zh, xl - 1:xl + 3], 1),
        (T[t:t + zh, xr - 2:xr + 2], unk[t:t + zh, xr - 2:xr + 2], 1),
    )
    n = 0
    for band, hidden, axis in bands:
        covered = (band.max(axis=axis) >= EDGE_ON) | hidden.any(axis=axis)
        if _run(covered) >= EDGE_RUN:
            n += 1
    return n


class Detector:
    def __init__(self):
        self.last = ""
        self.last_boxes = []
        self._lock = None
        self._hits = 0
        self._seen = 0.0
        self._prev = None
        self._best_score = 0.0
        self._why = ""

    def find(self, bgr, offset=(0, 0), near=None) -> Optional[Game]:
        H, W = bgr.shape[:2]
        ox, oy = offset
        now = time.perf_counter()
        if now - self._seen > LOCK_AGE:
            self._lock = None
            self._hits = 0
        m = ball_mask(bgr)
        n, lab, st, cen = cv2.connectedComponentsWithStats(m)
        cands = []
        for i in range(1, n):
            x, y, w, h, area = st[i]
            if not (SIDE_MIN <= w <= SIDE_MAX and SIDE_MIN <= h <= SIDE_MAX):
                continue
            if not (0.6 <= w / float(h) <= 1.6) or area < FILL_MIN * w * h:
                continue
            cands.append((int(area), x + w / 2.0, y + h / 2.0, w + ERODE - 1, h + ERODE - 1))
        self.last_boxes = [(int(c[1] - c[3] / 2) + ox, int(c[2] - c[4] / 2) + oy, c[3], c[4]) for c in cands]
        if not cands:
            self.last = "no bright squares"
            return None
        if near is not None:
            nx, ny = near[0] - ox, near[1] - oy
            cands.sort(key=lambda c: (c[1] - nx) ** 2 + (c[2] - ny) ** 2)
        else:
            cands.sort(key=lambda c: -c[0])

        G = greenness(bgr)
        mask = overlay_mask(bgr)
        if mask is not None:
            G = fill_masked(G, mask)
        unknown = mask if mask is not None else np.zeros(G.shape, np.uint8)

        fallback = None
        best = None
        self._best_score = 0.0
        self._why = ""
        for area, cx, cy, bw, bh in cands[:CANDIDATES]:
            if near is not None:
                nx, ny = near[0] - ox, near[1] - oy
                if abs(cx - nx) > 3 * bw or abs(cy - ny) > 12 * bh:
                    continue
            zone = self._zone(G, unknown, cx, cy, bw, bh, oy, now)
            if zone is None:
                if near is not None and fallback is None:
                    fallback = Game(cx + ox, cy + oy, bw, bh, None, None, None, None)
                continue
            if best is None or zone[4] > best[1][4]:
                best = ((cx, cy, bw, bh), zone)
            if near is not None:
                break
        if best is None:
            self.last = "%d bright square%s, best zone score %.2f%s" % (
                len(cands), "" if len(cands) == 1 else "s", self._best_score, self._why)
            return fallback
        (cx, cy, bw, bh), (x0, x1, top, bot, score) = best
        self._remember(top, bot, x0, x1, cx, oy, now)
        self.last = "found (zone score %.2f)" % score
        return Game(cx + ox, cy + oy, bw, bh, x0 + ox, x1 + ox, top + oy, bot + oy)

    def _remember(self, top, bot, x0, x1, cx, oy, now):
        hw = (x1 - x0) // 2
        zh = bot - top + 1
        dx = int(round((x0 + x1) / 2.0 - cx))
        if self._prev is not None and abs(hw - self._prev[1]) <= 1 and abs(zh - self._prev[2]) <= 2:
            self._hits += 1
        else:
            self._hits = 1
        if self._hits >= LOCK_HITS:
            self._lock = (hw, zh, dx)
        self._prev = ((top + bot) / 2.0 + oy, hw, zh, dx)
        self._seen = now

    def _zone(self, G, unknown, cx, cy, bw, bh, oy, now):
        H, W = G.shape
        bs = 0.5 * (bw + bh)
        pad = max(4, int(round(PAD * bs)))
        thick = max(2, int(round(THICK * bs)))
        k = max(3, int(round(KERNEL * bs)) | 1)
        hw_lo, hw_hi = max(thick + 2, int(round(HW_LO * bs))), int(round(HW_HI * bs))
        zh_lo, zh_hi = max(2 * thick + 4, int(round(ZH_LO * bs))), int(round(ZH_HI * bs))
        if self._lock is not None:
            hw_hi = max(hw_hi, self._lock[0] + 1)
            zh_hi = max(zh_hi, self._lock[1] + 1)
        reach = hw_hi + pad + 3
        m = zh_hi // 2 + pad + thick + 4
        icx, icy = int(round(cx)), int(round(cy))
        x0, x1 = icx - reach, icx + reach + 1
        win = cv2.copyMakeBorder(G[:, max(0, x0):min(W, x1)], m, m, m + max(0, -x0), m + max(0, x1 - W),
                                 cv2.BORDER_REPLICATE)
        unk = cv2.copyMakeBorder(unknown[:, max(0, x0):min(W, x1)], m, m, m + max(0, -x0), m + max(0, x1 - W),
                                 cv2.BORDER_CONSTANT, value=0)
        Hp, Wp = win.shape
        cxw = icx - x0 + m

        bx0, bx1 = max(0, cxw - bw // 2 - 2), min(Wp, cxw + bw // 2 + 3)
        by0, by1 = max(0, icy + m - bh // 2 - 2), min(Hp, icy + m + bh // 2 + 3)
        fx0, fx1 = max(0, bx0 - 3), min(Wp, bx1 + 3)
        fy0, fy1 = max(0, by0 - 3), min(Hp, by1 + 3)
        frame_area = (fx1 - fx0) * (fy1 - fy0) - (bx1 - bx0) * (by1 - by0)
        if frame_area > 0:
            win[by0:by1, bx0:bx1] = (win[fy0:fy1, fx0:fx1].sum() - win[by0:by1, bx0:bx1].sum()) / frame_area
        unk[by0:by1, bx0:bx1] = 1

        T = win - cv2.morphologyEx(win, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
        IG = np.ascontiguousarray(cv2.integral(win).T)
        IT = np.ascontiguousarray(cv2.integral(T).T)

        prev_i = None
        if self._prev is not None and now - self._seen < NEAR_AGE:
            prev_i = self._prev[0] - oy + m

        best = [None]

        def consider(hw, zh, dx):
            c = cxw + dx
            xl, xr = c - hw, c + hw
            T0 = m - zh // 2

            def strip(I, a, b):
                return I[b] - I[a]

            def rows(C, a, b):
                return C[T0 + b:T0 + b + H] - C[T0 + a:T0 + a + H]

            wi = xr + 1 - 2 * thick - xl
            hi = zh - 2 * thick
            ci = strip(IG, xl + thick, xr + 1 - thick)
            ti = strip(IT, xl + thick, xr + 1 - thick)
            to = strip(IT, xl - 1, xr + 2)
            tl = strip(IT, xl - 1 - pad, xl - 1)
            tr = strip(IT, xr + 2, xr + 2 + pad)
            t_in = rows(ti, thick, zh - thick)
            rough = t_in / float(wi * hi)

            inner = rows(ci, thick, zh - thick) / float(wi * hi)
            above = rows(ci, -1 - pad, -1) / float(wi * pad)
            below = rows(ci, zh + 1, zh + 1 + pad) / float(wi * pad)
            tint = inner - np.maximum(above, below) - rough

            perim = 2.0 * (2 * hw + 1) + 2.0 * zh
            band = (2 * hw + 3) * (zh + 2) - wi * hi
            on = (rows(to, -1, zh + 1) - t_in) / (2.0 * perim)
            off = (rows(ti, -1 - pad, -1) + rows(ti, zh + 1, zh + 1 + pad)
                   + rows(tl, thick, zh - thick) + rows(tr, thick, zh - thick))
            off = np.maximum(off / float(2 * wi * pad + 2 * pad * hi), rough) * band / (2.0 * perim)
            line = on - off

            score = (np.minimum(np.maximum(tint, TINT_FLOOR), TINT_CAP) / TINT
                     + np.minimum(np.maximum(line, LINE_FLOOR), LINE_CAP) / LINE)
            if prev_i is not None:
                centre = T0 + np.arange(H) + zh / 2.0
                score = score + NEAR_BONUS * (np.abs(centre - prev_i) <= zh)
            i = int(np.argmax(score))
            if best[0] is None or score[i] > best[0][0]:
                best[0] = (float(score[i]), i, hw, zh, dx, float(tint[i]), float(line[i]), T0)

        if self._lock is not None:
            hw0, zh0, dx0 = self._lock
            hw0 = max(hw_lo, min(hw_hi, hw0))
            for hw, zh, dx in ((hw0, zh0, dx0), (hw0, zh0 - 1, dx0), (hw0, zh0 + 1, dx0),
                               (hw0, zh0, dx0 - 1), (hw0, zh0, dx0 + 1), (hw0 - 1, zh0, dx0), (hw0 + 1, zh0, dx0)):
                consider(max(hw_lo, min(hw_hi, hw)), max(zh_lo, min(zh_hi, zh)), dx)
        else:
            hw_g = max(hw_lo, min(hw_hi, int(round(HW_GUESS * bs))))
            zh_g = max(zh_lo, min(zh_hi, int(round(ZH_GUESS * bs))))
            for f in (1.0, 1.25, 0.8):
                consider(hw_g, max(zh_lo, min(zh_hi, int(round(f * zh_g)))), 0)
            if best[0][0] < PEEK * SCORE_MIN:
                self._best_score = max(self._best_score, best[0][0])
                return None
            for hw in range(hw_lo, hw_hi + 1):
                consider(hw, best[0][3], 0)
            hw1 = best[0][2]
            for zh in range(zh_lo, zh_hi + 1, 2):
                consider(hw1, zh, 0)
            zh1 = best[0][3]
            for hw in (hw1 - 1, hw1, hw1 + 1):
                for zh in (zh1 - 1, zh1, zh1 + 1):
                    for dx in (-2, 0, 2):
                        consider(max(hw_lo, min(hw_hi, hw)), max(zh_lo, min(zh_hi, zh)), dx)

        score, i, hw, zh, dx, tint, line, T0 = best[0]
        self._best_score = max(self._best_score, score)
        if line < LINE_MIN or score < SCORE_MIN:
            return None
        t = T0 + i
        xl, xr = cxw + dx - hw, cxw + dx + hw
        if _edges(T, unk, xl, xr, t, zh) < EDGES_MIN:
            self._why = " (edges broken)"
            return None
        top = t - m
        c = cxw + dx + x0 - m
        return int(c - hw), int(c + hw), int(top), int(top + zh - 1), score
