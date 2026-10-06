import { useState } from 'react';

/**
 * 가로 막대. 지점 이름이 길어서 세로로 세우면 라벨이 눕는다.
 *
 * **0 에서 시작한다.** 막대는 길이가 곧 값이라 축을 자르면 1.2배를 3배로 보이게 만든다
 * (라인 차트는 다르다 — 거기는 변화를 보는 것이라 0 에서 시작하지 않는다).
 *
 * 시리즈가 하나라 범례가 없다. 값은 막대 끝에 직접 적는다 — 축을 되짚어 읽지 않게.
 */
export interface Bar {
  label: string;
  value: number;
  /** 지점·거리 같은 부가 설명. 툴팁에만 뜬다 */
  note?: string;
}

interface Props {
  title: string;
  unit: string;
  bars: Bar[];
  color: string;
  dec?: number;
  /** 값이 없을 때 화면이 비지 않게 */
  emptyText?: string;
}

const ROW = 30;

export function BarChart({ title, unit, bars, color, dec = 1, emptyText = '값 없음' }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...bars.map((b) => b.value), 0.0001);

  return (
    <div className="chart">
      <div className="chart-head">
        <span className="chart-title">{title}</span>
        <span className="chart-read mono">
          {hover != null && bars[hover]?.note ? bars[hover]!.note : `${bars.length}지점`}
        </span>
      </div>
      {bars.length === 0 ? (
        <p className="chart-empty">{emptyText}</p>
      ) : (
        <div className="bars">
          {bars.map((b, i) => (
            <div key={b.label} className="bar-row"
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
              style={{ height: ROW }}>
              <span className="bar-label">{b.label}</span>
              <span className="bar-track">
                {/* 데이터 끝만 둥글게. 기준선 쪽은 각져야 0 에서 시작한 것이 보인다 */}
                <i className="bar-fill" style={{
                  width: `${(b.value / max) * 100}%`,
                  background: color,
                  opacity: hover == null || hover === i ? 1 : 0.45,
                }} />
              </span>
              <span className="bar-value mono">{b.value.toFixed(dec)}<small>{unit}</small></span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
