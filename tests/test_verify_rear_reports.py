import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import verify_rear_reports as v  # noqa: E402

DAY = 86400 * 1000
NOW = 1_800_000_000_000
# 서울시청 근처 기준 카메라 1대
CAMERAS = [{"lat": 37.5665, "lon": 126.9780}, {"lat": 35.1796, "lon": 129.0756}]
INDEX = v.build_index(CAMERAS)


def report(lat, lon, age_days=0.0):
    return {"id": "r1", "lat": lat, "lon": lon, "created_at": NOW - int(age_days * DAY)}


class DecideTest(unittest.TestCase):
    def test_within_50m_is_approved(self):
        # 위도 0.0003도 ≈ 33m
        self.assertEqual(v.decide(report(37.5668, 126.9780), INDEX, NOW), "approved")

    def test_exactly_on_camera_is_approved(self):
        self.assertEqual(v.decide(report(37.5665, 126.9780), INDEX, NOW), "approved")

    def test_beyond_50m_is_pending(self):
        # 위도 0.0008도 ≈ 89m
        self.assertEqual(v.decide(report(37.5673, 126.9780), INDEX, NOW), "pending")

    def test_far_away_new_report_stays_pending(self):
        self.assertEqual(v.decide(report(37.0, 127.0, age_days=1), INDEX, NOW), "pending")

    def test_unmatched_after_7_days_is_rejected(self):
        self.assertEqual(v.decide(report(37.0, 127.0, age_days=7), INDEX, NOW), "rejected")
        self.assertEqual(v.decide(report(37.0, 127.0, age_days=6.9), INDEX, NOW), "pending")

    def test_old_but_matching_report_is_still_approved(self):
        self.assertEqual(v.decide(report(37.5665, 126.9780, age_days=30), INDEX, NOW), "approved")

    def test_missing_coordinates_are_rejected(self):
        self.assertEqual(v.decide({"id": "x", "lat": None, "lon": None, "created_at": NOW}, INDEX, NOW), "rejected")

    def test_match_across_grid_cell_boundary(self):
        # 칸 경계 근처: 카메라가 칸의 끝, 제보는 옆 칸이지만 30m 이내
        cam = [{"lat": 37.50099, "lon": 127.00000}]
        idx = v.build_index(cam)
        self.assertEqual(v.decide(report(37.50110, 127.00000), idx, NOW), "approved")

    def test_empty_camera_list(self):
        self.assertEqual(v.decide(report(37.5665, 126.9780), v.build_index([]), NOW), "pending")


class RunTest(unittest.TestCase):
    def test_dry_run_does_not_call_server(self):
        calls = []
        reports = [report(37.5665, 126.9780), report(37.0, 127.0, age_days=8), report(37.0, 127.0, age_days=1)]
        s = v.run(reports, INDEX, NOW, lambda i, st: calls.append((i, st)), dry_run=True)
        self.assertEqual(calls, [])
        self.assertEqual((s["approved"], s["rejected"], s["pending"], s["errors"]), (1, 1, 1, 0))

    def test_apply_calls_server_and_counts_errors(self):
        def flaky(report_id, status):
            if status == "rejected":
                raise RuntimeError("boom")
        reports = [report(37.5665, 126.9780), report(37.0, 127.0, age_days=8)]
        s = v.run(reports, INDEX, NOW, flaky, dry_run=False)
        self.assertEqual((s["approved"], s["rejected"], s["errors"]), (1, 0, 1))


class SupabaseUrlTest(unittest.TestCase):
    def test_url_normalization(self):
        for raw in ("https://x.supabase.co", "https://x.supabase.co/", "https://x.supabase.co/rest/v1/"):
            self.assertEqual(v.Supabase(raw, "k").url, "https://x.supabase.co")

    def test_missing_secrets_skip_without_error(self):
        old = {k: os.environ.pop(k, None) for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")}
        try:
            self.assertEqual(v.main(["nonexistent.json"]), 0)
        finally:
            for k, val in old.items():
                if val is not None:
                    os.environ[k] = val


if __name__ == "__main__":
    unittest.main()
