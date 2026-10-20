# app-baedal-data

모두의배달 앱이 내려받는 단속카메라 데이터(`cameras.json`)를 만드는 저장소입니다.

- 출처: 공공데이터포털 [전국무인교통단속카메라표준데이터](https://www.data.go.kr/) (이용허락범위: 저작자표시)
- 매주 GitHub Actions가 API에서 받아 정규화하고, 30m 이내 같은 종류는 하나로 합칩니다.
- 내용이 바뀐 경우에만 `cameras.json`을 커밋합니다.
- 설정: 저장소 Settings → Secrets and variables → Actions 에 `DATA_GO_KR_KEY`(공공데이터포털 일반 인증키)를 등록합니다.

## cameras.json 형식

```json
{"updatedAt":"...Z","source":"...","count":37546,
 "cameras":[{"id":1,"lat":33.24,"lon":126.27,"kind":"signal","limit":50,"name":"...","road":"..."}]}
```

`kind`: `speed`(과속), `signal`(신호위반), `speed_signal`(과속+신호), `parking`(불법주정차), `section`(구간단속), `other`.
`limit`: 제한속도 km/h, 없으면 0.

단속구분 코드→이름 대응은 제한속도와 장소명 분포로 추정한 것입니다(`scripts/build_cameras.py` 참고).

## 로컬 실행

```bash
DATA_GO_KR_KEY=<인증키> python scripts/build_cameras.py cameras.json
```

## 후면 카메라 (rear_overrides.json)

공공데이터에는 후면/후방 카메라를 구분하는 항목이 없습니다. 이름에 "후면", "후방"이 적힌 것은 앱이 알아보고, 나머지는
사람이 확인한 카메라를 `rear_overrides.json` 에 모아 두었다가 `build_cameras.py` 가 매번 적용합니다.

- 목록에는 **추가만 하고 지우지 않습니다.** 주간 갱신에서 카메라가 잠시 사라져도 목록은 그대로입니다.
- 공공 카메라 번호(예: `J6729`)로 지정하거나, 사용자가 찍은 지점(`MY-0001` …)을 지번 주소 100m / 가장 가까운 카메라 40m 규칙으로 기존 카메라에 연결합니다. 연결할 카메라가 없으면 그 좌표에 새 후면 카메라를 만듭니다.
- 엑셀에서 표시하는 방법: 첫 시트 X열에 글자를 적거나, '후면' 시트에 `I:지번 J:위도 K:경도 L:설치장소 X:후면` 으로 행을 추가한 뒤
  `python scripts/import_rear_sheet.py raw/<파일>.xls` 로 목록에 반영합니다 (`pip install xlrd`).
- 규칙 테스트: `python scripts/test_build_cameras.py`
- `raw/` 폴더(내려받은 원본)는 저장소에 올리지 않습니다 (`.gitignore`).
- `cameras.json` 의 `rear: true` 가 후면 카메라입니다.
