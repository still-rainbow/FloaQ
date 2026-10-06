/**
 * 갱신 주기가 3분에서 3개월까지 벌어진다.
 * 값만 보여주면 사용자가 오래된 값을 오늘 값으로 읽는다.
 * 조업 판단에 쓰이는 화면에서는 그냥 오정보다.
 *
 * 오프라인일 때만이 아니라 온라인일 때도 항상 붙인다 —
 * 원본 데이터 자체가 오래된 경우가 있다.
 */
export function formatAge(observedAt: string | Date, now: Date = new Date()): string {
  const t = typeof observedAt === 'string' ? new Date(observedAt) : observedAt;
  const sec = Math.max(0, Math.floor((now.getTime() - t.getTime()) / 1000));

  if (sec < 60) return '방금';
  if (sec < 3600) return `${Math.floor(sec / 60)}분 전`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}시간 전`;
  return `${Math.floor(sec / 86400)}일 전`;
}
