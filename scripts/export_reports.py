"""서버(Supabase)의 승인된 공유 제보를 엑셀(.xls/.xlsx)의 '제보' '단속' '통제' 시트에 추가한다. (삭제는 하지 않는다)

사용:  python scripts/export_reports.py <엑셀 파일> [--props <앱의 local.properties>] [--json <테스트용 JSON>]
필요:  pip install xlrd (가장 가까운 공공 카메라를 찾을 때만), Windows + Excel (시트에 쓸 때)
주의:  엑셀 파일을 **닫은 상태**에서 실행한다 (열려 있으면 쓰지 않고 멈춘다).
       키는 local.properties 에서 읽기만 하고 출력/저장하지 않는다. 읽기 전용(공개 키)이라 승인된 제보만 보인다.
       제보한 사람의 ID(reporter_id)는 가져오지 않는다.

시트
  제보 = 후면/후방 카메라(rear_camera)   단속 = 실시간 단속(realtime)   통제 = 통제(control)
  같은 제보ID 는 다시 적지 않는다. 열: 제보ID, 접수시각, 상태, 위도, 경도, 메모, 확인, 부인, 가까운 공공 카메라, 거리(m), 관리번호, 처리
  '처리' 칸은 사람이 쓰는 칸이다 (예: "내가 아님" 이라고 적어 두고, 서버에서는 앱의 관리자 화면으로 삭제한다).
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROPS = os.path.join(HERE, "..", "..", "app-baedal-v2", "local.properties")
KST = timezone(timedelta(hours=9))

SHEETS = [
    ("제보", "rear_camera"),
    ("단속", "realtime"),
    ("통제", "control"),
]
HEADERS = ["제보ID", "접수시각", "상태", "위도", "경도", "메모", "확인", "부인",
           "가까운 공공 카메라", "거리(m)", "관리번호", "처리"]
SELECT = "id,category,status,lat,lon,memo,confirm_count,deny_count,created_at"


def read_props(path):
    props = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    return props


def fetch_reports(props):
    url = props.get("SUPABASE_URL", "").rstrip("/")
    key = props.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise SystemExit("local.properties 에 SUPABASE_URL / SUPABASE_ANON_KEY 가 없습니다.")
    cats = ",".join(c for _, c in SHEETS)
    out, offset = [], 0
    while True:
        endpoint = (f"{url}/rest/v1/shared_reports?select={SELECT}&category=in.({cats})"
                    f"&order=created_at.asc&limit=1000&offset={offset}")
        req = urllib.request.Request(endpoint, headers={"apikey": key, "Authorization": "Bearer " + key})
        page = json.load(urllib.request.urlopen(req, timeout=30))
        out += page
        if len(page) < 1000:
            return out
        offset += 1000


def load_official(xls_path):
    """엑셀 첫 시트에서 (위도, 경도, 관리번호, 설치장소) 목록을 만든다. 못 읽으면 빈 목록."""
    try:
        import xlrd
    except ImportError:
        print("xlrd 가 없어 가까운 공공 카메라는 비워 둡니다 (pip install xlrd).")
        return []
    sh = xlrd.open_workbook(xls_path).sheet_by_index(0)
    head = next(r for r in range(min(5, sh.nrows)) if str(sh.cell_value(r, 0)).strip() == "무인교통단속카메라관리번호")
    cams = []
    for r in range(head + 1, sh.nrows):
        try:
            la, lo = float(sh.cell_value(r, 9)), float(sh.cell_value(r, 10))
        except (TypeError, ValueError):
            continue
        cams.append((la, lo, str(sh.cell_value(r, 0)).strip(), str(sh.cell_value(r, 11)).strip()))
    return cams


def distance_m(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def nearest_camera(lat, lon, cams, limit_m=200):
    best = None
    for la, lo, mg, name in cams:
        if abs(la - lat) > 0.01 or abs(lo - lon) > 0.01:
            continue
        d = distance_m(lat, lon, la, lo)
        if d <= limit_m and (best is None or d < best[0]):
            best = (d, mg, name)
    return best


def status_label(s):
    return {"approved": "승인", "pending": "대기", "rejected": "반려", "hidden": "숨김"}.get(s, s)


def to_rows(reports, cams):
    sheets = []
    for name, category in SHEETS:
        rows = []
        for r in (x for x in reports if x["category"] == category):
            near = nearest_camera(r["lat"], r["lon"], cams) if category == "rear_camera" and cams else None
            when = datetime.fromtimestamp(r["created_at"] / 1000, KST).strftime("%Y-%m-%d %H:%M:%S")
            rows.append([
                r["id"], when, status_label(r["status"]), r["lat"], r["lon"], r.get("memo") or "",
                r.get("confirm_count") or 0, r.get("deny_count") or 0,
                near[2] if near else "", round(near[0]) if near else "", near[1] if near else "", "",
            ])
        sheets.append({"name": name, "headers": HEADERS, "rows": rows})
    return {"sheets": sheets}


def main(argv):
    args = argv[1:]
    if not args:
        print(__doc__)
        return 1
    xls = args[0]
    props_path = DEFAULT_PROPS
    json_path = None
    if "--props" in args:
        props_path = args[args.index("--props") + 1]
    if "--json" in args:
        json_path = args[args.index("--json") + 1]

    if json_path:
        with open(json_path, encoding="utf-8") as f:
            reports = json.load(f)
    else:
        reports = fetch_reports(read_props(props_path))
    print(f"서버에서 읽은 제보: {len(reports)}건 " + str({n: sum(1 for x in reports if x['category'] == c) for n, c in SHEETS}))

    cams = load_official(xls) if any(x["category"] == "rear_camera" for x in reports) else []
    payload = to_rows(reports, cams)
    tmp = os.path.join(tempfile.gettempdir(), "export_reports.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    ps1 = os.path.join(HERE, "append_reports.ps1")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Path", os.path.abspath(xls), "-JsonPath", tmp],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))
