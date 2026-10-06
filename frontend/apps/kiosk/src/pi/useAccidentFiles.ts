import { useEffect, useState } from 'react';
import { listAccidentFiles, type PiFile, type PiFileType } from './files';

/**
 * 사고 파일 목록을 채워질 때까지 따라간다.
 *
 * <p>⚠ <b>한 번 부르고 끝내면 안 된다.</b> 탐지 순간에는 목록이 비어 있거나 짧다 —
 * `BEFORE` 75장은 링 버퍼에서 한꺼번에 쏟아지지만 `AFTER` 50장은 <b>10초에 걸쳐</b>
 * 들어오고(IoT `config.py` `FRAME_POST_SEC = 10`), 업로드 큐가 밀리면 더 늦는다.</p>
 *
 * <p>그래서 <b>수가 안 늘 때까지</b> 짧게 다시 묻는다. 시간으로 끊지 않는 이유는
 * 업로드가 얼마나 밀리는지 우리가 모르기 때문이다 — 큐 길이는 Jetson 쪽 사정이다.</p>
 */

/** 다시 묻는 간격. 업로드가 5fps 로 들어오므로 이보다 촘촘하게 물어도 같은 답이다 */
const POLL_MS = 2_000;

/** 수가 이만큼 연속으로 같으면 다 받은 것으로 본다 (약 6초) */
const STABLE_ROUNDS = 3;

/** 연속 실패 상한. Pi 가 없는 자리에서 영원히 두드리지 않는다 */
const MAX_FAILS = 3;

export interface AccidentFiles {
  files: PiFile[];
  /** 마지막 시도가 실패한 이유. 목록이 비어 있는 것과 <b>못 물어본 것</b>은 다르다 */
  error: string | null;
  /** 더 안 늘어난다고 판단했나. 화면이 "받는 중"을 언제 거둘지 결정한다 */
  settled: boolean;
}

interface Options {
  /**
   * 꺼져 있으면 아무것도 하지 않는다.
   * 🔴 <b>가상 모드에서는 반드시 false.</b> 그쪽엔 Pi 가 없어 전부 실패로 쌓인다
   */
  enabled: boolean;
  /** 주면 그 종류만 받는다. 스냅샷 한 장이 필요할 때 125장을 받지 않는다 */
  fileType?: PiFileType;
}

export function useAccidentFiles(
  accidentId: string | null, { enabled, fileType }: Options,
): AccidentFiles {
  const [state, setState] = useState<AccidentFiles>(
    { files: [], error: null, settled: false });

  useEffect(() => {
    // 사고가 바뀌면 이전 사고의 사진을 그대로 두지 않는다 —
    // 새 경보에 옛 사진이 한 프레임 비치면 그게 판단 근거가 된다
    setState({ files: [], error: null, settled: false });
    if (!enabled || !accidentId) return;

    let alive = true;
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setInterval> | null = null;
    const stop = () => { if (timer) { clearInterval(timer); timer = null; } };
    let same = 0;
    let fails = 0;
    let last = -1;

    const round = async () => {
      try {
        const files = await listAccidentFiles(accidentId, fileType, ctrl.signal);
        if (!alive) return;
        fails = 0;
        same = files.length === last ? same + 1 : 0;
        last = files.length;
        const settled = same >= STABLE_ROUNDS;
        setState({ files, error: null, settled });
        if (settled) stop();
      } catch (e: unknown) {
        if (!alive) return;
        // ⚠ 실패해도 이미 받은 목록은 지우지 않는다. 사진이 화면에서 사라지는 것이
        //   "못 물어봤다"보다 나쁘다
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
        if (++fails >= MAX_FAILS) stop();
      }
    };

    timer = setInterval(() => void round(), POLL_MS);
    void round();

    return () => { alive = false; ctrl.abort(); stop(); };
  }, [accidentId, enabled, fileType]);

  return state;
}
