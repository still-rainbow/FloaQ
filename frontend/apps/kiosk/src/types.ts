/**
 * 지도에 구역으로 그릴 수 있는 항목.
 *
 * 실제로 격자가 있는 것은 tide·temp 뿐이다 — 파고는 지점 관측, 적조는 텍스트라 구역이 없다.
 * 눌러도 되게 두고, 화면이 "격자 데이터가 없습니다"를 띄운다.
 */
// 'algae'(적조) 를 뺐다 (2026-09-18 요청) — 조사해역이 텍스트라 지도에 그릴 구역이 없다.
// 눌러도 '영역이 없습니다' 만 뜨는 버튼이었다. 값 자체는 조업 표에 그대로 남는다.
export type MetricKey = 'temp' | 'wave' | 'tide' | 'wind';

/** 단말에 등록된 선박. localStorage 에 산다 — 단말 하나에 선박 하나 */
export interface Vessel {
  name: string;
  /** ⚠ 총톤수·승선 인원은 두지 않는다 (2026-09-16) — ERD 의 ship 에 없다. 서버 V8 에서도 함께 뺐다 */
  regno: string;
  /**
   * 설치 캘리브레이션. 선박마다 다른 값은 이 둘뿐이다 (계획.md §6).
   *
   * ⚠ **입력은 받지 않는다**(2026-09-17). Pi 가 자기 `env` 로 갖고 있고 추락 위치 계산도 Pi 가 한다 —
   * 두 곳에서 받으면 어느 값으로 쐈는지 알 수 없다. 화면은 **Pi 가 알려준 값을 보여주기만** 한다.
   *
   * 🔴 아직 Pi 가 이 값을 보내는 토픽이 없다(`ref/mqtt.md` 미정). 그때까지는 빈 값이고,
   * 설정 화면이 "Pi 설정값"이라고 적는다 — 0 으로 그리면 "카메라가 수면 높이"로 읽힌다.
   */
  camH: string;
  launchOff: string;
}

export type CatKey = 'safe' | 'fish' | 'nav' | 'ship';

export interface Reading {
  label: string;
  /** 본문. 숫자든 문구든 평문이다 — HTML 을 넣지 않는다 (XSS 경로가 된다) */
  value: string;
  /** 단위. 작게 붙는다 */
  unit?: string;
  /** value 를 상태 알약으로 그린다 */
  pill?: 'ok' | 'warn' | 'alert';
  /** 저체온 강조 */
  cold?: boolean;
  /** 관측·예측·발표 시각 + 출처. 갱신 주기가 3분~주간이라 항상 붙인다 (§9.18) */
  age: string;
  /** 갱신이 느리거나 끊긴 값. 화면에서 흐리게 표시한다 */
  stale?: boolean;
  /** 누르면 지도에 등치선을 그린다. 없으면 표시 전용 */
  metric?: MetricKey;
}

export interface Category {
  title: string;
  src: string;
  rows: Reading[];
}
