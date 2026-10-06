/**
 * 좌표 DDM(도분) 표기(신규 2).
 *
 * 십진도를 쓰지 말자는 게 아니라, **관제·무전으로 읽어 주는 상황**을 고려해
 * 도분 형식으로도 표시하고 복사할 수 있게 한다. 무전으로 "35점1234도"라고 부르는 사람은 없다.
 */

const dm = (v: number, pos: string, neg: string) => {
  const hemi = v >= 0 ? pos : neg;
  const abs = Math.abs(v);
  const deg = Math.floor(abs);
  const min = (abs - deg) * 60;
  return `${deg}° ${min.toFixed(3)}' ${hemi}`;
};

export const ddmLat = (lat: number) => dm(lat, 'N', 'S');
export const ddmLon = (lon: number) => dm(lon, 'E', 'W');

/** `[lng, lat]` (MapLibre 순서) 를 받아 읽는 순서인 위도·경도로 낸다. */
export function ddm([lng, lat]: [number, number]) {
  return `${ddmLat(lat)}, ${ddmLon(lng)}`;
}

/** 십진도 병기용. 기록·API 는 계속 십진도가 정본이다. */
export function decimal([lng, lat]: [number, number]) {
  return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
}

/**
 * 클립보드 복사. 실패해도 화면은 그대로 둔다 —
 * 권한 거부·비보안 컨텍스트에서 throw 되는데, 좌표는 화면에 이미 보이므로 치명적이지 않다.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
