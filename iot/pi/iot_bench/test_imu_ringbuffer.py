#!/usr/bin/env python3
"""IMU 링버퍼 테스트 — 하드웨어 없이 돈다.

핵심 검증은 test_wall_clock_jump: NTP 점프가 나도 잘린 구간 길이가 유지되는지.
"""

import math
import time
import unittest

from imu_ringbuffer import (
    NS, ImuRingBuffer, ImuSample, ImuCollector, SyntheticImuSource,
    summarize, write_jsonl,
)


def make_buffer(hz=50, seconds=35.0, count=None, t0_mono=10**12, t0_wall=1_789_000_000 * NS):
    """합성 샘플로 채운 버퍼. 시각을 직접 지정해 결정적으로 테스트한다."""
    buf = ImuRingBuffer(hz=hz, seconds=seconds)
    n = count if count is not None else buf.capacity
    step = NS // hz
    for i in range(n):
        buf.append(ImuSample(t0_mono + i * step, t0_wall + i * step,
                             0.0, 0.0, 9.8, 0.1, 0.1, 0.0))
    return buf


class TestRingBuffer(unittest.TestCase):

    def test_capacity_evicts_oldest(self):
        buf = make_buffer(hz=50, seconds=2.0)          # 용량 100
        self.assertEqual(buf.capacity, 100)
        self.assertEqual(len(buf), 100)
        first = buf.snapshot()[0].mono_ns
        buf.append(ImuSample(10**13, 10**13, 0, 0, 0, 0, 0, 0))
        self.assertEqual(len(buf), 100)                # 늘지 않는다
        self.assertGreater(buf.snapshot()[0].mono_ns, first)   # 가장 오래된 게 밀려났다

    def test_monotonic_strictly_increasing(self):
        buf = make_buffer(count=500)
        m = [s.mono_ns for s in buf.snapshot()]
        self.assertEqual(m, sorted(m))
        self.assertEqual(len(set(m)), len(m))

    def test_cut_exact_30s(self):
        buf = make_buffer()                             # 35초 가득
        s = buf.snapshot()
        t0 = s[-1].wall_ns
        cut = buf.cut_by_wall(t0, pre_s=30.0)
        self.assertAlmostEqual(cut.span_s, 30.0, places=2)
        self.assertEqual(len(cut), 30 * 50 + 1)         # 경계 포함
        self.assertFalse(cut.truncated)
        self.assertAlmostEqual(cut.anchor_error_ms, 0.0, places=3)

    def test_cut_reports_truncation(self):
        buf = make_buffer(count=10 * 50)                # 10초분만
        t0 = buf.snapshot()[-1].wall_ns
        cut = buf.cut_by_wall(t0, pre_s=30.0)
        self.assertTrue(cut.truncated)                  # 30초를 못 채웠다고 보고
        self.assertLess(cut.span_s, 30.0)

    def test_cut_with_post_window(self):
        buf = make_buffer()
        s = buf.snapshot()
        mid = s[len(s) // 2]
        cut = buf.cut_by_wall(mid.wall_ns, pre_s=10.0, post_s=5.0)
        self.assertAlmostEqual(cut.span_s, 15.0, places=2)

    def test_wall_clock_jump_preserves_span(self):
        """NTP 점프 후에도 잘린 구간 길이가 정확히 유지되는지.

        이게 monotonic 을 기준으로 잡은 이유다. wall clock 으로 창을 계산하면
        점프한 만큼 구간이 늘거나 줄어든다.
        """
        hz, jump_s = 50, 7.0
        buf = ImuRingBuffer(hz=hz, seconds=35.0)
        step = NS // hz
        t_mono, t_wall = 10**12, 1_789_000_000 * NS
        n = buf.capacity

        for i in range(n):
            mono = t_mono + i * step
            wall = t_wall + i * step
            if i >= n // 2:                      # 중간에 시계가 +7초 점프
                wall += int(jump_s * NS)
            buf.append(ImuSample(mono, wall, 0.0, 0.0, 9.8, 0.1, 0.1, 0.0))

        s = buf.snapshot()
        # wall clock 은 점프 지점에서 불연속이다
        walls = [x.wall_ns for x in s]
        gaps = [walls[i + 1] - walls[i] for i in range(len(walls) - 1)]
        self.assertGreater(max(gaps), int(jump_s * NS))   # wall clock 불연속 확인
        self.assertAlmostEqual(max(gaps) / NS, jump_s + 1 / hz, places=3)

        # 그런데 monotonic 기준 절단은 정확히 30초를 준다
        cut = buf.cut_by_wall(s[-1].wall_ns, pre_s=30.0)
        self.assertAlmostEqual(cut.span_s, 30.0, places=2)
        self.assertEqual(len(cut), 30 * hz + 1)

        # monotonic 순서는 점프와 무관하게 단조 증가
        monos = [x.mono_ns for x in cut.samples]
        self.assertEqual(monos, sorted(monos))


class TestSummary(unittest.TestCase):

    def test_stable_flag(self):
        calm = [ImuSample(i, i, 0, 0, 9.8, 0.2, 0.1, 0.05) for i in range(50)]
        rough = [ImuSample(i, i, 0, 0, 9.8, 12.0, 8.0, 3.0) for i in range(50)]
        self.assertTrue(summarize(calm)["stable"])
        self.assertFalse(summarize(rough)["stable"])

    def test_created_at_is_int_unixtime(self):
        s = [ImuSample(i, 1_789_000_123 * NS + i, 0, 0, 9.8, 0, 0, 0) for i in range(10)]
        out = summarize(s)
        self.assertIsInstance(out["created_at"], int)
        self.assertEqual(out["created_at"], 1_789_000_123)

    def test_empty(self):
        self.assertEqual(summarize([]), {})


class TestCollectorLive(unittest.TestCase):
    """실제 스레드를 돌려 주기 정확도를 본다."""

    def test_50hz_for_3s(self):
        hz, dur = 50, 3.0
        buf = ImuRingBuffer(hz=hz, seconds=35.0)
        col = ImuCollector(SyntheticImuSource(), buf, hz=hz)
        col.start()
        time.sleep(dur)
        col.stop()

        n = len(buf)
        expected = hz * dur
        self.assertGreater(n, expected * 0.9, f"샘플 부족: {n}")
        self.assertLess(n, expected * 1.1, f"샘플 과다: {n}")
        self.assertEqual(col.read_errors, 0)

        s = buf.snapshot()
        monos = [x.mono_ns for x in s]
        self.assertEqual(monos, sorted(monos))

        # 실측 주기의 평균이 20ms 근처인지
        gaps = [(monos[i + 1] - monos[i]) / 1e6 for i in range(len(monos) - 1)]
        avg = sum(gaps) / len(gaps)
        self.assertAlmostEqual(avg, 1000.0 / hz, delta=2.0)
        print(f"\n  실측 {n}샘플 / {dur}s · 평균 주기 {avg:.2f}ms "
              f"(목표 {1000/hz:.1f}ms) · 지연틱 {col.late_ticks}")

    def test_synthetic_units_sane(self):
        src = SyntheticImuSource()
        ax, ay, az, r, p, y = src.read()
        self.assertAlmostEqual(math.sqrt(ax*ax + ay*ay + az*az), 9.80665, delta=0.1)
        for v in (r, p, y):
            self.assertLess(abs(v), 60.0)     # 각속도가 deg/s 스케일인지


class TestExport(unittest.TestCase):

    def test_jsonl_roundtrip(self):
        import json, tempfile, os
        buf = make_buffer(count=100)
        with tempfile.TemporaryDirectory() as d:
            p = write_jsonl(buf.snapshot(), os.path.join(d, "imu.jsonl"))
            lines = p.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 100)
            first = json.loads(lines[0])
            for k in ("mono_ns", "created_at_ns", "accel_x", "roll"):
                self.assertIn(k, first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
