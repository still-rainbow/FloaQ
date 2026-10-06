/** 경과 초를 사람이 읽는 문구로. 배지·목록·상황판이 같은 표기를 쓰게 한 곳에 둔다. */
export function ago(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}초 전`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}분 전`;
  const h = Math.floor(m / 60);
  return `${h}시간 ${m % 60}분 전`;
}

/** 경과 시간(누적). "12분 05초" */
export function elapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  if (m < 60) return `${m}분 ${String(s).padStart(2, '0')}초`;
  return `${Math.floor(m / 60)}시간 ${m % 60}분`;
}

/** 거리(m) → 읽기 좋은 단위 */
export function dist(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(2)}km` : `${Math.round(m)}m`;
}

/**
 * ISO 시각 → 'HH:MM'. <b>관측 시각처럼 분까지면 충분한 자리</b>에 쓴다 —
 * 해양 관측은 한 시간에 한 번 들어와 초를 적으면 없는 정밀도를 말하게 된다.
 */
export function hm(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** ISO 시각 → 'M월 D일'. 지난 사고의 값이 <b>며칠 전 것인지</b>를 한눈에 보게 한다 */
export function md(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : `${d.getMonth() + 1}월 ${d.getDate()}일`;
}
