import { ago } from '../lib/time';
import type { Buoy, Urgency } from '../types';

/**
 * 0.3 의 두 배지. S-03(선내 단말)과 W-03(관제 웹)이 **같은 컴포넌트**를 쓴다.
 * 구조는 선원과 해경 어느 쪽이든 수행하므로 위치 표시가 양쪽에서 달라서는 안 된다.
 *
 * 두 배지는 서로 **독립**이다. 위치가 실측인지와 사람이 부표를 잡았는지는 다른 정보이고,
 * 둘을 곱해 "사고 유형" 같은 걸 만들지 않는다(0.2). 네 조합이 전부 정상적으로 나올 수 있다.
 */

interface PositionProps {
  buoy: Buoy | null;
  /** 슬라이더로 앞당겨 그린 경우의 눈금 이름(예: '+30분'). 있으면 실측이어도 추정으로 표시한다. */
  dtLabel?: string;
  /** 부표가 아니라 사람 추정 마커에 붙일 때 */
  label?: string;
  /**
   * 부표가 없는 이유. <b>안 쏜 것과 쏘다 실패한 것은 다르다</b> —
   * 실패면 이 배가 부표를 못 쏘는 상태라는 뜻이고, 구조 쪽은 사람만 찾아야 한다.
   * ⚠ 실패 사유는 서버에 아직 칸이 없다(팀원 edge 마이그레이션 대기).
   */
  failReason?: string | null;
}

/** `● 부표 (실측) · 3초 전 수신` / `○ 부표 (추정) · 마지막 수신 12분 전` — 지도 라벨 `사람 (추정)` 과 같은 괄호 표기 */
export function PositionBadge({ buoy, label = '부표', dtLabel, failReason }: PositionProps) {
  if (!buoy) {
    // 물에 뜬 부표가 없다 — 구조 쪽에서 찾을 주황색이 바다에 없다는 뜻이다
    return (
      <span className={`pos-badge is-none${failReason ? ' is-failed' : ''}`}
            title={failReason
              ? `부표를 쏘지만 실패해서 바다에 부표가 없습니다 (${failReason})`
              : '부표를 쏬 적이 없어 바다에 부표가 없습니다'}>
        <i />{failReason ? '부표 없음 · 발사 실패' : '부표 없음 · 쏘 적 없음'}
      </span>
    );
  }

  // 화면에 그려진 것이 무엇인지를 말한다. 데이터가 실측이어도 Δt 로 옮겨 그렸으면 그건 추정이다.
  const measured = buoy.fix === 'measured' && !dtLabel;
  return (
    <span
      className={`pos-badge ${measured ? 'is-measured' : 'is-estimated'}`}
      title={measured
        ? '부표가 지금 알려온 위치입니다'
        : dtLabel
          ? `지금 자리에서 ${dtLabel} 동안 조류·바람에 떠내려갔을 때 있을 만한 자리입니다`
          : '부표 신호가 끊겨, 마지막으로 받은 자리에서 조류·바람으로 계산한 자리입니다'}
    >
      <i />
      {/* 배지가 flex + gap 이라 글자 조각이 따로 놓이면 "부표 ( 실측 )"처럼 괄호 안이 벌어진다. 한 덩어리로 묶는다 */}
      <span>
        {label} (<b>{measured ? '실제 위치' : '추정'}</b>) ·{' '}
        {measured
          ? `${ago(buoy.ageSec)} 받음`
          : dtLabel ? `${dtLabel} 뒤` : `마지막으로 받은 것이 ${ago(buoy.ageSec)}`}
      </span>
    </span>
  );
}

/**
 * 부표에서 **LoRa 신호가 들어오고 있는가**. 통신 상태다.
 * 버튼 눌림과는 다른 신호라 모양부터 다르게 둔다 — 이쪽은 알약 + 신호 점.
 */
const lasted = (sec: number) => {
  const m = Math.floor(sec / 60);
  return m > 0 ? `${m}분째` : `${Math.round(sec)}초째`;
};

export function LoraBadge({ buoy }: { buoy: Buoy }) {
  const on = buoy.fix === 'measured';
  return (
    <span className={`lora-badge ${on ? 'is-on' : 'is-off'}`}
          title={on
            ? '부표가 위치를 계속 알려오고 있습니다'
            : `부표 신호가 끊겼습니다. 마지막으로 받은 것이 ${ago(buoy.ageSec)}`}>
      <i />
      {on ? `부표 위치 받는 중 · ${ago(buoy.ageSec)}` : `부표 신호 끊김 · ${lasted(buoy.ageSec)}`}
    </span>
  );
}

/**
 * 사람이 **부표 버튼을 누르고 있는가**. 사람의 상태다.
 * LoRa 가 끊겨도 마지막으로 받은 버튼 상태는 남는다 — 둘은 따로 읽어야 한다. 네모 + 체크.
 */
export function ButtonBadge({ heldAt }: { heldAt: string | null }) {
  return heldAt ? (
    <span className="btn-badge is-on" title={`${heldAt} 부터 부표의 손잡이 버튼이 눌려 있습니다 — 사람이 부표를 잡았다는 뜻입니다`}>
      ✓ 사람이 부표를 잡고 있음
    </span>
  ) : (
    <span className="btn-badge is-off" title="부표의 손잡이 버튼이 눌리지 않았습니다. 못 잡은 것일 수도, 잡았는데 버튼까지 누를 힘이 없는 것일 수도 있습니다">
      ✕ 부표를 잡았는지 확인 안 됨
    </span>
  );
}
export const URG: Record<Urgency, [string, string]> = {
  distress: ['조난', 'urg-d'],
  urgency: ['긴급', 'urg-u'],
};
