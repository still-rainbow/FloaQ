import type { Reading } from '../types';

// 값 아래 출처·관측 시각을 항상 붙인다. 연동 주기가 3분~3개월이라
// 시각 없이 값만 보면 오래된 값을 지금 값으로 읽는다(계획.md §9.18).
//
// 값은 목 데이터의 HTML 문자열이다. API 가 붙으면 구조화된 값으로 바꾸고 이 dangerously 를 걷어낸다.

export function Readings({ rows }: { rows: Reading[] }) {
  return (
    <div className="readings">
      {rows.map(([label, value, meta, stale, detail], i) => (
        <div className={`reading${stale ? ' is-stale' : ''}${detail ? ' has-detail' : ''}`} key={i}>
          <span className="reading-label">{label}</span>
          <span className="reading-value" dangerouslySetInnerHTML={{ __html: value }} />
          {/* 관측값에는 출처·시각을 반드시 붙이지만, 등록 정보처럼 출처가 하나뿐인 칸은 비워 둔다.
              빈 span 을 두면 격자 한 줄과 gap 이 그대로 남아 행 높이가 들쭉날쭉해진다. */}
          {meta ? <span className="reading-meta">{meta}</span> : null}
          {/* 값에 딸린 정보(최대 파고·풍향·만조 등)는 시각 줄에 섞지 않고 값 아래에 둔다 */}
          {detail ? <span className="reading-detail">{detail}</span> : null}
        </div>
      ))}
    </div>
  );
}
