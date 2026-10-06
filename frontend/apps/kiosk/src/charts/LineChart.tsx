import { useCallback, useRef, useState } from 'react';
import { linePath, niceExtent, scaleX, scaleY, ticks, type Extent } from './scale';

/**
 * 시계열 라인 하나.
 *
 * **축이 하나다.** 단위가 다른 두 값을 한 그림에 겹치지 않는다 — 유속과 수온을 같이 그리면
 * 두 축의 눈금 위치가 우연히 만드는 교차를 사람이 상관관계로 읽는다. 차트를 나눈다.
 *
 * 시리즈가 하나라 범례를 두지 않는다. 제목이 그 이름이다.
 * 크로스헤어와 툴팁은 기본이다 — 178개 점에 숫자를 다 찍을 수는 없고,
 * 찍지 않으면 "그래서 17시에 얼마냐"에 답이 없다.
 */
export interface LinePoint {
  at: string;
  value: number | null;
}

interface Props {
  title: string;
  unit: string;
  points: LinePoint[];
  /** 선 색. 테마 토큰 변수를 넘긴다 */
  color: string;
  dec?: number;
  /** 이 시각에 세로선을 긋는다 — "지금" 표시 */
  markerAt?: string;
  height?: number;
}

const PAD = { top: 10, right: 12, bottom: 20, left: 40 };

const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', hour12: false, timeZone: 'Asia/Seoul' });

const dayHour = (iso: string) => {
  const d = new Date(iso);
  return `${d.toLocaleDateString('ko-KR', { day: 'numeric', timeZone: 'Asia/Seoul' })} ${hhmm(iso)}`;
};

export function LineChart({ title, unit, points, color, dec = 2, markerAt, height = 150 }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [box, setBox] = useState({ w: 520, h: height });

  // ResizeObserver 대신 마우스가 들어올 때 잰다. 차트가 여럿이라 관찰자를 여럿 두지 않는다
  const measure = useCallback(() => {
    const w = hostRef.current?.clientWidth;
    if (w && Math.abs(w - box.w) > 2) setBox({ w, h: height });
  }, [box.w, height]);

  const values = points.map((p) => p.value);
  const extent: Extent = niceExtent(values.filter((v): v is number => v != null));
  const w = Math.max(120, box.w - PAD.left - PAD.right);
  const h = height - PAD.top - PAD.bottom;

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left - PAD.left;
    const i = Math.round((x / w) * (points.length - 1));
    setHover(i >= 0 && i < points.length ? i : null);
  };

  const markerIdx = markerAt
    ? points.findIndex((p) => new Date(p.at).getTime() >= new Date(markerAt).getTime())
    : -1;
  const cur = hover != null ? points[hover] : null;

  return (
    <div className="chart" ref={hostRef} onMouseEnter={measure}>
      <div className="chart-head">
        <span className="chart-title">{title}</span>
        <span className="chart-read mono">
          {cur?.value != null
            ? `${cur.value.toFixed(dec)}${unit} · ${dayHour(cur.at)}`
            : `${points.length}시각 예측`}
        </span>
      </div>
      <svg
        width="100%" height={height} role="img" aria-label={title}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}
      >
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {/* 격자는 배경으로 물러난다 — 데이터보다 진하면 안 된다 */}
          {ticks(extent).map((t) => (
            <g key={t}>
              <line x1={0} x2={w} y1={scaleY(t, extent, h)} y2={scaleY(t, extent, h)}
                stroke="var(--line)" strokeWidth={1} />
              <text x={-8} y={scaleY(t, extent, h)} dy="0.32em" textAnchor="end"
                className="chart-axis">{t.toFixed(dec)}</text>
            </g>
          ))}

          {/* "지금". 예측 차트라 과거와 미래의 경계가 보여야 한다 */}
          {markerIdx >= 0 && (
            <g>
              <line x1={scaleX(markerIdx, points.length, w)} x2={scaleX(markerIdx, points.length, w)}
                y1={0} y2={h} stroke="var(--line-firm)" strokeWidth={1} strokeDasharray="3 3" />
              <text x={scaleX(markerIdx, points.length, w) + 4} y={10} className="chart-axis">지금</text>
            </g>
          )}

          <path d={linePath(values, extent, w, h)} fill="none" stroke={color}
            strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

          {hover != null && points[hover]?.value != null && (
            <g>
              <line x1={scaleX(hover, points.length, w)} x2={scaleX(hover, points.length, w)}
                y1={0} y2={h} stroke="var(--line-firm)" strokeWidth={1} />
              {/* 표면색 링이 겹친 선 위에서도 점을 읽히게 한다 */}
              <circle cx={scaleX(hover, points.length, w)} cy={scaleY(points[hover]!.value!, extent, h)}
                r={5} fill={color} stroke="var(--surface)" strokeWidth={2} />
            </g>
          )}

          {/* 양 끝 시각만 적는다. 178개를 다 적으면 라벨이 서로 겹친다 */}
          {points.length > 0 && (
            <>
              <text x={0} y={h + 14} className="chart-axis">{hhmm(points[0]!.at)}</text>
              <text x={w} y={h + 14} textAnchor="end" className="chart-axis">
                {dayHour(points[points.length - 1]!.at)}
              </text>
            </>
          )}
        </g>
      </svg>
    </div>
  );
}
