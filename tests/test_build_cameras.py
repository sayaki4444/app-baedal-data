import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_cameras as b  # noqa: E402


def item(itlpc, lat="35.0", lon="128.0", regltSe="1", lmttVe="50", **extra):
    d = {"latitude": lat, "longitude": lon, "regltSe": regltSe, "lmttVe": lmttVe, "itlpc": itlpc,
         "rdnmadr": "", "lnmadr": "", "roadRouteNm": ""}
    d.update(extra)
    return d


class RearTest(unittest.TestCase):
    def test_real_names_with_rear_words_are_marked(self):
        for name in ("사주교차로 후면 (사천공항→시청)", "탑리육교 후방500m(전주→순창)",
                     "사곡삼거리 후면(통영→시청)", "거제유치원 후면 (옥포공설운동장→옥포고교)"):
            self.assertTrue(b.normalize(item(name)).get("rear"), name)

    def test_similar_words_are_not_marked(self):
        for name in ("벡스코 뒤편(원동IC)", "평택대 후문", "후정동로 입구", "정문 앞"):
            self.assertNotIn("rear", b.normalize(item(name)), name)

    def test_district_name_in_address_is_not_marked(self):
        n = b.normalize(item("무릉리 입구", lnmadr="경상북도 안동시 남후면 무릉리 326-1"))
        self.assertNotIn("rear", n)

    def test_merge_keeps_rear_flag_even_if_rear_comes_second(self):
        a = b.normalize(item("A교차로 앞", lat="35.00000"))
        r = b.normalize(item("A교차로 후면", lat="35.00010"))  # 약 11m
        merged = b.merge_close([a, r])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0].get("rear"))

    def test_merge_does_not_add_rear_to_unrelated_camera(self):
        a = b.normalize(item("A교차로 앞", lat="35.00000"))
        far = b.normalize(item("B교차로 후면", lat="35.01000"))
        merged = b.merge_close([a, far])
        self.assertEqual(len(merged), 2)
        self.assertNotIn("rear", merged[0])
        self.assertTrue(merged[1].get("rear"))

    def test_other_fields_unchanged(self):
        n = b.normalize(item("X 후면", regltSe="2", lmttVe="0"))
        self.assertEqual((n["kind"], n["limit"], n["name"]), ("signal", 0, "X 후면"))


if __name__ == "__main__":
    unittest.main()
