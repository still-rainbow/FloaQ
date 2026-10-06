import type { LngLat } from '@floaq/shared';
import { LEEWAY_BUOY, LEEWAY_HELD_UNKNOWN, LEEWAY_PERSON, MAX_DRIFT_SEC, estimate, splitOf } from './drift';

import type { Leeway, Sea } from './drift';
import type { Incident, Uncertainty } from '../types';

/** 어디서 몇 초를 흘렸나. 위치와 범위가 이 한 쌍에서 나온다 */
export interface Span {
  from: LngLat;
  sec: number;
}

/**
 * 슬라이더 Δt 를 반영한 **화면에 실제로 그릴 위치**.
 *
 * 지도와 좌표 표시가 이 값 하나를 같이 쓴다. 각자 계산하면
 * 지도의 원과 패널에 적힌 좌표가 어긋나고, 그 순간 화면 전체를 믿을 수 없게 된다.
 */
export interface Placed {
  at: LngLat;
  band: Uncertainty | null;
  movedM: number;
  /**
   * 이 위치가 나온 출발점과 경과. <b>더 흘려 보려면 여기서 다시 계산한다</b> —
   * 이미 그린 범위를 또 미는 방식은 같은 불확실성을 두 번 세게 된다(drift.ts 참고).
   * 수색 화면이 시계를 따로 돌릴 때 쓴다.
   */
  span: Span;
  /**
   * 이 위치를 만든 <b>표류 계수</b>. 수색 화면이 같은 대상을 더 흘릴 때 이것을 그대로 써야 한다 —
   * 밖에서 `person 이면 사람 계수` 처럼 다시 고르면, 잡았는지 모를 때 쓰는
   * {@link LEEWAY_HELD_UNKNOWN} 을 놓쳐 지도와 수색 화면의 범위가 어긋난다(2026-09-18).
   */
  leeway: Leeway;
  /**
   * 잡았는지 모르는 경우인가. 두 경우가 벌어지는 거리는 시간이 늘면 같이 늘어나므로
   * 거리를 굳혀 두지 않고 {@link splitOf} 로 그때그때 다시 센다.
   */
  split: boolean;
  /**
   * 🔴 너무 오래 끊겨 <b>추정을 포기한 자리</b>. 이때 {@link at} 은 계산 결과가 아니라
   * 마지막으로 받은 위치 그대로이고 {@link band} 는 null 이다.
   * 화면은 "여기 있다"가 아니라 <b>"여기까지만 안다"</b>로 적어야 한다(drift.ts MAX_DRIFT_SEC).
   */
  beyond?: boolean;
}

export interface IncidentView {
  buoy: Placed | null;
  person: Placed | null;
  /**
   * 부표 버튼이 눌렸을 때의 사람 추정 위치. 데이터에는 person 이 없다(눌렸으면 부표 = 사람으로 본다).
   * 그래도 버튼이 잘못 눌렸을 수 있으니 부표와 **따로** 계산한다 —
   * 익수 지점에서 사고 후 경과 시간만큼 사람 계수로 흘린 위치다. 부표 위치를 쓰면 확인하는 의미가 없다.
   */
  personAlt: Placed | null;
  /** 마지막으로 받은 선박 위치. <b>band 는 항상 null 이다</b> — 배는 표류 추정을 하지 않는다. */
  ship: Placed | null;
  /** 둘 중 더 많이 흘러간 거리 — 슬라이더 옆에 적는다 */
  movedM: number;
  /** 추정된 것이 하나도 없으면 슬라이더는 의미가 없다 */
  hasEstimate: boolean;
  /** Δt 를 먹여 앞당겨 그린 상태인가. 배지·좌표 라벨을 '추정'으로 바꾸는 근거다. */
  projected: boolean;
}



/** 'HH:MM:SS' → 하루 중 초 */
const secOf = (t: string): number => {
  const [h, m, s] = t.split(':').map(Number);
  return (h ?? 0) * 3600 + (m ?? 0) * 60 + (s ?? 0);
};

/**
 * 사람 추정의 출발점과 경과 시간을 고른다.
 *
 * <p>부표를 놓친 자리가 있으면 거기서부터다 — 그 전 구간은 부표와 함께 흘렀으므로
 * 이미 부표 위치에 반영돼 있다. 놓친 적이 없으면 익수 지점에서 사고 후 전체를 센다.</p>
 */
function personSpan(incident: Incident, b: Incident['map']['buoy']): Span | null {
  const detectAt = incident.stages.detect.at;

  if (b?.releasedAt && b.releasedFrom && detectAt) {
    // 놓친 뒤로 흐른 시간. 사고 시각과의 차이를 전체 경과에서 뺀다
    const sinceRelease = incident.elapsedSec - (secOf(b.releasedAt) - secOf(detectAt));
    if (sinceRelease > 0) {
      return { from: b.releasedFrom, sec: sinceRelease };
    }
  }

  const from = incident.map.mob ?? b?.lastFixAt ?? null;
  return from ? { from, sec: incident.elapsedSec } : null;
}

/**
 * 한 대상을 **출발점에서 한 걸음에** 흘려 화면에 놓는다.
 *
 * <p>Δt 를 따로 굴리지 않고 {@code 경과 + Δt} 로 한 번에 센다 — 두 걸음으로 나누면
 * 첫 걸음에서 이미 센 계수 폭·좌우 성분을 둘째 걸음에서 또 더하게 된다.</p>
 *
 * @param splitM 부표를 잡고 있나 놓았나 모를 때 두 경우가 벌어지는 거리(m). 0 이면 해당 없음
 */
function place(sea: Sea, span: Span, dt: number, leeway: Leeway, split = false): Placed {
  const sec = span.sec + dt;
  /*
   * 🔴 한계를 넘으면 <b>아무것도 그리지 않는다.</b> 마지막으로 받은 자리만 남긴다.
   * 조류가 그 사이 여러 번 뒤집혔을 텐데 등속으로 밀면 타원이 수십 km 로 벌어지고
   * 그 안에 육지가 절반이다 — 넓어서 틀린 게 아니라 <b>방향 자체가 틀린다</b>(drift.ts MAX_DRIFT_SEC).
   */
  if (sec > MAX_DRIFT_SEC) {
    return {
      at: span.from, band: null, movedM: 0,
      span: { from: span.from, sec }, leeway, split, beyond: true,
    };
  }
  const e = estimate(span.from, sea, sec, leeway, split ? splitOf(sea, sec) : 0);
  return {
    at: e.at,
    // 흘린 시간이 없으면 지금 받고 있는 값이다. 정확한 값에 범위를 씌우면 거짓말이 된다
    band: sec > 0 ? e.band : null,
    movedM: e.movedM,
    span: { from: span.from, sec },
    leeway,
    split,
  };
}

/**
 * 이미 놓인 위치를 <b>sec 초 더</b> 흘린다. 지도에 그린 것과 <b>같은 출발점·같은 계수</b>로
 * 한 걸음에 다시 세므로 두 화면의 범위가 어긋날 수 없다.
 *
 * <p>수색 화면이 자기 시계(simSec)를 돌릴 때 쓴다. 이미 그린 범위를 또 미는 방식이 아니라
 * 출발점에서 통째로 다시 세는 것이 핵심이다 — 나눠 세면 같은 불확실성을 두 번 센다(drift.ts).</p>
 */
export function advance(p: Placed, sea: Sea, sec: number): Placed {
  return place(sea, p.span, sec, p.leeway, p.split);
}

/**
 * @param sea 사고 지점의 바다 값(useSea). <b>null 이면 추정을 그리지 않는다</b> —
 *            임의의 기본값으로 흘려보내면 그 원이 근거 있는 것처럼 보인다.
 */
export function incidentView(incident: Incident | null, dt: number, sea: Sea | null): IncidentView {
  /**
   * 바다 값이 없으면 <b>받은 위치만</b> 남긴다. Δt 를 먹여도 흘릴 방향을 모른다.
   *
   * <p>사람은 아예 그리지 않는다 — 사람 위치는 처음부터 끝까지 계산 결과이고,
   * 계산할 입력이 없으면 세울 자리가 없다. 임의의 좌표를 쓰면 그 마커가 근거 있는 것처럼 보인다.</p>
   */
  if (sea === null) {
    const b0 = incident?.map.buoy ?? null;
    return {
      // 부표는 실제로 받은 마지막 위치다. 그것만 그대로 둔다
      buoy: b0 ? { at: b0.at, band: null, movedM: 0, span: { from: b0.at, sec: 0 },
                   leeway: LEEWAY_BUOY, split: false } : null,
      person: null,
      personAlt: null,
      ship: incident
        ? { at: incident.map.ship, band: null, movedM: 0, span: { from: incident.map.ship, sec: 0 },
            leeway: LEEWAY_BUOY, split: false }
        : null,
      movedM: 0,
      hasEstimate: false,
      projected: false,
    };
  }

  const b = incident?.map.buoy ?? null;
  const p = incident?.map.person ?? null;

  /**
   * 배는 <b>마지막으로 받은 자리 그대로</b> 둔다. 어디로 흘러갈지는 계산하지 않는다(2026-09-17).
   * 배의 풍압 계수를 모르는 채로 부표 값을 빌려 쓰고 있었고, 그렇게 나온 범위는 근거가 없다(lib/kind.ts).
   */
  const ship: Placed | null = incident
    ? { at: incident.map.ship, band: null, movedM: 0, span: { from: incident.map.ship, sec: 0 },
        leeway: LEEWAY_BUOY, split: false }
    : null;

  /**
   * **지금 위치부터 추정이다.** 통신이 끊긴 부표는 마지막 실측 이후에도 계속 흘러간다 —
   * 마지막으로 받은 자리에 그대로 찍어 두면 12분 전 위치를 지금 위치로 보여 주는 셈이다.
   * 그래서 {@code lastFixAt} 에서 {@code ageSec}(마지막 수신 후 경과) 만큼 먼저 흘린다.
   *
   * 실측 중이면 흘리지 않는다 — 지금 값을 받고 있으므로 계산할 것이 없다.
   */
  const buoySpan: Span | null = b
    ? (b.fix === 'estimated' ? { from: b.lastFixAt, sec: b.ageSec } : { from: b.at, sec: 0 })
    : null;

  /**
   * 사람에게는 위치 발신 수단이 없다. 그런데 **부표를 잡고 있던 동안은 부표가 곧 사람이다** —
   * 그 구간을 사람 계수로 세면 안 된다. 부표는 바람을 3% 타고 사람은 1% 라 3배 차이가 난다.
   *
   * 그래서 기점을 셋으로 가른다.
   *   놓친 적 있음   놓친 자리에서, 놓친 뒤 경과만큼, 사람 계수로
   *   아직 잡고 있음 부표 위치가 곧 사람 위치다 — 따로 추정하지 않는다
   *   잡은 적 없음   익수 지점에서 사고 후 경과만큼
   *
   * ⚠ LoRa 가 끊기면 눌림도 위치도 오지 않는다. 그때의 "눌림 끊김"은 놓은 것이 아니라
   *   더는 모르는 것이다 — 서버가 최신 수신이 눌린 상태인지 보고 가른다(E9).
   */
  const personSp = incident && p ? personSpan(incident, b) : null;

  /**
   * 🔴 <b>끊겼는데 끊길 때까지 눌려 있었다.</b> 놓은 것이 아니라 더는 모르는 것이다(types.ts).
   *
   * <p>계속 잡고 있었다면 사람은 부표를 따라 3% 로, 끊긴 직후 놓았다면 1% 로 흘렀다.
   * 어느 쪽인지 고를 근거가 없어 <b>두 경우의 중간</b>에 중심을 두고, 사이 거리만큼 넓혀
   * 하나의 타원으로 덮는다. 이 경우에만 사람 마커가 부표와 따로 선다 —
   * 잡고 있는 것이 확인될 때는 부표 위치가 곧 사람 위치라 따로 그리지 않는다.</p>
   */
  const unsure = !!b && b.fix === 'estimated' && b.heldAtLastFix && !b.releasedAt;
  const unsureSpan: Span | null = unsure && b ? { from: b.lastFixAt, sec: b.ageSec } : null;

  // Δt 는 실측이든 추정이든 똑같이 먹인다.
  // 지금 정확한 위치를 받고 있어도 '10분 뒤엔 어디쯤일까'는 여전히 필요한 질문이다 —
  // 구조 세력에게 필요한 것은 지금 위치가 아니라 도착할 때쯤의 위치다.
  // Δt 가 0 인 실측만 불확실 범위를 그리지 않는다. 정확한 값에 원을 씌우면 거짓말이 된다.
  const buoy = buoySpan ? place(sea, buoySpan, dt, LEEWAY_BUOY) : null;
  const person = unsureSpan
    ? place(sea, unsureSpan, dt, LEEWAY_HELD_UNKNOWN, true)
    : personSp ? place(sea, personSp, dt, LEEWAY_PERSON) : null;

  // 부표 버튼이 눌려 사람 마커가 따로 없을 때의 확인용. 버튼이 잘못 눌렸을 수 있어 부표와 독립으로 센다
  const altSp = incident && b?.heldAt && !p ? personSpan(incident, b) : null;
  const personAlt = altSp ? place(sea, altSp, dt, LEEWAY_PERSON) : null;

  return {
    buoy,
    person,
    personAlt,
    ship,
    movedM: Math.max(buoy?.movedM ?? 0, person?.movedM ?? 0),
    hasEstimate: b?.fix === 'estimated' || !!p || unsure || dt > 0,
    projected: dt > 0,
  };
}
