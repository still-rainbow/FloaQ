/**
 * 표류 추정 고리 배율. **Pi · 관제 · 키오스크가 같은 값을 써야 한다.**
 *
 * 정본은 웹 팀과 합의한 「Pi ↔ 관제 표류 위치 추정 공통 구현 명세」 §6 이고,
 * Pi 쪽 같은 상수는 `iot/pi/floaq/drift.py` 의 `SIGMA_SCALE` 이다. 세 곳이
 * 같은 숫자를 각자 적고 있으면 한 곳만 고쳐지고 아무도 모른다 — 프런트 두
 * 앱만이라도 여기 하나로 모은다.
 *
 * ⚠ **정규분포 이론값이 아니다.** 2차원 정규분포라면 √(−2 ln(1−p)) 로
 *   1.177 · 1.665 · 2.448 인데, 입자 4만 개로 재 보니 1.22 · 1.69 · 2.36
 *   이었다(네 조건에서 ±2% 안). 바깥이 이론보다 좁은 것은 풍압 계수에 상한이
 *   있어 꼬리가 짧기 때문이다. **모델이 바뀌면 다시 검증해야 한다.**
 */
export const RING_K = { p50: 1.22, p75: 1.69, p95: 2.36 } as const;

/**
 * 1σ 타원에 곱해 세 고리를 그린다. 지도의 `setBand` 에 그대로 넘긴다.
 * 넓은 것부터다 — `BAND_RAMP[0]` 이 95% 다.
 */
export const RAMP_FROM_SIGMA: [number, number, number] =
  [RING_K.p95, RING_K.p75, RING_K.p50];

/**
 * 95% 고리를 1 로 둔 비율. `Uncertainty` 처럼 **이미 95% 로 곱해진** 축을
 * 넘길 때 쓴다.
 *
 * 🔴 {@link RAMP_FROM_SIGMA} 와 헷갈리면 타원이 2.36배 크거나 작게 그려진다.
 *    축이 1σ 면 위쪽, 95% 면 이쪽이다.
 */
export const BAND_RAMP: [number, number, number] =
  [1, RING_K.p75 / RING_K.p95, RING_K.p50 / RING_K.p95];
