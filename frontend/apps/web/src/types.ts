import type { SeaReading } from './lib/ocean';
import type { LngLat } from '@floaq/shared';

export type Role = 'admin' | 'superadmin';
/** 안전·항해는 탭이 아니라 상세 패널 위의 접히는 "해양 정보"로 옮겼다. */
export type DetailTab = 'ship' | 'incident';
/**
 * 긴급도. 해사 관례의 세 등급 중 <b>안전(SAFETY)은 두지 않는다</b> —
 * 항행 위험을 다른 배에 알리는 통보라 관제가 구조 판단을 할 대상이 아니다.
 */
export type Urgency = 'distress' | 'urgency';

/** 사고 진행 상태. live 만 실시간 수신 대상이다(계획.md §9.13). */
export type IncidentState = 'live' | 'done' | 'cancel' | 'closed';

/**
 * 위치가 실측인지 추정인지. 웹 서비스의 핵심 축이다(0장).
 * 통신이 끊겨도 마커는 사라지지 않는다 — 형태만 바뀐다.
 */
export type Fix = 'measured' | 'estimated';

/** 불확실 범위. 조류·바람의 벡터 합 방향으로 늘어지므로 원이 아니라 타원이다. */
export interface Uncertainty {
  /** 장반경(m) — bearing 방향 */
  a: number;
  /** 단반경(m) */
  b: number;
  /** 장축 방위(°) */
  bearing: number;
}

/**
 * 부표 궤적 — <b>실제로 받은 위치만</b> 담는다.
 *
 * 추정 구간은 여기 두지 않는다. 추정은 해양 공공데이터(조류·바람)로 그때그때 계산하는 것이라
 * 미리 적어 둘 수 있는 값이 아니다 — 적어 두면 <b>바다가 바뀌어도 선이 안 바뀐다.</b>
 * 실측(실선)과 추정(점선)을 갈라 그리는 것은 그대로다(충돌 정리 #9).
 */
export interface Track {
  measured: LngLat[];
}

/**
 * 부표 상태. 0.1 — 네트워크 정상이면 실측, 두절이면 추정.
 * 두 경우 모두 `at` 에 값이 있다. null 이 되는 경우는 발사 자체가 없었을 때뿐이다.
 */
export interface Buoy {
  at: LngLat;
  fix: Fix;
  /** 마지막 실측 수신으로부터 경과 초. 배지의 "3초 전 수신" / "12분 전" */
  ageSec: number;
  /** 마지막으로 실제 받은 위치. 추정의 기준점이다. */
  lastFixAt: LngLat;
  /**
   * 부표 버튼이 **처음** 눌린 시각. null 이면 잡았는지 확인되지 않은 상태다.
   * 0.2 — 위치 상태(실측/추정)와 **독립된 별도 정보**다. 둘을 조합해 사고 유형을 만들지 않는다.
   */
  heldAt: string | null;
  /**
   * 🔴 <b>마지막으로 받은 패킷에서 버튼이 눌려 있었나.</b>
   *
   * <p>LoRa 가 끊기면 위치도 눌림도 함께 끊긴다. 그때의 "눌림 없음"은 <b>놓은 것이 아니라
   * 더는 모르는 것</b>이다. 이 값이 true 이면 사람이 계속 잡고 있었을 수도(부표 계수 3%),
   * 끊긴 직후 놓았을 수도(사람 계수 1%) 있다 — 어느 쪽인지 고를 근거가 없다.</p>
   *
   * <p>그래서 추정은 두 경우의 중간에 중심을 두고 사이 거리만큼 넓힌다
   * (lib/drift.ts `LEEWAY_HELD_UNKNOWN` · `splitOf`).</p>
   *
   * ⚠ 서버가 판정해서 내려 준다(api.md E9). 웹이 `heldAt` 유무로 흉내 내면 안 된다 —
   *   끊기기 전에 이미 놓은 경우와 구별할 수 없다.
   */
  heldAtLastFix: boolean;
  /**
   * 부표를 **놓친** 시각 — 마지막으로 눌림이 확인된 때. 아직 잡고 있으면 null.
   *
   * <b>잡고 있는 동안 사람 위치는 곧 부표 위치다.</b> 놓는 순간부터 둘이 갈라진다 —
   * 부표는 바람을 3%, 사람은 1% 타서 시간이 갈수록 벌어진다.
   * 이 값이 없으면 익수 지점부터 혼자 떠내려간 것으로 잘못 세게 된다.
   */
  releasedAt: string | null;
  /** 놓친 자리(그때의 부표 위치). 사람 추정의 출발점이다 */
  releasedFrom: LngLat | null;
}

/**
 * 사람 추정 위치. 0.2 — 부표 버튼이 눌리지 않았을 때만 별도 마커가 선다.
 * 눌렸으면 부표 위치 = 사람 위치이므로 이 값은 null 이다.
 * 사람은 직접 측정 수단이 없으므로 fix 는 항상 'estimated' 다.
 */
/**
 * 사람 추정 마커를 세울지 여부.
 *
 * <p><b>좌표도 범위도 담지 않는다.</b> 사람은 위치 발신 수단이 없어 <b>언제나 계산 결과</b>다 —
 * 익수 지점(또는 부표를 놓친 자리)에서 실제 조류·바람으로 흘린 값이고, 그 계산은 lib/view.ts 가 한다.
 * 좌표를 미리 적어 두면 바다가 바뀌어도 마커가 안 움직인다.</p>
 */
export interface Person {
  /** 왜 사람 마커가 서는가. 화면에 쓰지 않고 데이터의 뜻을 적어 두는 용도 */
  reason: '부표 버튼 안 눌림' | '부표 없음';
}

export interface Vessel {
  id: string;
  name: string;
  reg: string;
  /** 센서·영상 이상 탐지 결과. 배터리·재장전은 범위 밖이다(§9.15) */
  dev: string;
  devWarn: 0 | 1;
  // 사고 id 를 여기 두지 않는다. 한 배에 사고가 여러 건일 수 있어서 사고 쪽이 ship 을 든다(lib/history.ts).
}

/** Pi 가 올린 mp4 한 개의 메타. ERD 로는 incident_clips 가 된다. */
export interface ClipMeta {
  src: string;
  /** 선내 시계의 하루 중 초. Date 로 두면 브라우저 타임존에 따라 촬영 시각이 밀린다 */
  startSec: number;
  dur: number;
  fps: number;
  /** 익수 확정(t=0)까지의 초. 이 앞 구간이 링 버퍼에서만 얻어지는 부분이다 */
  trigger: number;
  /** 전송된 비율. 사고 메타가 먼저, 영상이 마지막이다(§9.9) */
  got: number;
  /** 영상 그만 받기를 누른 시각(HH:MM:SS). 사고 후 구간은 원래 종결하거나 1시간이 지나야 끝난다 */
  stoppedAt?: string | null;
}

export interface IncidentMap {
  ship: LngLat;
  hdg: number;
  /** 선박 GPS 를 마지막으로 받은 뒤 경과 초. 사고 중에만 받는다. MOB 가 아니면 이것이 "마지막 수신"이다 */
  shipAgeSec?: number;
  /**
   * 위 {@link ship}·{@link hdg}·{@link shipAgeSec} 가 <b>실제로 받은 위치</b>에서 나왔나.
   *
   * <p>false 면 배를 감지된 자리에 그린 것이고 경과는 감지 이후로 센 것이다 — 그 배가 사고 뒤로
   * 위치를 한 번도 안 보냈다는 뜻이다. 목록 응답에는 항적이 없어 늘 false 이므로,
   * 5초마다 오는 목록이 상세에서 받은 진짜 자리를 덮지 않도록 가르는 데 쓴다.</p>
   */
  shipFix?: boolean;
  /** 감지(익수) 지점 */
  mob: LngLat | null;
  mobText?: string;
  buoy: Buoy | null;
  person: Person | null;
  track: Track | null;
  /**
   * 사고자를 발견한 자리(④ 사고자 발견). 부표 잡음으로 확인된 경우 <b>그 순간 부표가 있던 좌표</b>다.
   * 발견 사실만 남기고 자리를 안 남기면, 나중에 리포트를 열어도 어디서 찾았는지 알 수 없다.
   */
  foundAt?: LngLat | null;
}

/**
 * 대응 단계(신규 10). 새 사고 상태를 만들지 않고 기존 필드로 판정만 한다.
 * 순서가 뒤바뀔 수 있으므로 진행 바가 아니라 체크리스트다.
 */
export interface Stage {
  /** 달성 시각. null 이면 미달성(회색) */
  at: string | null;
  /** 오른쪽에 붙는 근거 문구 */
  note?: string;
}

export interface Stages {
  detect: Stage;
  report: Stage;
  ack: Stage;
  found: Stage;
  close: Stage;
}

export interface Incident {
  id: string;
  ship: string;
  day: string;
  state: IncidentState;
  badge: [string, string];
  head: string;
  map: IncidentMap;
  facts: [string, string, string][];
  params: [string, number, string][];
  /**
   * 사고 당시 해항 스냅샷. 진행 중이면 null — 그때는 '지금'이 곶 그때라
   * 공공데이터의 현재 값(mock/data.ts CATS)을 그대로 쓴다.
   */
  ocean?: OceanSnap | null;
  /**
   * 감지 시각(ISO). <b>화면에 적는 값이 아니라 물어보는 데 쓴다</b> —
   * 종결된 사고의 해양 정보를 "그때" 기준으로 받아 오는 기준점이다(lib/useSea.ts).
   * 사람이 읽는 시각은 {@link Stages} 의 {@code detect.at} 이 따로 들고 있다.
   */
  detectedAt: string;
  /**
   * 사고가 나던 때의 바다. <b>사고 행에 박혀 있는 값</b>이라 몇 년 뒤에 열어도 같다
   * (서버 V20260921_1210). 없으면 이 칸이 생기기 전 사고이거나 격자·관측 지점이 멀었던 사고다 —
   * 그때만 화면이 해양 조회로 메운다(lib/useSea.ts).
   */
  oceanSnap: SeaReading | null;
  /**
   * 사진 두 장 — 감지 순간 · 지금(가장 최근 프레임). 서버 {@code /photos} 가 준다.
   *
   * <p>진행 중에는 영상이 없고 이 두 장이 전부다. 실시간 동영상은 배 안 랜에서만 보여
   * 인터넷의 관제 웹은 닿을 수 없다 — 그래서 "지금"은 <b>몇 초마다 새로 받는 최신 사진</b>이다.</p>
   */
  photos: { detect: Photo | null; latest: Photo | null };
  result: string;
  timeline: [string, string, string, string][];
  clip: ClipMeta;
  /** DSC nature of distress 코드를 인용한다. 우리가 만든 분류가 아니다(§9.21) */
  type: { urg: Urgency; label: string; dsc: string };

  /**
   * 담당자·처리 기관은 두지 않는다(2026-09-15 결정). 해경 쪽에서는 신고를 받았는지(stages.ack)만 알 수 있고,
   * 누가 담당하는지·어느 곳에서 처리하는지는 알 수 없다.
   */
  stages: Stages;
  /** 생존 잔여시간 입력 — 수온(℃). 공공데이터에서 이미 받는 값이다(신규 1) */
  waterTemp: number;
  /** 사고 발생 후 경과 초 */
  elapsedSec: number;
  /** 신고 발신 진행. 1분에 8회 반복 중 몇 번째인지 */
  send: { sent: number; total: number } | null;
}

/**
 * [라벨, 값(HTML), 시각, stale, 부가 정보?] — 값만 보이면 3개월 전 값을 오늘 값으로 읽는다(§9.18)
 * 부가 정보는 값에 딸린 정보(최대 파고·풍향·만조 시각 등)다. 시각 줄이 아니라 값 쪽에 붙인다.
 */
export type Reading = [string, string, string, 0 | 1, string?];

export interface OceanCategory {
  title: string;
  src: string;
  rows: Reading[];
}

/**
 * <b>사고 당시의 해항.</b> 종결된 사고를 다시 열었을 때 '지금 바다'를 보여 준다면
 * 9월 7일 사고를 여는 사람에게 <b>오늘 바람을 그런 바람으로 읽힌다</b> — 거짓말이다.
 * 그래서 해항은 사고마다 그 시간의 값을 들고 있어야 한다.
 *
 * <p>⚠ 서버는 지금 해항을 <b>덮어쓴다</b>(`ocean_snapshot` 은 원처당 한 줄 upsert).
 * 사고 시각의 관족값을 남기는 것은 백엔드에 넘긴 일이다 — 여기는 그 자리를 밌다.</p>
 */
export interface OceanSnap {
  /** 사고 시각에 가장 가까운 관족 시각 'HH:MM' */
  at: string;
  rows: Record<'safe' | 'nav', Reading[]>;
}

/** 사진 한 장. {@code url} 은 R2 서명 주소라 {@code <img src>} 에 그대로 쓴다 */
export interface Photo {
  url: string;
  /** 찍힌 시각(ISO). 없으면 Pi 가 안 보낸 것이다 */
  capturedAt: string | null;
  camera: 'L' | 'R' | null;
}
