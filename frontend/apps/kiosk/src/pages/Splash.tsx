import { Mascot } from '../layout/Mascot';

/**
 * 진입 화면 (`p-shim/demo-v2/kiosk` 의 `.splash`).
 *
 * <p>스타일은 처음부터 `kiosk.css` 에 이식돼 있었는데 **그리는 쪽이 없어 쓰이지 않고 있었다**
 * (2026-09-21 발견). 등록 관문이 Pi 를 확인하는 동안 맨 텍스트 화면을 띄우고 있어서
 * 원래 진입 화면으로 바꾼다.</p>
 *
 * <p>🔴 <b>데모의 4단계 진행 막대를 그대로 옮기지 않았다.</b> 그쪽은 620ms 간격으로
 * `선내 장비 확인 중 → 카메라·IMU 응답 확인 → 부표 통신 확인 → 준비 완료` 를
 * <b>시간으로 흉내 낸 것</b>이다. 실제로 이 화면이 기다리는 것은 `GET /api/ship` 한 번이라
 * 단계가 없다. 없는 진행률을 그리면 화면이 거짓말을 한다 — 막대는 <b>진행률이 아니라
 * "도는 중"</b>만 표시한다.</p>
 *
 * <p>⚠ 데모의 `&lt;canvas id="sea"&gt;` 파도 애니메이션은 안 옮겼다. 이 화면은 길어야
 * 몇 초 뜨는데 그 그림 하나로 캔버스 루프가 번들에 들어온다. 배경 그라디언트가 분위기를 낸다.</p>
 */
export function Splash({ hint = '선내 장비 확인 중' }: { hint?: string }) {
  return (
    <div className="splash">
      <div className="splash-inner">
        <Mascot className="splash-mark bobbing" />
        <h1>Floa<em>Q</em></h1>
        <p>AIoT 기반 해상 인명 구조 시스템</p>
        <div className="splash-bar"><i className="is-wait" /></div>
        <div className="splash-hint">{hint}</div>
      </div>
    </div>
  );
}
