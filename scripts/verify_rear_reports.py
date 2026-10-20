"""후면/후방 카메라 제보를 최신 공공 카메라 위치와 비교해 자동 승인/반려한다.

동작
  1. Supabase 에서 status='pending', category='rear_camera' 인 제보를 읽는다.
  2. 최신 cameras.json(공공데이터)의 카메라 중 MATCH_RADIUS_M 이내에 하나라도 있으면 approved.
  3. 일치하지 않고 제보 후 REJECT_AFTER_DAYS 일이 지났으면 rejected. 아니면 그대로 둔다(대기).

사용:
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python scripts/verify_rear_reports.py cameras.json [--dry-run]

환경변수 SUPABASE_SERVICE_ROLE_KEY 는 GitHub Secret 으로만 넣는다. 이 키는 모든 보안 규칙을 우회하므로
앱, 저장소, 로그에 남기지 않는다. 표준 라이브러리만 사용하고, 출력에는 키와 URL 을 쓰지 않는다.
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MATCH_RADIUS_M = 50
REJECT_AFTER_DAYS = 7
GRID_DEG = 0.001  # 약 100m. 이웃 3x3 칸만 검사하면 50m 반경을 모두 덮는다


def distance_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_index(cameras):
    index = {}
    for c in cameras:
        lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        key = (math.floor(lat / GRID_DEG), math.floor(lon / GRID_DEG))
        index.setdefault(key, []).append((lat, lon))
    return index


def nearest_camera_m(index, lat, lon):
    """주변 3x3 칸의 가장 가까운 카메라까지 거리(m). 없으면 None."""
    gy, gx = math.floor(lat / GRID_DEG), math.floor(lon / GRID_DEG)
    best = None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for clat, clon in index.get((gy + dy, gx + dx), ()):
                d = distance_m(lat, lon, clat, clon)
                if best is None or d < best:
                    best = d
    return best


def decide(report, index, now_ms, match_radius_m=MATCH_RADIUS_M, reject_after_days=REJECT_AFTER_DAYS):
    """'approved' | 'rejected' | 'pending' 중 하나를 돌려준다."""
    lat, lon = report.get("lat"), report.get("lon")
    if lat is None or lon is None:
        return "rejected"
    d = nearest_camera_m(index, float(lat), float(lon))
    if d is not None and d <= match_radius_m:
        return "approved"
    age_ms = now_ms - int(report.get("created_at") or now_ms)
    if age_ms >= reject_after_days * 86400 * 1000:
        return "rejected"
    return "pending"


class Supabase:
    def __init__(self, url, key):
        self.url = url.rstrip("/")
        if self.url.endswith("/rest/v1"):
            self.url = self.url[: -len("/rest/v1")]
        self.key = key

    def _request(self, method, path, body=None, prefer=None):
        headers = {"apikey": self.key, "Authorization": "Bearer " + self.key}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read().decode()
                    return json.loads(raw) if raw.strip() else None
            except urllib.error.HTTPError as e:
                # 응답 본문에 키가 들어갈 일은 없지만, 상태 코드만 남기고 본문은 버린다
                last = f"HTTP {e.code}"
                if e.code < 500:
                    break
            except Exception as e:  # noqa: BLE001
                last = type(e).__name__
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"{method} {path.split('?')[0]} failed: {last}")

    def pending_rear_reports(self):
        q = "category=eq.rear_camera&status=eq.pending&select=id,lat,lon,created_at&order=created_at.asc&limit=1000"
        return self._request("GET", "/rest/v1/shared_reports?" + q) or []

    def set_status(self, report_id, status):
        path = "/rest/v1/shared_reports?id=eq." + urllib.parse.quote(report_id, safe="")
        self._request("PATCH", path, {"status": status}, prefer="return=minimal")


def run(reports, index, now_ms, apply_fn, dry_run, match_radius_m=MATCH_RADIUS_M, reject_after_days=REJECT_AFTER_DAYS):
    summary = {"approved": 0, "rejected": 0, "pending": 0, "errors": 0}
    for r in reports:
        verdict = decide(r, index, now_ms, match_radius_m, reject_after_days)
        if verdict == "pending":
            summary["pending"] += 1
            continue
        if dry_run:
            summary[verdict] += 1
            continue
        try:
            apply_fn(r["id"], verdict)
            summary[verdict] += 1
        except Exception:  # noqa: BLE001 - 한 건 실패가 전체를 멈추지 않게 한다
            summary["errors"] += 1
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cameras_json", help="최신 공공 카메라 cameras.json 경로")
    ap.add_argument("--dry-run", action="store_true", help="서버를 바꾸지 않고 결과만 출력")
    ap.add_argument("--match-radius", type=float, default=MATCH_RADIUS_M)
    ap.add_argument("--reject-after-days", type=float, default=REJECT_AFTER_DAYS)
    args = ap.parse_args(argv)

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수가 없어 건너뜁니다.", file=sys.stderr)
        return 0

    with open(args.cameras_json, encoding="utf-8") as f:
        cameras = json.load(f).get("cameras", [])
    if len(cameras) < 1000:  # 비정상적으로 적으면 데이터 수집 실패로 보고 아무것도 바꾸지 않는다
        print(f"카메라 {len(cameras)}건뿐이라 데이터 이상으로 보고 중단합니다.", file=sys.stderr)
        return 1
    index = build_index(cameras)

    sb = Supabase(url, key)
    reports = sb.pending_rear_reports()
    now_ms = int(time.time() * 1000)
    summary = run(reports, index, now_ms, sb.set_status, args.dry_run, args.match_radius, args.reject_after_days)

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(f"[{mode}] 카메라 {len(cameras)}건 기준, 대기 제보 {len(reports)}건 → "
          f"승인 {summary['approved']}, 반려 {summary['rejected']}, 계속 대기 {summary['pending']}, 오류 {summary['errors']}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
