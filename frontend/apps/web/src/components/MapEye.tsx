/**
 * 지도에 표시 중인가 — <b>눈</b>으로 말한다.
 *
 * <p>전에는 on/off 스위치였다. 스위치는 "켠다/끈다"는 뜻이라 이 자리에 맞지 않았다 —
 * 여기서 바뀌는 것은 사고의 상태가 아니라 <b>내가 보고 있는가</b>뿐이다.
 * 눈을 감기면(사선) 지도에서 내려간다(2026-09-17).</p>
 */
export function MapEye({ on }: { on: boolean }) {
  return (
    <svg className="eye" viewBox="0 0 24 16" width="22" height="15" aria-hidden="true"
         fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 8s4-6 11-6 11 6 11 6-4 6-11 6S1 8 1 8Z" />
      <circle cx="12" cy="8" r="2.8" />
      {/* 감은 눈 대신 사선 — 감은 눈은 작게 그리면 그냥 가로선이라 뜬 눈과 구별이 안 된다 */}
      {!on ? <path className="eye-slash" d="M3.5 14.5 20.5 1.5" /> : null}
    </svg>
  );
}
