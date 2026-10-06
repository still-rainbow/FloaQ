import type { Category, Vessel } from '../types';

/**
 * 목 데이터. 해양 정보(안전·조업·항해)는 EC2 `/cloud` 실데이터로 갈아탔다 — `cloud/readings.ts`.
 * 남은 것은 선박 센서(내 배)와 등록 샘플뿐이다.
 *
 * ⚠ 내 배 행은 아직 목이다. Pi 텔레메트리(속력·침로·롤·피치)가 store 에 들어오면 그걸로 그린다.
 */

/** 내 배가 이 제품의 차별점이다 — 공공데이터만 보여주는 앱은 이미 많다 (§9.18) */
export const SHIP_CAT: Category = {
  title: '내 배 — 지금 상태는?', src: '선박 센서',
  rows: [
    { label: '속력 · 침로', value: '6.4', unit: 'kn', age: '실시간' },
    { label: '선체 동요', value: '롤 3.2', unit: '°', age: '실시간 · 피치 1.1°' },
    { label: '카메라 높이', value: '3.2', unit: 'm', age: '설치 시 등록값' },
  ],
};

export const SAMPLE_VESSEL: Vessel = {
  name: '제7해성호',
  regno: '부산선적 25-1104', camH: '3.2', launchOff: '1.4',
};
