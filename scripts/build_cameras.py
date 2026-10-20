"""공공데이터포털 '전국무인교통단속카메라표준데이터'를 받아 cameras.json 으로 정규화한다.

사용:  DATA_GO_KR_KEY=<인증키> python scripts/build_cameras.py [출력경로]
       python scripts/build_cameras.py [출력경로] --csv <표준데이터.csv>   (인증키 없이 내려받은 CSV로 만들 때)
표준 라이브러리만 사용한다. 인증키는 환경변수로만 받고 파일에 남기지 않는다.

후면 카메라: 공공데이터에는 후면을 구분하는 항목이 없다. 사람이 확인한 후면 카메라는 rear_overrides.json 에 모아 두고,
이 스크립트가 매번 적용한다 (목록은 추가만 하고 지우지 않는다). 적용 규칙은 apply_rear_overrides() 참고.
"""
import json
import csv
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

# 후면 지정 목록(rear_overrides.json)을 공공 카메라에 연결하는 규칙
LINK_SAME_ADDRESS_M = 100  # 지번 주소가 같은 공공 카메라가 이 거리 안에 있으면 같은 카메라로 본다
LINK_NEAREST_M = 40        # 그 밖에는 이 거리 안의 가장 가까운 공공 카메라에 붙인다
LINK_BY_ID_FALLBACK_M = 10  # 관리번호가 바뀐 경우 좌표로 다시 찾을 때
OVERRIDES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rear_overrides.json")


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
        # 아래 두 값은 후면 지정을 연결할 때만 쓰고 cameras.json 에는 쓰지 않는다 (_ 로 시작)
        "_mgmt": (item.get("mnlssRegltCameraManageNo") or "").strip(),
        "_addr": normalize_address(item.get("lnmadr") or ""),
    }
    if REAR_PATTERN.search((item.get("itlpc") or "")):
        out["rear"] = True  # 후면/후방 카메라로 추정 (없으면 키를 만들지 않는다)
    return out


_PROVINCE_PREFIX = re.compile(r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)\S*\s*")


def normalize_address(addr: str) -> str:
    """'부산광역시 영도구 동삼동 1166' 과 '부산 영도구 동삼동 1166' 을 같게 만든다 (시도 이름과 공백 정리)."""
    a = re.sub(r"\s+", " ", (addr or "").strip())
    return _PROVINCE_PREFIX.sub("", a)


def load_csv_items(path: str) -> list:
    """공공데이터포털에서 내려받은 CSV(cp949 또는 utf-8)를 API 응답 항목 모양으로 바꾼다."""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("CSV 문자 코드를 읽지 못했습니다 (utf-8, cp949 모두 실패)")
    items = []
    for row in csv.DictReader(text.splitlines()):
        items.append({
            "mnlssRegltCameraManageNo": row.get("무인교통단속카메라관리번호", ""),
            "roadRouteNm": row.get("도로노선명", ""),
            "rdnmadr": row.get("소재지도로명주소", ""),
            "lnmadr": row.get("소재지지번주소", ""),
            "latitude": row.get("위도", ""),
            "longitude": row.get("경도", ""),
            "itlpc": row.get("설치장소", ""),
            "regltSe": row.get("단속구분", ""),
            "lmttVe": row.get("제한속도", ""),
        })
    return items


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


def apply_rear_overrides(items: list, entries: list) -> dict:
    """rear_overrides.json 의 항목을 정규화된 카메라 목록(items)에 적용한다. items 는 제자리에서 바뀌고 추가될 수 있다.

    규칙
      1) 공공 카메라 관리번호(J6729 같은 번호)로 지정된 항목: 그 번호의 카메라를 후면으로 한다.
         번호가 없어졌으면 좌표 10m 이내 가장 가까운 카메라, 그것도 없으면 지정한 좌표에 새 후면 카메라를 만든다.
      2) MY-0001 같은 사용자 지점: 지번이 같은 공공 카메라가 100m 이내에 있으면 그 카메라, 아니면 40m 이내의
         가장 가까운 공공 카메라를 후면으로 한다. 둘 다 없으면 지정한 좌표에 새 후면 카메라를 만든다.
      항목을 지우지는 않는다. 반환값은 결과 요약(연결/새로 만듦/확인 필요 목록).
    """
    by_mgmt = {}
    for it in items:
        if it.get("_mgmt"):
            by_mgmt.setdefault(it["_mgmt"], it)
    by_addr = {}
    for it in items:
        if it.get("_addr"):
            by_addr.setdefault(it["_addr"], []).append(it)
    base = list(items)

    def nearest(entry, pool, limit_m):
        best, best_d = None, None
        for it in pool:
            if abs(it["lat"] - entry["lat"]) > 0.02 or abs(it["lon"] - entry["lon"]) > 0.02:
                continue
            d = distance_m(it, entry)
            if d <= limit_m and (best_d is None or d < best_d):
                best, best_d = it, d
        return best, best_d

    report = {"linked": [], "created": [], "review": []}
    for e in entries:
        target, how = None, ""
        if not e["id"].startswith("MY-"):
            target = by_mgmt.get(e["id"])
            how = "관리번호"
            if target is None and e.get("lat") is not None:
                target, _ = nearest(e, base, LINK_BY_ID_FALLBACK_M)
                how = "좌표(관리번호 없음)"
                if target is not None:
                    report["review"].append((e["id"], "관리번호가 데이터에 없어 좌표로 찾았습니다"))
        else:
            if e.get("addr"):
                same = by_addr.get(normalize_address(e["addr"]), [])
                target, _ = nearest(e, same, LINK_SAME_ADDRESS_M)
                how = "같은 지번"
            if target is None:
                target, _ = nearest(e, base, LINK_NEAREST_M)
                how = "가장 가까운 카메라"
        if target is not None:
            target["rear"] = True
            report["linked"].append((e["id"], how, target.get("_mgmt", ""), target["name"]))
        elif e.get("lat") is not None and e.get("lon") is not None:
            items.append({
                "lat": round(e["lat"], 6),
                "lon": round(e["lon"], 6),
                "kind": "other",
                "limit": 0,
                "name": (e.get("name") or "").strip() or "후면 카메라(직접 추가)",
                "road": "",
                "rear": True,
                "_mgmt": e["id"],
                "_addr": normalize_address(e.get("addr", "")),
            })
            report["created"].append((e["id"], e.get("addr", "")))
        else:
            report["review"].append((e["id"], "연결할 카메라도 좌표도 없습니다"))
    return report


def load_overrides(path: str = OVERRIDES_PATH) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("entries", [])


def public_view(c: dict) -> dict:
    """cameras.json 에 쓸 필드만 남긴다 (_ 로 시작하는 연결용 값은 뺀다)."""
    return {k: v for k, v in c.items() if not k.startswith("_")}


def main() -> int:
    args = sys.argv[1:]
    csv_path = None
    if "--csv" in args:
        i = args.index("--csv")
        csv_path = args[i + 1]
        del args[i:i + 2]
    out = args[0] if args else "cameras.json"

    if csv_path:
        raw = load_csv_items(csv_path)
        print(f"CSV에서 읽음: {len(raw)}")
    else:
        key = os.environ.get("DATA_GO_KR_KEY", "").strip()
        if not key:
            print("DATA_GO_KR_KEY 환경변수가 필요합니다 (또는 --csv 로 CSV 파일을 지정).", file=sys.stderr)
            return 1
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
    entries = load_overrides()
    report = apply_rear_overrides(normalized, entries)  # 합치기 전에 적용해서 후면 표시가 합쳐지며 사라지지 않게 한다
    merged = merge_close(normalized)
    # 안정적인 순서로 정렬해 불필요한 diff를 줄인다.
    merged.sort(key=lambda c: (c["lat"], c["lon"], c["kind"]))
    for i, c in enumerate(merged, 1):
        c["id"] = i
    merged = [public_view(c) for c in merged]
    rear_total = sum(1 for c in merged if c.get("rear"))
    print(f"정규화: {len(normalized) - len(report['created'])}, 병합 후: {len(merged)} (버림 {len(raw) - (len(normalized) - len(report['created']))})")
    print(
        f"후면 지정 {len(entries)}건: 기존 카메라에 연결 {len(report['linked'])}, 새로 만듦 {len(report['created'])}, "
        f"확인 필요 {len(report['review'])} / 후면 카메라 합계 {rear_total}"
    )
    for eid, why in report["review"]:
        print(f"  확인 필요: {eid}: {why}")

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
