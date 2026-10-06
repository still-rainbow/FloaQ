import { hhmm, survival } from '../lib/survival';
import { elapsed } from '../lib/time';

/**
 * 생존 잔여시간(신규 1). `경과 8분 / 수온 14.2℃ / 의식 유지 예상 ~2시간`
 *
 * ⚠ 의료적 확정치가 아니다. 화면에 "참고용 추정치"를 반드시 병기한다 —
 *   이 숫자를 보고 수색을 접는 판단이 나오면 안 된다.
 *   쓰임은 정확도가 아니라 **여러 사고 중 어느 쪽이 급한지 줄 세우는 것**이다.
 */
export function SurvivalMeter({ tempC, elapsedSec }: { tempC: number; elapsedSec: number }) {
  const s = survival(tempC, elapsedSec);
  const [lo, hi] = s.band.conscious;
  const pct = Number.isFinite(hi) ? Math.min(100, (elapsedSec / 60 / hi) * 100) : 0;

  /**
   * 막대 색은 한 가지다 — 지금 얼마나 급한가만 말한다.
   *   초록  여유
   *   노랑  의식 유지 상한의 절반을 넘겼거나 1시간 안쪽
   *   빨강  80% 를 넘겼거나 30분 안쪽, 또는 상한 초과
   */
  const left = s.consciousLeftMin;
  const level = s.past || pct >= 80 || left <= 30 ? 'danger' : pct >= 50 || left <= 60 ? 'warn' : 'ok';

  return (
    <div className={`survival lv-${level}${s.past ? ' is-past' : ''}`}>
      {/*
        다른 섹션과 <b>같은 제목 줄</b>을 쓴다 — 이름 왼쪽, 핵심 값 오른쪽.
        전에는 이 블록만 테두리 두른 상자여서 옆 섹션들과 모양이 안 맞았다(2026-09-18).
      */}
      <div className="section-label">
        {/* 계산이 내는 값은 의식 유지 상한이다. "생존"은 그 시간이 지나면 사망으로 읽힌다 —
            저체온증은 의식을 잃은 뒤에도 생존 시간이 더 길다(2026-09-17) */}
        <h3>의식 유지 예상</h3>
        <span className="survival-val mono">
          {s.past ? '상한 초과' : `${hhmm(s.consciousLeftMin)} 남음`}
        </span>
      </div>

      <span className="survival-track"><i style={{ width: `${pct}%` }} /></span>

      <div className="survival-meta">
        경과 {elapsed(elapsedSec)} · 수온 {tempC.toFixed(1)}℃ ·{' '}
        수온 구간 {Number.isFinite(hi) ? `${hhmm(lo)}~${hhmm(hi)}` : '무기한'}
      </div>

      {/* 근거(USCG·캐나다 저체온증 생존곡선표)는 title 로만 둔다. 화면에는 지켜야 할 단서 한 줄만. */}
      <p className="src-note survival-note"
         title="미국 해안경비대·캐나다 해양 표준의 저체온증 생존곡선표를 수온 구간으로 옮긴 값입니다. 체격·복장·구명조끼 착용 여부는 반영되지 않습니다.">
        <b>참고용 추정치</b> · 의료 판단 아님
      </p>
    </div>
  );
}
