/**
 * 저체온증 생존 추정.
 *
 * 미 해안경비대 Cold Water Survival 표를 **인용한다.** 자체 계산식을 만들면
 * "그 숫자 근거가 뭐냐"에 답할 수 없다 (계획.md §6).
 * 화면에도 출처를 함께 띄운다.
 *
 * 목이 아니라 인용 자료다 — 그래서 mock/ 이 아니라 여기 있다.
 */

interface Survival {
  /** 탈진·의식 소실까지 */
  exh: string;
  /** 생존 가능 시간 */
  surv: string;
}

const TABLE: { max: number; exh: string; surv: string }[] = [
  { max: 0.3, exh: '15~45분', surv: '45분~1.5시간' },
  { max: 4.4, exh: '30~90분', surv: '1.5~3시간' },
  { max: 10, exh: '1~3시간', surv: '1~6시간' },
  { max: 15.6, exh: '2~7시간', surv: '2~40시간' },
  { max: 21.1, exh: '3~12시간', surv: '3시간~무기한' },
  { max: 99, exh: '3시간 이상', surv: '무기한' },
];

export function coldWater(waterTempC: number): Survival {
  return TABLE.find((r) => waterTempC <= r.max) ?? TABLE[TABLE.length - 1]!;
}
