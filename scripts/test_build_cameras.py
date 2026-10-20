"""build_cameras.py 의 후면 지정 적용 규칙 테스트.  실행: python scripts/test_build_cameras.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_cameras as b  # noqa: E402


def cam(lat, lon, mgmt="", addr="", kind="signal", limit=50, name="카메라"):
    return {"lat": lat, "lon": lon, "kind": kind, "limit": limit, "name": name, "road": "",
            "_mgmt": mgmt, "_addr": b.normalize_address(addr)}


def entry(eid, lat, lon, addr="", name=""):
    return {"id": eid, "addr": addr, "name": name, "lat": lat, "lon": lon}


class NormalizeAddress(unittest.TestCase):
    def test_province_prefix_and_spacing(self):
        self.assertEqual("영도구 동삼동 1166", b.normalize_address("부산광역시 영도구 동삼동 1166"))
        self.assertEqual("영도구 동삼동 1166", b.normalize_address("부산 영도구  동삼동 1166"))
        self.assertEqual("서구 남부민동 695", b.normalize_address("부산광역시 서구 남부민동 695"))
        self.assertEqual("", b.normalize_address(""))


class ApplyRearOverrides(unittest.TestCase):
    def test_link_by_management_number(self):
        items = [cam(35.0, 129.0, mgmt="J1", addr="부산 가동 1"), cam(35.1, 129.1, mgmt="J2")]
        rep = b.apply_rear_overrides(items, [entry("J1", 35.0, 129.0)])
        self.assertTrue(items[0].get("rear"))
        self.assertFalse(items[1].get("rear"))
        self.assertEqual(1, len(rep["linked"]))
        self.assertEqual(2, len(items))

    def test_same_address_within_100m_links_even_if_beyond_40m(self):
        far = cam(35.0000, 129.0000, mgmt="A", addr="부산 영도구 동삼동 1125-24")      # 같은 지번
        near = cam(35.0004, 129.0000, mgmt="B", addr="부산 영도구 동삼동 9")            # 약 44m, 다른 지번
        items = [far, near]
        # 사용자 점은 far 에서 약 66m, near 에서 약 22m 떨어진 곳
        b.apply_rear_overrides(items, [entry("MY-0001", 35.0006, 129.0000, addr="부산광역시 영도구 동삼동 1125-24")])
        self.assertTrue(far.get("rear"))
        self.assertFalse(near.get("rear"))

    def test_nearest_within_40m_when_no_same_address(self):
        a = cam(35.0000, 129.0000, mgmt="A", addr="가")
        c = cam(35.0002, 129.0000, mgmt="C", addr="나")   # 약 22m
        items = [a, c]
        b.apply_rear_overrides(items, [entry("MY-0001", 35.00025, 129.0000, addr="다 1")])
        self.assertTrue(c.get("rear"))
        self.assertFalse(a.get("rear"))

    def test_creates_standalone_when_nothing_close(self):
        items = [cam(35.0, 129.0, mgmt="A", addr="가")]
        rep = b.apply_rear_overrides(items, [entry("MY-0007", 35.5, 129.5, addr="멀리 1", name="")])
        self.assertEqual(2, len(items))
        new = items[1]
        self.assertTrue(new["rear"])
        self.assertEqual("other", new["kind"])
        self.assertEqual("후면 카메라(직접 추가)", new["name"])
        self.assertEqual(1, len(rep["created"]))

    def test_same_address_but_far_is_not_linked(self):
        # 다른 도시의 같은 구 이름/지번이라도 거리가 멀면 연결하지 않는다
        items = [cam(37.5, 127.0, mgmt="S", addr="서구 남부민동 695")]
        rep = b.apply_rear_overrides(items, [entry("MY-0002", 35.09, 129.02, addr="부산 서구 남부민동 695")])
        self.assertFalse(items[0].get("rear"))
        self.assertEqual(1, len(rep["created"]))

    def test_management_number_missing_falls_back_to_coordinates(self):
        items = [cam(35.0, 129.0, mgmt="NEW", addr="가")]
        rep = b.apply_rear_overrides(items, [entry("J9", 35.00003, 129.0)])
        self.assertTrue(items[0].get("rear"))
        self.assertEqual(1, len(rep["review"]))  # 사람이 알 수 있게 알린다

    def test_overrides_are_idempotent(self):
        items = [cam(35.0, 129.0, mgmt="J1", addr="가")]
        entries = [entry("J1", 35.0, 129.0), entry("MY-0001", 35.5, 129.5)]
        b.apply_rear_overrides(items, entries)
        self.assertEqual(2, len(items))  # 기존 1 + 새로 만든 1
        b.apply_rear_overrides(items, entries)
        # 같은 입력으로 다시 적용해도 점이 더 늘어나지 않는다 (먼저 만든 점에 연결된다)
        self.assertEqual(2, len(items))


class MergePreservesRear(unittest.TestCase):
    def test_rear_survives_when_marked_camera_is_merged_away(self):
        first = cam(35.00000, 129.0, mgmt="A", addr="가")
        marked = cam(35.00010, 129.0, mgmt="B", addr="나")  # 약 11m, 같은 종류/제한속도 -> 합쳐짐
        marked["rear"] = True
        kept = b.merge_close([first, marked])
        self.assertEqual(1, len(kept))
        self.assertTrue(kept[0].get("rear"))

    def test_different_kind_is_not_merged(self):
        a = cam(35.0, 129.0, kind="speed")
        c = cam(35.0001, 129.0, kind="signal")
        c["rear"] = True
        kept = b.merge_close([a, c])
        self.assertEqual(2, len(kept))
        self.assertFalse(kept[0].get("rear"))


class PublicView(unittest.TestCase):
    def test_internal_fields_are_not_written(self):
        v = b.public_view({"lat": 1, "lon": 2, "name": "x", "_mgmt": "J1", "_addr": "a", "rear": True})
        self.assertEqual({"lat": 1, "lon": 2, "name": "x", "rear": True}, v)


if __name__ == "__main__":
    unittest.main(verbosity=2)
