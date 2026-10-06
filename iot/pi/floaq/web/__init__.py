"""선내 HTTP 서버. 파일과 페이지만 나른다.

이벤트·상태·명령은 MQTT 가 나른다 (`adapters/mqtt.py`). 역할이 겹치지 않는다.

    app.py    FastAPI 앱과 라우트
    files.py  디스크 저장소. DB 도 HTTP 도 모른다
"""
