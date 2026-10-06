import { useState } from 'react';
import { STEPS } from '../lib/drift';
import { dist } from '../lib/time';

/**
 * 표류 범위 시간 슬라이더(신규 7).
 *
 * 정지한 범위 하나를 보여 주는 대신 시간 경과를 압축해 보여 준다 —
 * 끌면 불확실 범위가 부풀고 조류 방향으로 늘어지며 중심이 이동한다.
 *
 * **실측 중인 부표에도 적용된다.** 지금 위치를 정확히 알아도 구조 세력에게 필요한 것은
 * 도착할 때쯤의 위치이기 때문이다. 추정 계산의 시간 파라미터를 밖으로 노출한 것이 전부다.
 */
interface Props {
  /** 지금 고른 Δt(초) */
  value: number;
  onChange: (sec: number) => void;
  /** 지금 Δt 에서 현재 위치로부터 흘러간 거리(m) */
  movedM: number;
  disabled?: boolean;
}

export function DriftSlider({ value, onChange, movedM, disabled }: Props) {
  /**
   * 접을 수 있게 둔다 — 지도를 넓게 보고 싶을 때가 있다('지도에 표시 중' 과 같은 방식).
   * 접어도 <b>고른 시점은 그대로 남는다.</b> 접기는 보기 편하려는 것이지 되돌리는 것이 아니다 —
   * 접었더니 지도가 '지금'으로 돌아가면 무엇을 보고 있었는지 잃는다.
   */
  const [open, setOpen] = useState(true);
  const picked = STEPS.find(([sec]) => sec === value)?.[1] ?? '';

  return (
    <div className={`drift-slider${disabled ? ' is-disabled' : ''}`}>
      <button className="drift-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="drift-label">표류 예상 위치</span>
        {/* 접혀 있을 때는 무엇을 고른 상태인지가 보여야 한다. 안 그러면 지도만 보고 '지금'인 줄 안다 */}
        <span className="drift-moved mono">
          {open
            ? (movedM > 0 ? `현재 위치에서 ${dist(movedM)}` : '현재 위치 기준')
            : picked}
        </span>
        <i className="legend-caret" aria-hidden="true" />
      </button>

      {open ? (
        <div className="pick" role="group" aria-label="표류 예상 시점">
          {STEPS.map(([sec, label]) => (
            <button
              key={sec}
              className="pick-btn"
              aria-pressed={value === sec}
              disabled={disabled}
              onClick={() => onChange(sec)}
            >
              {label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
