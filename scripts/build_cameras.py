"""공공데이터포털 '전국무인교통단속카메라표준데이터'를 받아 cameras.json 으로 정규화한다.

사용:  DATA_GO_KR_KEY=<인증키> python scripts/build_cameras.py [출력경로]
표준 라이브러리만 사용한다. 인증키는 환경변수로만 받고 파일에 남기지 않는다.
"""
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://api.data.go.kr/openapi/tn_pubr_public_unmanned_traffic_camera_api"
PAGE_SIZE = 1000
MERGE_RADIUS_M = 30  # 이 거리 안의 같은 종류 카메라는 하나로 합친다
# 대한민국 대략적 경계. 이 밖의 좌표는 오입력으로 보고 버린다.
# 설치장소(itlpc) 이름에 후면/후방이 적힌 카메라를 후면 단속카메라로 표시한다.
# 공공데이터에는 카메라가 보는 방향 항목이 없어 이름으로 추정한다(주소의 '남후면' 같은 지명은 보지 않는다).
REAR_PATTERN = re.compile(r"후면|후방|전후면|배면")
LAT_RANGE = (33.0, 38.9)
LON_RANGE = (124.5, 132.0)


def fetch_page(key: str, page: int) -> dict:
    qs = urllib.parse.urlencode(
        {"serviceKey": key, "pageNo": page, "numOfRows": PAGE_SIZE, "type": "json"},
        quote_via=urllib.parse.quote,
    )
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"{ENDPOINT}?{qs}", timeout=60) as r:
                data = json.load(r)
            if data["header"]["resultCode"] != "00":
                raise RuntimeError(data["header"]["resultMsg"])
            return data
        except Exception as e:  # noqa: BLE001 - 재시도 후 마지막 오류를 던진다
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"page {page} failed: {last}")


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_int(v):
    f = to_float(v)
    return int(f) if f is not None else 0


# 단속구분(regltSe) 코드를 이름으로 바꾼다. 제한속도/장소명 분포로 추정한 매핑:
#   1 과속(제한속도 있음), 2 신호위반(교차로), 3 또는 1+2 과속+신호, 4 불법주정차(제한속도 0), 99 구간단속(시점/종점)
KIND_BY_CODE = {1: "speed", 2: "signal", 3: "speed_signal", 4: "parking", 99: "section"}


def kind_name(raw: str) -> str:
    parts = {int(p) for p in raw.replace(" ", "").split("+") if p.isdigit()}
    if parts == {1, 2}:
        return "speed_signal"
    if len(parts) == 1:
        return KIND_BY_CODE.get(next(iter(parts)), "other")
    return "other"


def normalize(item: dict):
    lat, lon = to_float(item.get("latitude")), to_float(item.get("longitude"))
    if lat is None or lon is None:
        return None
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
        return None
    name = (item.get("itlpc") or item.get("rdnmadr") or item.get("lnmadr") or "").strip()
    road = (item.get("roadRouteNm") or "").strip()
    out = {
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "kind": kind_name((item.get("regltSe") or "").strip()),
        "limit": to_int(item.get("lmttVe")),  # 제한속도 km/h, 0이면 없음
        "name": name,
        "road": road,
    }
    if REAR_PATTERN.search((item.get("itlpc") or "")):
        out["rear"] = True  # 후면/후방 카메라로 추정 (없으면 키를 만들지 않는다)
    return out


def distance_m(a, b) -> float:
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dl = math.radians(b["lon"] - a["lon"])
    x = (b["lat"] - a["lat"]) * math.pi / 180
    h = math.sin(x / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def merge_close(cameras: list) -> list:
    """같은 종류(kind, limit)이고 MERGE_RADIUS_M 이내면 먼저 나온 것만 남긴다."""
    cell = 0.0005  # 약 50m
    grid: dict = {}
    kept = []
    for c in cameras:
        cy, cx = int(c["lat"] / cell), int(c["lon"] / cell)
        dup = False
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for o in grid.get((cy + dy, cx + dx), ()):
                    if o["kind"] == c["kind"] and o["limit"] == c["limit"] and distance_m(o, c) <= MERGE_RADIUS_M:
                        if c.get("rear"):
                            o["rear"] = True  # 합쳐져도 후면 표시는 잃지 않는다
                        dup = True
                        break
                if dup:
                    break
            if dup:
                break
        if not dup:
            grid.setdefault((cy, cx), []).append(c)
            kept.append(c)
    return kept


def main() -> int:
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key:
        print("DATA_GO_KR_KEY 환경변수가 필요합니다.", file=sys.stderr)
        return 1
    out = sys.argv[1] if len(sys.argv) > 1 else "cameras.json"

    first = fetch_page(key, 1)
    total = first["body"]["totalCount"]
    pages = math.ceil(total / PAGE_SIZE)
    raw = list(first["body"]["items"]["item"])
    for p in range(2, pages + 1):
        raw += fetch_page(key, p)["body"]["items"]["item"]
    print(f"받음: {len(raw)} / 전체 {total}")
    if len(raw) < total * 0.95:
        print("받은 수가 전체의 95% 미만이라 중단합니다.", file=sys.stderr)
        return 2

    normalized = [n for n in map(normalize, raw) if n]
    merged = merge_close(normalized)
    # 안정적인 순서로 정렬해 불필요한 diff를 줄인다.
    merged.sort(key=lambda c: (c["lat"], c["lon"], c["kind"]))
    for i, c in enumerate(merged, 1):
        c["id"] = i
    print(f"정규화: {len(normalized)}, 병합 후: {len(merged)} (버림 {len(raw) - len(normalized)})")

    # 내용이 그대로면 파일을 다시 쓰지 않는다(불필요한 커밋 방지).
    if os.path.exists(out):
        try:
            with open(out, encoding="utf-8") as f:
                if json.load(f).get("cameras") == merged:
                    print("변경 없음")
                    return 0
        except (OSError, ValueError):
            pass

    doc = {
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "공공데이터포털 전국무인교통단속카메라표준데이터 (저작자표시)",
        "count": len(merged),
        "cameras": merged,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"저장: {out} ({os.path.getsize(out) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
