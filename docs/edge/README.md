# IoT 문서

## 먼저 읽을 것

| 문서 | 내용 |
|---|---|
| [communication.md](communication.md) | **통신 구조를 처음 보는 사람용으로 한 장에.** 장치·용어·전체 그림·사고 순서·남은 과제 |
| [demo.md](demo.md) | **시연 사항.** 켜는 순서·안전·발사관 기본값·부표 가짜 GPS 주의·확인 로그 |
| [architecture.md](architecture.md) | **노드 역할과 전송 경로 전체.** 여기서 시작한다 |

## 규격·구현

| 문서 | 내용 | 대상 |
|---|---|---|
| [mqtt.md](mqtt.md) | MQTT 토픽·페이로드 규격 (정본) | IoT · 웹 · AI |
| [mqtt-연동-웹.md](mqtt-연동-웹.md) | 접속·구독·명령·파일 전송 | **웹 팀** |
| [kiosk.md](kiosk.md) | 키오스크 ↔ Pi. 시나리오·토픽·명령·등록 | **키오스크 팀** |
| [ec2.md](ec2.md) | Pi ↔ EC2. 선박 등록·전송 펌프·타르볼 | IoT · 웹 |
| [api.json](api.json) | **EC2 REST 정본** (OpenAPI. 서버 코드에서 생성) | IoT · 웹 |
| [../../iot/jetson/README.md](../../iot/jetson/README.md) | Jetson SDK. 함수 둘 | **AI 팀** |
| [lora.md](lora.md) | 부표 LoRa 프레임 + E22 하드웨어 | IoT |
| [distress.md](distress.md) | DSC · AIS 조난 신고 (ITU-R M.493 / M.1371) | IoT |

## 설계 검토 (2026-09-10)

| 문서 | 내용 |
|---|---|
| [IoT_REVIEW_README.md](IoT_REVIEW_README.md) | 검토 개요 |
| [IoT_REVIEW_DES-31_엣지보드사양.md](IoT_REVIEW_DES-31_엣지보드사양.md) | 엣지보드 |
| [IoT_REVIEW_DES-33_부품선정.md](IoT_REVIEW_DES-33_부품선정.md) | 부품 |
| [IoT_REVIEW_DES-34_회로도.md](IoT_REVIEW_DES-34_회로도.md) | 회로 |
| [IoT_REVIEW_DES-35_전원설계.md](IoT_REVIEW_DES-35_전원설계.md) | 전원 |
| [IoT_REVIEW_DES-36_선박장착.md](IoT_REVIEW_DES-36_선박장착.md) | 장착 |
| [IoT_REVIEW_DES-37_발사메커니즘.md](IoT_REVIEW_DES-37_발사메커니즘.md) | 발사 기구 |
| [IoT_REVIEW_DES-38_각도제어구조.md](IoT_REVIEW_DES-38_각도제어구조.md) | 각도 제어 |
| [IoT_REVIEW_DES-39_발사체설계.md](IoT_REVIEW_DES-39_발사체설계.md) | 발사체 |
| VERIFY_docs_2026-09-10.md (`VERIFY_docs_2026-09-10.md`, 공개 사본 미포함) | 검증 기록 |

---

## 규약

문서와 코드가 어긋나면 **코드가 맞다.** 정본은 이렇다.

| 대상 | 정본 |
|---|---|
| MQTT 계약 | `iot/pi/floaq/contracts/` |
| EC2 REST | `docs/edge/api.json` — ⚠ `api.md` 는 **폐기** |
| Jetson SDK | `iot/jetson/floaq_jetson/` |
| LoRa 프레임 | `iot/pi/floaq/contracts/lora.py` |
| DSC · AIS | `iot/pi/floaq/protocols/` |
| 정책값 | `iot/pi/floaq/config.py` |
| DB 스키마 | `database/pi.sql` |

`확정` 은 팀 결정, `제안` 은 승인 대기, `미정` 은 결정 없이 임시값이다.
임시값에는 반드시 TODO 와 담당을 적는다 — 안 적으면 그게 확정값으로 굳는다.
