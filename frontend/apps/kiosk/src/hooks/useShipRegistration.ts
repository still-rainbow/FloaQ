import { useCallback, useEffect, useState } from 'react';
import { piUrl } from '@floaq/shared/origins';

/**
 * 선박 등록 — **신청은 HTTP, 상태는 폴링** (`ref/kiosk_시연.md` §4).
 *
 * <p>일생에 한 번이다. Pi 가 신청을 받아 두고 EC2 에 중계하며, 승인은 관제 웹에서 사람이 누른다.</p>
 *
 * <p>🔴 <b>등록 전에는 사고를 못 연다.</b> `ship_id` 가 없으면 MQTT 토픽 경로 자체가
 * 성립하지 않는다 — 그래서 첫 화면이 등록 화면이어야 한다(§4).</p>
 *
 * <p>⚠ <b>MQTT 가 아니라 HTTP 다.</b> 등록 시점에는 붙을 토픽이 없다(`ship_id` 가 없으니까) —
 * 닭과 달걀이라 이 한 건만 HTTP 로 뺐다.</p>
 */

/**
 * Pi 가 답하는 등록 상태 (§4).
 *
 * `NO_KEY` 는 `pi_ship` 은 있는데 `ship_key` 가 없는 상태다 (IoT `web/app.py ship_state`).
 * 등록 응답을 놓쳤다는 뜻이고 **서버는 같은 키를 다시 주지 않는다** — 재등록해야 풀린다.
 * 기다려서 풀리는 `WAIT` 과 반드시 갈라야 한다.
 */
export type ShipState = 'NONE' | 'PENDING' | 'WAIT' | 'ACTIVE' | 'REJECTED' | 'NO_KEY';

export interface ShipStatus {
  state: ShipState;
  ship_id?: string;
  name?: string;
  /** 반려 사유. 있으면 화면에 그대로 보여준다 — 고쳐서 다시 내야 하니까 */
  reason?: string;
}

export interface ShipForm {
  name: string;
  registration_no: string;
  mmsi: string;
  has_buoy: boolean;
}

/**
 * 폴링 주기.
 *
 * 승인은 "몇 분에서 몇 시간"이라 초 단위 긴급도가 아니다(§4). 다만 `PENDING`(Pi 가 들고
 * 서버 등록 대기)은 곧 풀리므로 짧게 본다 — 등록 직후 화면이 멈춘 것처럼 보이지 않게.
 *
 * ⚠ **WAIT 를 15초 → 5초로 줄였다** (2026-09-18). 승인이 화면에 반영되기까지의 지연은
 *   `Pi 신청 픽업 30초`(IoT `enroll.RETRY_SEC`) + `Pi→EC2 승인 확인 60초`(`APPROVAL_POLL_SEC`)
 *   + 이 값이다. 합이 100초를 넘어 시험에서 "몇 분 걸린다"로 나왔다.
 *   지배항은 IoT 쪽 60초라 이것만 줄여서는 안 풀린다 — 우리 몫만 덜어 둔다.
 *   Pi 는 선내 유선이고 응답이 작아서 5초 폴링의 비용이 사실상 없다.
 */
const POLL_MS = { PENDING: 3_000, WAIT: 5_000, other: 30_000 } as const;

/**
 * Pi 가 살아 있나 — `GET /health` (IoT `web/app.py`. `{"ok": true, "ship_id": "…"}`).
 *
 * <p>🔴 <b>"Pi 에 못 붙었다"와 "Pi 는 사는데 등록 상태를 못 읽었다"는 다른 고장이다</b> (2026-09-20).
 * 앞은 전원·랜·주소 문제라 사람이 배선을 봐야 하고, 뒤는 Pi 앱이나 DB 문제라 재등록·재시작
 * 쪽이다. 한 문구로 뭉치면 선원이 엉뚱한 곳을 본다.</p>
 *
 * <p>DB 를 안 건드리는 경로라 `/api/ship` 이 막혀도 이건 답한다 — 그 차이가 곧 진단이다.</p>
 */
async function probePi(): Promise<boolean> {
  try {
    const res = await fetch(piUrl('/health'), { signal: AbortSignal.timeout(3_000) });
    if (!res.ok) return false;
    const body = (await res.json()) as { ok?: boolean };
    return body.ok === true;
  } catch {
    return false;
  }
}

export function useShipRegistration() {
  const [status, setStatus] = useState<ShipStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** 마지막으로 Pi 에 물어본 시각. 화면이 "멈춘 건지 기다리는 건지"를 이걸로 가른다 */
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  /** Pi 자체가 응답하나. `/api/ship` 이 실패했을 때만 따로 확인한다 */
  const [piAlive, setPiAlive] = useState<boolean | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(piUrl('/api/ship'), { signal: AbortSignal.timeout(6000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus((await res.json()) as ShipStatus);
      setError(null);
      setPiAlive(true);          // 답이 왔으니 자명하다. 따로 물어볼 필요가 없다
      setCheckedAt(new Date());
    } catch {
      // 🔴 **실패를 ACTIVE 로 덮지 않는다** (2026-09-18).
      //
      // 전에는 여기서 `VITE_SHIP_ID`(커밋된 .env 값이 'ship-dev')로 ACTIVE 를 지어냈다.
      // 그러면 등록 관문이 통과되고 `ship/ship-dev/**` 를 구독하는데, 브로커는
      // **없는 배를 구독해도 아무 에러를 주지 않는다** — 화면은 멀쩡히 뜨고 사고만 영영 안 온다.
      // 실제로 2026-09-17 시험에서 사고 화면이 안 보인 원인이 이것이었다.
      //
      // 이전 상태는 지우지 않는다. 붙어 있다가 잠깐 끊긴 것과 처음부터 못 붙은 것은 다르다 —
      // 전자는 화면을 유지하고 error 로만 알린다.

      // 어디가 끊겼는지 가른다 — 배선인지 Pi 앱인지가 다음 행동을 바꾼다
      const alive = await probePi();
      setPiAlive(alive);
      setError(alive
        ? 'Pi 는 응답하지만 등록 상태를 읽지 못했습니다'
        : 'Pi 에 연결하지 못했습니다');
      setCheckedAt(new Date());
    }
  }, []);

  useEffect(() => {
    void load();
    const ms = status?.state === 'PENDING' ? POLL_MS.PENDING
      : status?.state === 'WAIT' ? POLL_MS.WAIT : POLL_MS.other;
    const id = setInterval(() => void load(), ms);
    return () => clearInterval(id);
  }, [load, status?.state]);

  /** @return 오류 문구. null 이면 접수됨(202) */
  const register = useCallback(async (form: ShipForm): Promise<string | null> => {
    setBusy(true);
    try {
      const res = await fetch(piUrl('/api/ship'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
        signal: AbortSignal.timeout(10_000),
      });
      // 409 = 이미 등록된 배가 있다. 새로 내는 것이 아니라 그 상태를 보여주면 된다
      if (res.status === 409) { await load(); return '이미 등록된 선박이 있습니다'; }
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { message?: string } | null;
        return body?.message ?? `등록 실패 (HTTP ${res.status})`;
      }
      await load();
      return null;
    } catch {
      return 'Pi 에 연결하지 못했습니다';
    } finally {
      setBusy(false);
    }
  }, [load]);

  return {
    status,
    checkedAt,
    /**
     * Pi 가 응답하나. null 이면 아직 한 번도 확인 못 했다.
     * ⚠ false 는 <b>Pi 자체에 못 붙었다</b>는 뜻이다 — 등록 화면을 띄워 봐야 소용없다
     */
    piAlive,
    /** 등록·승인이 끝나 MQTT 를 열 수 있는 선박. 그 전에는 null */
    shipId: status?.state === 'ACTIVE' ? (status.ship_id ?? null) : null,
    error,
    busy,
    register,
    refresh: load,
  };
}
