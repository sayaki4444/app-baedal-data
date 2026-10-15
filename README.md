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
