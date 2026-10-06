# Interface

## Detection output contract

후속 tracking/stereo 모듈을 위해 각 detection은 최소한 다음 정보를 유지한다.

- frame or image identifier
- bounding box coordinates (`xyxy`)
- confidence score
- class id and class name
- optional timestamp

구체적인 직렬화 형식은 backend/IoT 연동 요구사항 확정 후 버전과 함께 정의한다.
