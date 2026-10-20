"""엑셀(.xls/.xlsx)의 후면 표시를 읽어 rear_overrides.json 에 '누적'한다 (삭제는 하지 않는다).

사용:  python scripts/import_rear_sheet.py raw/전국무인교통단속카메라표준데이터-20261020.xls
필요:  pip install xlrd   (.xls 를 읽을 때만. 이 스크립트는 사람이 로컬에서 돌리는 도구이고 주간 자동 갱신에는 쓰지 않는다)

읽는 곳
  - 첫 번째 시트(Sheet1)의 X열(24번째)에 글자가 있는 행  -> 공공 카메라를 관리번호(A열)로 후면 지정
  - '후면' 시트의 데이터 행(2행부터): I열 지번주소, J열 위도, K열 경도, L열 설치장소, X열 '후면'
      A열은 비워 둬도 된다. 새 지점에는 MY-0001 처럼 번호를 붙이고, 같은 좌표의 지점이 이미 목록에 있으면 그 번호를 쓴다.
      A열에 번호를 적어 두면 그 번호의 항목을 갱신한다 (좌표를 고칠 때는 A열에 번호를 적어 두면 새 지점이 생기지 않는다).
      J열에 "35.07, 129.07" 처럼 한 쌍으로 붙여넣은 경우도 읽는다.
"""
import json
import os
import re
import sys

OVERRIDES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rear_overrides.json")
LAT_RANGE = (33.0, 38.9)
LON_RANGE = (124.5, 132.0)
REAR_SHEET_NAME = "후면"


def parse_coords(lat_cell, lon_cell):
    """J/K 두 칸 또는 J칸에 '위도, 경도' 한 쌍으로 들어온 값을 (lat, lon)으로. 못 읽으면 None."""
    def num(v):
        try:
            return float(str(v).strip())
        except ValueError:
            return None

    lat, lon = num(lat_cell), num(lon_cell)
    if lat is None or lon is None:
        pair = re.findall(r"-?\d+\.\d+", f"{lat_cell} {lon_cell}")
        if len(pair) >= 2:
            lat, lon = float(pair[0]), float(pair[1])
    if lat is None or lon is None:
        return None
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
        return None
    return round(lat, 6), round(lon, 6)


def next_point_id(existing_ids):
    nums = [int(i[3:]) for i in existing_ids if re.fullmatch(r"MY-\d{4,}", i)]
    return f"MY-{(max(nums) + 1) if nums else 1:04d}"


def merge_entries(overrides, official_marks, points):
    """overrides 에 추가/갱신만 한다. 반환: (추가 수, 갱신 수, 행->번호 매핑)."""
    added = updated = 0
    index = {e["id"]: e for e in overrides["entries"]}
    assigned = {}
    for m in official_marks:
        if m["id"] in index:
            if index[m["id"]] != {**index[m["id"]], **m}:
                index[m["id"]].update(m)
                updated += 1
        else:
            overrides["entries"].append(m)
            index[m["id"]] = m
            added += 1
    for p in points:
        row = p.pop("_row")
        if not p.get("id"):
            # A열이 비어 있어도 같은 좌표(약 10cm 이내)의 지점이 이미 목록에 있으면 그 번호를 그대로 쓴다.
            same = next((e for e in overrides["entries"]
                         if e["id"].startswith("MY-") and abs(e["lat"] - p["lat"]) < 1e-6 and abs(e["lon"] - p["lon"]) < 1e-6), None)
            if same is not None:
                p["id"] = same["id"]
                if any(same.get(k) != v for k, v in p.items()):
                    same.update(p)
                    updated += 1
                assigned[row] = p["id"]
                continue
            p["id"] = next_point_id(list(index))
            overrides["entries"].append(p)
            index[p["id"]] = p
            added += 1
        elif p["id"] in index:
            if any(index[p["id"]].get(k) != v for k, v in p.items()):
                index[p["id"]].update(p)
                updated += 1
        else:
            overrides["entries"].append(p)
            index[p["id"]] = p
            added += 1
        assigned[row] = p["id"]
    return added, updated, assigned


def load_overrides():
    if os.path.exists(OVERRIDES):
        with open(OVERRIDES, encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "entries": []}


def read_sheets(path):
    import xlrd  # 로컬 도구에서만 필요
    wb = xlrd.open_workbook(path)
    sheets = {s.name: s for s in wb.sheets()}
    return wb.sheet_by_index(0), sheets.get(REAR_SHEET_NAME)


def collect(path):
    first, rear_sheet = read_sheets(path)
    official, points, problems = [], [], []
    # Sheet1: X열 표시 (헤더 행이 1행 또는 2행이므로 '관리번호' 헤더를 찾는다)
    header_row = next(r for r in range(min(5, first.nrows)) if str(first.cell_value(r, 0)).strip() == "무인교통단속카메라관리번호")
    for r in range(header_row + 1, first.nrows):
        if first.ncols > 23 and str(first.cell_value(r, 23)).strip():
            co = parse_coords(first.cell_value(r, 9), first.cell_value(r, 10))
            official.append({
                "id": str(first.cell_value(r, 0)).strip(),
                "addr": str(first.cell_value(r, 8)).strip(),
                "name": str(first.cell_value(r, 11)).strip(),
                "lat": co[0] if co else None,
                "lon": co[1] if co else None,
            })
    # 후면 시트
    if rear_sheet is not None:
        for r in range(1, rear_sheet.nrows):
            mark = str(rear_sheet.cell_value(r, 23)).strip() if rear_sheet.ncols > 23 else ""
            addr = str(rear_sheet.cell_value(r, 8)).strip()
            if not (mark or addr or str(rear_sheet.cell_value(r, 9)).strip()):
                continue
            if not mark:
                continue
            co = parse_coords(rear_sheet.cell_value(r, 9), rear_sheet.cell_value(r, 10))
            if co is None:
                problems.append((r + 1, addr, "좌표를 읽지 못했습니다"))
                continue
            points.append({
                "_row": r + 1,
                "id": str(rear_sheet.cell_value(r, 0)).strip(),
                "addr": addr,
                "name": str(rear_sheet.cell_value(r, 11)).strip(),
                "lat": co[0],
                "lon": co[1],
            })
    return official, points, problems


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    official, points, problems = collect(sys.argv[1])
    overrides = load_overrides()
    before = len(overrides["entries"])
    added, updated, assigned = merge_entries(overrides, official, points)
    with open(OVERRIDES, "w", encoding="utf-8") as f:
        json.dump(overrides, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"공공 카메라 표시 {len(official)}건, 후면 시트 {len(points)}건 읽음 (읽지 못한 행 {len(problems)}건)")
    print(f"목록: {before} -> {len(overrides['entries'])}건 (추가 {added}, 갱신 {updated}, 삭제 0)")
    for row, addr, why in problems:
        print(f"  확인 필요: 후면 시트 {row}행 {addr!r}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
