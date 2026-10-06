import { BASIS_TEXT } from './ocean';
import type { SeaReading } from './ocean';
import type { OceanCategory, Reading } from '../types';
import { hm, md } from './time';

/**
 * 상세 패널의 <b>해양 정보</b> 표. 지금 받고 있는 값(`/api/ocean/*`)으로 만든다 —
 * 하드코딩 표(mock/data.ts `CATS`)를 걷어낸 자리다(2026-09-18).
 *
 * <p>전에는 다섯 줄(기상 특보 · 유의파고 · 풍속 · 수온 · 시정)과 네 줄(조류 · 정조 · 조위 · 유속 예측)이
 * 고정값이었다. 사고가 부산이든 목포든, 오늘이든 지난달이든 <b>늘 같은 숫자</b>가 떴다.
 * 표류 추정은 진짜 값으로 계산하면서 그 옆의 표는 가짜였다.</p>
 *
 * <p>그래서 <b>받는 것만 적는다.</b> 기상 특보 · 유의파고 · 시정 · 정조 · 조위는 아직 안 받으므로
 * 줄 자체가 없다. 빈 줄을 '—' 로 남기면 "값이 없다"가 아니라 "여기에 값이 있어야 한다"로 읽히고,
 * 지어낸 숫자를 남기면 화면이 실데이터인 척한다.</p>
 */

/** 북 기준 방위를 여덟 방향 이름으로. 숫자만 있으면 지도를 안 보고는 못 읽는다 */
const COMPASS = ['북', '북동', '동', '남동', '남', '남서', '서', '북서'] as const;
export const compass = (deg: number): string =>
  COMPASS[Math.round((((deg % 360) + 360) % 360) / 45) % 8]!;

/** m/s → kn. 해도·항해 계기가 노트를 쓴다 */
const KN = 1.943844;

/**
 * 관측이 얼마나 오래됐나. 값 자체보다 이게 더 중요할 때가 있다.
 *
 * <p>⚠ <b>조류는 예보라 시각이 미래일 수 있다.</b> ROMS 는 정시 예보를 미리 내려 주므로
 * 낮 12시 예보를 오전 11시에 보는 일이 흔하다. 그때 "몇 분 전 관측"은 틀린 말이라
 * <b>앞으로 올 값</b>이라고 적는다 — 전에는 그 경우 ISO 문자열이 그대로 찍혔다(2026-09-21).</p>
 */
function ago(at: string | null | undefined): string {
  if (!at) return '수신 시각 모름';
  const sec = Math.round((Date.now() - new Date(at).getTime()) / 1000);
  if (!Number.isFinite(sec)) return '수신 시각 모름';
  if (sec < 0) {
    const ahead = -sec;
    return ahead < 3600 ? `${Math.max(1, Math.round(ahead / 60))}분 뒤 예보` : `${Math.round(ahead / 3600)}시간 뒤 예보`;
  }
  if (sec < 90) return '방금 관측';
  if (sec < 3600) return `${Math.round(sec / 60)}분 전 관측`;
  return `${Math.round(sec / 3600)}시간 전 관측`;
}

/** 얼마나 먼 곳의 값인가. 이 자리 값이 아니라는 사실을 숨기지 않는다 */
const far = (km: number | undefined, name: string | null | undefined): string | undefined => {
  if (km == null) return undefined;
  const where = name ? `${name} ` : '';
  return km < 1 ? `${where}바로 앞` : `${where}${km.toFixed(1)}km 떨어진 값`;
};

/**
 * 받은 바다 값 → 화면 표 두 개.
 *
 * @param sea `useSea` 가 준 값. null 이면 아직 못 받았거나 서버가 답하지 않은 것이다 —
 *            그때는 줄이 하나도 없는 표를 준다. 화면이 "해양 정보 없음"을 그리면 된다.
 * @param waterTempC 사고가 들고 있는 수온. 해양 API 가 아니라 사고 쪽에서 온다
 */
export function oceanRows(sea: SeaReading | null, waterTempC?: number): Record<'safe' | 'nav', OceanCategory> {
  /**
   * 값이 <b>언제 것인지</b>를 적는 법. 지금 받는 값은 "몇 분 전"이 쓸모 있고,
   * 사고에 박아 둔 값은 <b>그날 몇 시</b>가 쓸모 있다 — 지난 사고에 "117시간 전"은 셈만 맞는 말이다.
   */
  const stamp = (at: string) => (sea?.stored ? `${md(at)} ${hm(at)} 값` : ago(at));
  const safe: Reading[] = [];
  const nav: Reading[] = [];

  if (sea?.wind) {
    safe.push([
      '풍속 · 풍향',
      `${sea.sea.windSpeed.toFixed(1)}<small>m/s</small>`,
      stamp(sea.wind.at),
      0,
      // ⚠ sea.windDir 은 <b>흘러가는 쪽</b>이다(ocean.ts 가 +180° 한다). 표에는 관측 관례대로
      //   불어오는 쪽을 적는다 — 기상청 값과 달라 보이면 그 자체가 오해를 부른다
      `${compass(sea.sea.windDir + 180)} ${Math.round((sea.sea.windDir + 180) % 360)}° · ${far(sea.wind.distanceKm, sea.wind.name) ?? ''}`,
    ]);
  }

  if (waterTempC != null && Number.isFinite(waterTempC)) {
    safe.push(['수온', `${waterTempC.toFixed(1)}<small>℃</small>`, '사고 기록값', 0]);
  }

  if (sea?.current) {
    nav.push([
      '조류',
      `${(sea.sea.currentSpeed * KN).toFixed(1)}<small>kn</small>`,
      stamp(sea.current.at),
      0,
      `${compass(sea.sea.currentDir)} ${Math.round(sea.sea.currentDir)}° · ${far(sea.current.distanceKm, sea.current.name) ?? ''}`,
    ]);
    if (sea.spreadMs != null && sea.spreadMs > 0) {
      nav.push([
        '유속 불확실',
        `±${(sea.spreadMs * KN).toFixed(1)}<small>kn</small>`,
        '이웃 격자와의 차이',
        sea.spreadMs > 0.3 ? 1 : 0,
        '이 값이 클수록 표류 범위가 넓어집니다',
      ]);
    }
  }

  return {
    safe: { title: '안전', src: sea ? BASIS_TEXT[sea.basis] : '해양 정보를 받지 못했습니다', rows: safe },
    nav: { title: '항해', src: '출처: 국립해양조사원 · 기상청', rows: nav },
  };
}
