# Local deployment model

공개 저장소는 모델 가중치를 포함하지 않습니다.
학습·평가 결과로 생성한 모델을 이 폴더에 두고 실행 시 --weights로 지정하세요.
기존 스테레오 조준 설정은 person이라는 클래스 이름을 찾으므로 자기 모델의 클래스 목록을 확인해야 합니다.

```bash
python -m src.stereo_targeting --config configs/stereo_targeting.yaml --weights models/best_performance.pt
```
