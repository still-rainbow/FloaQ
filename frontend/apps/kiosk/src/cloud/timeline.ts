/**
 * 시간 슬라이더 눈금·라벨. 순수 함수 — `test/chart-check.mjs` 가 검증한다.
 *
 * **KST 로 고정한다.** 브라우저 타임존을 쓰면 해외 설정 PC 에서 날짜 경계가 밀린다 —
 * 조업 해역도 ROMS 원자료(predcDt)도 한국 시각 기준이다.
 * Intl 대신 +9시간을 더해 UTC 필드로 읽는다. 한국은 서머타임이 없어 오프셋이 고정이다.
 */

const KST_OFFSET_MS = 9 * 3600_000;
const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토'];

const pad = (n: number) => String(n).padStart(2, '0');

function kst(iso: string) {
  const d = new Date(new Date(iso).getTime() + KST_OFFSET_MS);
  return { month: d.getUTCMonth() + 1, day: d.getUTCDate(), hour: d.getUTCHours(), weekday: d.getUTCDay() };
}

export interface DayTick {
  /** times 안의 위치 — 슬라이더 값 */
  index: number;
  /** 슬라이더 폭 대비 위치(%) */
  pct: number;
  /** "09.15" */
  label: string;
}

/**
 * KST 자정마다 날짜 눈금. 해양포털 슬라이더와 같은 읽기 방식이다.
 *
 * 위치는 **시각이 아니라 인덱스 비율**이다. 슬라이더가 인덱스로 움직이므로 눈금도 그래야 맞는다 —
 * 예측 시각 간격이 중간에 벌어져도 눈금과 손잡이가 어긋나지 않는다.
 */
export function dayTicks(times: string[]): DayTick[] {
  if (times.length < 2) {
    return [];
  }
  const last = times.length - 1;
  return times.flatMap((t, i) => {
    const k = kst(t);
    return k.hour === 0 ? [{ index: i, pct: (i / last) * 100, label: `${pad(k.month)}.${pad(k.day)}` }] : [];
  });
}

/** "9/15(화) 06시" */
export function frameLabel(iso: string): string {
  const k = kst(iso);
  return `${k.month}/${k.day}(${WEEKDAY[k.weekday]}) ${pad(k.hour)}시`;
}
