# Playwright WebRTC Viewer Flood Test

* Playwright와 Chromium으로 다수의 WebRTC 시청자를 생성하는 부하 테스트 도구
* 마스터 프로세스가 목표 시청자를 여러 워커에 분배하고, 각 워커는 시청자별로 독립된 `BrowserContext`와 페이지를 만들어 접속 상태 및 inbound RTP 수신 여부를 확인

## 동작 방식

1. `viewer_master.mjs`가 전체 시청자 수를 워커별로 나눠 Node.js 자식 프로세스를 실행
2. 각 `test_viewer_flood.mjs` 워커가 다음 주소에 배치 단위로 접속

   ```text
   {baseUrl}/loadtest.html?roomId={roomId}&displayName=viewer-{번호}
   ```

3. 페이지의 `RTCPeerConnection` 생성을 추적하고, 하나 이상의 PeerConnection이 `connected` 상태가 될 때까지 기다림
4. 접속에 실패한 시청자는 새 Context/Page를 사용해 성공할 때까지 다시 시도
5. 모든 시청자가 연결되면 일정 주기로 WebRTC `inbound-rtp` 통계의 패킷 및 바이트 증가량을 측정
6. 마스터가 워커 요약을 모아 10초마다 전체 현황을 출력

* TLS 인증서 오류는 무시하며, Chromium은 headless 모드와 가짜 미디어 장치로 실행됨
* 오디오는 음소거

## 구성 파일

- `viewer_master.mjs`: 워커 생성, 시청자 분배, 로그 병합 및 전체 통계 집계
- `test_viewer_flood.mjs`: 브라우저 실행, 시청자 접속·재시도 및 RTP 통계 측정
- `run.sh`: 현재 로컬 환경용 실행 예시
- `package.json`, `package-lock.json`: Node.js 의존성 정의

## 요구 사항

- Node.js 20 이상
- npm
- Playwright가 설치한 Chromium 또는 별도로 빌드한 Chromium 실행 파일
- `{baseUrl}/loadtest.html`에서 접근 가능한 WebRTC 테스트 페이지

테스트 페이지는 로드 과정에서 `RTCPeerConnection`을 생성하고 연결해야 함. 각 페이지 이동, PeerConnection 생성, 연결에는 각각 최대 30초의 대기 시간이 적용됨.

## 설치

잠금 파일에 지정된 의존성 설치

```bash
npm ci
```

## 실행

* 모든 인자는 `--이름=값` 형식으로 전달해야 함. 
* `roomId`만 필수
* `chromiumPath`를 생략하면 Playwright 기본 Chromium을 사용

```bash
node viewer_master.mjs \
  --roomId=test-room \
  --baseUrl=https://10.20.13.186:5555 \
  --totalViewers=10000 \
  --workerCount=40 \
  --batchSize=15 \
  --batchDelayMs=0 \
  --retryDelayMs=1000 \
  --workerStartDelayMs=1000 \
  --rtpCheckIntervalMs=30000 \
  --rtpWindowMs=2000 \
  --statsConcurrency=25
```

별도 Chromium을 사용할 때는 실행 파일 경로를 추가

```bash
node viewer_master.mjs \
  --roomId=test-room \
  --chromiumPath=/path/to/chrome \
  --totalViewers=200 \
  --workerCount=1
```

## 마스터 옵션

| 옵션 | 기본값 | 설명 |
| --- | ---: | --- |
| `roomId` | 없음 | 접속할 방 ID. 필수 |
| `baseUrl` | `https://10.20.13.186:5555` | `/loadtest.html`을 제공하는 서버 주소 |
| `chromiumPath` | 없음 | 사용할 Chromium 실행 파일. 생략 시 Playwright 기본값 사용 |
| `totalViewers` | `10000` | 전체 목표 시청자 수 |
| `workerCount` | `40` | 생성할 최대 워커 수. 1 이상이어야 함 |
| `batchSize` | `15` | 워커 하나가 동시에 접속을 시도할 시청자 수 |
| `batchDelayMs` | `0` | 다음 배치 전 대기 시간(ms) |
| `retryDelayMs` | `1000` | 실패한 시청자가 포함된 배치 이후 추가 대기 시간(ms) |
| `workerStartDelayMs` | `1000` | 워커 생성 사이의 대기 시간(ms) |
| `rtpCheckIntervalMs` | `30000` | RTP 검사 시작 주기(ms) |
| `rtpWindowMs` | `2000` | RTP 증가량을 비교할 측정 구간(ms) |
| `statsConcurrency` | `25` | 워커별 페이지 통계 조회 동시 실행 수 |

* 숫자 옵션은 0 이상의 정수
* `workerCount`는 0을 허용하지 않으며, 워커 내부에서 `batchSize`와 `statsConcurrency`는 최소 1로 보정됨.

## 출력 해석

마스터의 `MASTER AGGREGATE`에는 다음 값 표시

- `workers reporting`: 한 번 이상 요약을 보낸 워커 수
- `target viewers`: 목표 시청자 수
- `attempted`: 재시도를 포함한 누적 접속 시도 수
- `connected`: 현재까지 연결에 성공한 시청자 수
- `receiving RTP`: 최근 측정 구간에 패킷과 바이트가 모두 증가한 시청자 수
- `failed attempts`: 최종 실패 시청자 수가 아니라 누적 실패 시도 수
- `packetsDelta`, `bytesDelta`: 최근 RTP 측정 구간의 전체 증가량

워커 로그에는 HTTP 오류, 요청 실패, 브라우저 콘솔 오류, 실패 단계와 PeerConnection 상태가 함께 기록.

## 종료

* `Ctrl+C`로 종료
* 마스터는 모든 워커에 `SIGTERM`을 보내고, 2초 후에도 종료되지 않은 워커는 강제 종료
* 워커는 종료 신호를 받으면 RTP 타이머를 정리하고 브라우저를 닫음
