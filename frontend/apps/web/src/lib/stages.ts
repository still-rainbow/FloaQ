import { isMob } from './kind';
import type { Incident, Stages } from '../types';

/**
 * 대응 단계 상황판(신규 10)의 판정.
 *
 * **새 사고 상태를 만들지 않는다.** 기존 상태·필드로 판정만 하는 표시 레이어다.
 * 상태를 늘리면 kiosk·백엔드·상태 기계가 전부 따라 늘어난다.
 *
 * 단계는 선형이 아니다 — ③ 해경 접수와 ④ 사고자 발견은 순서가 뒤바뀔 수 있다.
 * 부표 버튼은 발사 몇 초 뒤에 눌릴 수 있고 해경 접수는 1분 뒤일 수 있다.
 * 그래서 진행 바가 아니라 **체크리스트**로 그린다.
 */

export type StageKey = keyof Stages;

/**
 * ⚠ 결정 필요 2 — 단계 ④ 의 판정 근거.
 *
 *   'A' 부표 버튼 눌림 = 사고자 발견   (기존 데이터로 자동 판정. 지금 이 값)
 *   'B' 구조자의 수동 확인 입력        (의미는 정확하나 입력 UI·권한 정의 필요)
 *   'C' 단계를 둘로 분리                (정확하나 단계가 늘어남)
 *
 * A 를 골라 둔 이유는 지금 가진 데이터만으로 화면이 성립하기 때문이다.
 * "사고자가 부표를 잡았다"와 "구조자가 발견했다"는 엄밀히 다른 사건이라는 점은 남아 있다.
 * 바꿀 때는 이 상수와 아래 FOUND_LABEL 만 손대면 된다.
 */
export const FOUND_BASIS: 'A' | 'B' | 'C' = 'A';

/** ⚠ 결정 필요 3 — 단계 ④ 명칭. `사고자 발견` / `사고자 확인` / `생존 확인` */
export const FOUND_LABEL = '사고자 발견';

export const STAGE_ORDER: StageKey[] = ['detect', 'report', 'ack', 'found', 'close'];

/**
 * <b>칸 수는 사고 종류를 따른다.</b> 익수는 다섯, 나머지는 넷이다.
 *
 * <p>① 탐지 · 부표 발사 는 카메라가 잡고 부표를 쏘을 때만 있는 일이다. 기관 고장·화재는
 * 사람이 단말에서 직접 누른다 — 그 누름과 ② 구조 요청(발신)은 <b>2초 차이의 한 동작</b>이라
 * 칸 둘을 나눠 두면 옆에 같은 시각이 두 번 적힐 뿐이다(2026-09-18).</p>
 *
 * <p>⚠ <b>데이터를 버리는 것이 아니다.</b> `stages.detect` 는 그대로 저장되고 걸린 시간도
 * 여전히 거기서 센다(CloseReport took). 화면에서 칸 하나를 접는 것뿐이다.</p>
 */
export const orderOf = (x: Incident): StageKey[] =>
  (isMob(x) ? STAGE_ORDER : STAGE_ORDER.filter((k) => k !== 'detect'));

export const STAGE_LABEL: Record<StageKey, string> = {
  detect: '탐지 · 부표 발사',
  report: '구조 요청',
  ack: '구조대 대응',
  found: FOUND_LABEL,
  close: '종료',
};

/**
 * MOB 이 아니면 ④ 의 이름이 맞지 않는다 — 배 위치를 아는 사고에 "사고자 발견"은 없다.
 * ①(탐지 · 부표 발사)은 이름을 바꾸는 대신 칸을 통째로 뺀다(orderOf).
 */
const VESSEL_LABEL: Partial<Record<StageKey, string>> = {
  found: '현장 도착',
};

export const labelFor = (x: Incident, k: StageKey) =>
  (isMob(x) ? STAGE_LABEL[k] : VESSEL_LABEL[k] ?? STAGE_LABEL[k]);

/** 판정 근거를 화면에 같이 적는다 — 왜 켜졌는지 모르면 신뢰할 수 없다. */
export const STAGE_BASIS: Record<StageKey, string> = {
  detect: 'status = DETECT 또는 WAIT',
  report: 'status = REPORT',
  ack: 'acknowledged_at 존재',
  found: FOUND_BASIS === 'A' ? '부표 버튼 눌림' : '구조자 확인 입력',
  close: 'status = CLOSE',
};

export const stagesOf = (x: Incident): [StageKey, string, Stages[StageKey]][] =>
  orderOf(x).map((k) => [k, labelFor(x, k), x.stages[k]]);

export const doneCount = (x: Incident) =>
  orderOf(x).filter((k) => x.stages[k].at).length;

/**
 * 지금 어느 단계까지 왔는가 — **가장 최근에 달성된 단계**.
 *
 * 단계 번호가 큰 쪽을 고르지 않는다. ③ 해경 접수와 ④ 사고자 발견은 순서가 뒤바뀌므로
 * 번호로 고르면 방금 일어난 일이 아니라 늦게 도착한 일을 "현재"로 표시하게 된다.
 * 시각이 같은 날 안의 HH:MM:SS 라 문자열 비교로 충분하다.
 */
export function currentStage(x: Incident): StageKey | null {
  let best: StageKey | null = null;
  for (const k of orderOf(x)) {
    const at = x.stages[k].at;
    if (!at) continue;
    if (!best || at > (x.stages[best].at ?? '')) best = k;
  }
  return best;
}

export const currentLabel = (x: Incident) => {
  const k = currentStage(x);
  return k ? labelFor(x, k) : '대기';
};
