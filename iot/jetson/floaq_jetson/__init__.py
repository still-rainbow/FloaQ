"""FloaQ Jetson SDK. **함수 둘이면 끝난다.**

    from floaq_jetson import Floaq

    fq = Floaq(pi="192.168.0.10")
    fq.start()

    while True:
        jpeg = encode(camera.read())
        fq.frame(jpeg, camera="L")                  # ① 매 프레임

        if p := model.detect(...):                  # ② 탐지되면 한 줄
            fq.detected(lat=p.lat, lon=p.lon, distance_m=p.dist,
                        confidence=p.conf, camera="L", bbox=p.bbox,
                        yaw=aim.yaw, pitch=aim.pitch,
                        target_lat=aim.lat, target_lon=aim.lon)

`detected()` 한 번이 이걸 다 한다.

    1. detection_id 발급(uuid v7, 시간순)
    2. 페이로드 검증 — 틀리면 **즉시 예외**
    3. jetson/detection 발행 (QoS 1)
    4. 링 버퍼(앞 15초) -> 업로드 큐  BEFORE
    5. 지금 프레임      -> 업로드 큐  DETECT_SNAPSHOT
    6. AFTER 모드 ON — 이후 frame() 이 자동으로 올라간다 (뒤 10초)

AFTER 는 Pi 가 `pi/accident/state` 로 CLOSE·CANCEL 을 주면 **자동으로 꺼진다.**
종료 시점을 AI 쪽에서 신경 쓸 필요가 없다.

── 규칙 ──────────────────────────────────────────────────────────────
🔴 **모든 호출이 논블로킹이다.** 추론 루프가 5fps 로 도는데 우리 때문에 프레임이
   밀리면 안 된다. 전송은 전부 워커 스레드가 한다.

🔴 **예외는 호출이 틀렸을 때만 난다.** `lat=200` 같은 것은 AI 쪽 버그라 크게 터져야
   한다. 반대로 Pi 가 죽어 있거나 랜이 끊긴 것은 **정상 경로**라 조용히 큐에 쌓인다.
   그 상태는 `stats()` 로 본다.

🔴 **사고 판정은 Pi 가 한다.** 그래서 이 SDK 어디에도 `accident_id` 를 만드는 곳이
   없다. 탐지를 보내면 Pi 가 사고를 열고 `accident_id` 를 알려준다.
"""

from ._client import Detection, Floaq, InvalidCall
from ._client import (FRAME_FPS, FRAME_POST_SEC, FRAME_PRE_SEC, HTTP_PORT,
                      MQTT_PORT, STREAM_PORT)

__all__ = [
    "Floaq", "Detection", "InvalidCall",
    "FRAME_PRE_SEC", "FRAME_POST_SEC", "FRAME_FPS",
    "MQTT_PORT", "HTTP_PORT", "STREAM_PORT",
]


def __getattr__(name: str):
    """내부 이름에 손이 닿으면 알려준다.

    🔴 `del` 로 지우면 안 된다. 함수는 전역을 **호출 시점에** 찾으므로 `time` 이나
      `requests` 를 지우는 순간 전부 NameError 가 된다. 구현을 `_client.py` 로
      옮기고 여기서는 공개 이름만 재수출한다.
    """
    raise AttributeError(
        f"floaq_jetson.{name} 은 공개 API 가 아니다. 쓸 수 있는 것: {', '.join(__all__)}")
