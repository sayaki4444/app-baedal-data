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

## 후면/후방 카메라 제보 자동 검증

앱에서 사용자가 올린 `후면/후방 고정카메라` 제보(`category='rear_camera'`, 처음에는 `pending`)를 사람이 승인하지 않고 공공데이터로 확인합니다.

- 매일 03:30(KST) `verify-rear-reports` 워크플로가 최신 공공데이터를 **새로 받아** 대기 중인 제보와 위치를 비교합니다.
- 공공 카메라가 **50m 이내**에 있으면 `approved`. 일치하지 않으면 대기하다가 **제보 후 7일이 지나면 `rejected`**.
- 공공데이터에는 카메라가 앞/뒤 어느 쪽을 보는지 정보가 없습니다. 이 검증은 "그 위치에 실제 단속카메라가 있다"만 확인합니다.
- 설정: 저장소 Settings → Secrets and variables → Actions 에 `DATA_GO_KR_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` 등록. **service_role 키는 이 Secret 에만 두고 앱·저장소·채팅에 넣지 않습니다.** Secret 이 없으면 워크플로는 테스트만 하고 건너뜁니다.
- 수동 실행: Actions → Verify rear-camera reports → Run workflow (기본 `dry_run=true`: 서버를 바꾸지 않고 결과만 출력).
- 로컬 테스트: `python -I -m unittest discover -s tests -v`
