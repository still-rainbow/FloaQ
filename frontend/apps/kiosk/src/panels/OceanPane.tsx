import { useState } from 'react';
import type { CatKey, Category, MetricKey } from '../types';
import { IcoBoat, IcoCompass, IcoExpand, IcoFish, IcoShield } from '../layout/Icons';

/**
 * 우측 — 평시 조업 지원 (§9.18).
 *
 * 카테고리를 **데이터 출처가 아니라 어민이 내리는 판단**으로 나눈다.
 * "수과원 데이터"를 보고 싶은 어민은 없고 "나가도 되나"를 알고 싶은 어민만 있다.
 *
 * 값은 전부 props 로 받는다 — 안전·조업·항해는 EC2, 내 배는 Pi 다. 두 경로를 여기서 섞지 않는다.
 * 출항 가부는 판단하지 않는다. 기상청 특보 기준을 따른다 (§9.18)
 *
 * 🔴 <b>하단 "오늘의 바다" 요약을 뺐다</b> (2026-09-18 요청). 이 서랍은 좁아서 수치표가 먼저다 —
 *    요약 문장은 해양 상황판(`Ocean.tsx` 종합 상황)에 전문이 있고, 위 `크게 보기` 가 그리로 간다.
 *    같은 문장을 두 곳에 두면 한쪽만 갱신됐을 때 어느 쪽이 지금 값인지 알 수 없다.
 */
interface Props {
  cats: Record<CatKey, Category>;
  metric: MetricKey | null;
  onMetric: (m: MetricKey) => void;
  /** 해양 상황판으로. 이 패널의 확대판이다 */
  onExpand: () => void;
}

const TABS: { key: CatKey; label: string; Icon: typeof IcoShield }[] = [
  { key: 'safe', label: '안전', Icon: IcoShield },
  { key: 'fish', label: '조업', Icon: IcoFish },
  { key: 'nav', label: '항해', Icon: IcoCompass },
  { key: 'ship', label: '내 배', Icon: IcoBoat },
];

export function OceanPane({ cats, metric, onMetric, onExpand }: Props) {
  const [cat, setCat] = useState<CatKey>('fish');
  const c = cats[cat];

  return (
    <section className="col">
      <div className="tabs" role="tablist" aria-label="해양 정보 카테고리">
        {TABS.map(({ key, label, Icon }) => (
          <button key={key} className="tab" role="tab" aria-selected={cat === key}
            onClick={() => setCat(key)}>
            <Icon size={26} />{label}
          </button>
        ))}
      </div>

      <div className="panel-head">
        {/* 출처는 남긴다 — 값의 근거를 화면에서 밝힌다 (§6) */}
        <span className="eyebrow">{c.src}</span>
        <button className="expand-btn" onClick={onExpand} title="해양 상황판 열기">
          <IcoExpand size={16} />크게 보기
        </button>
      </div>

      <div className="readings">
        {c.rows.map((r) => (
          <button key={r.label} className="reading"
            {...(r.metric ? { 'data-metric': r.metric } : { 'data-static': '' })}
            aria-pressed={!!r.metric && metric === r.metric}
            onClick={r.metric ? () => onMetric(r.metric!) : undefined}>
            <span className="reading-label">{r.label}</span>
            <span className="reading-value">
              {r.pill
                ? <span className={`pill ${r.pill}`}>{r.value}</span>
                : r.cold
                  ? <span className="cold">{r.value}</span>
                  : <>{r.value}{r.unit && <small>{r.unit}</small>}</>}
            </span>
            {/* 언제 값인지는 지우지 않는다 — 끊긴 동안 옛값이 지금 값처럼 보인다 (§9.10) */}
            <span className={`reading-age${r.stale ? ' old' : ''}`}>{r.age}</span>
          </button>
        ))}
      </div>

    </section>
  );
}
