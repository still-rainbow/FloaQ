/**
 * 지난 사고 조회 훅. `cloud/useZones.ts` 와 같은 모양이다.
 *
 * ⚠ **실패해도 마지막 값을 지우지 않는다.** 지우면 화면이 빈다 — 선내 무선이
 *   한 번 튀었다고 방금 보던 사고가 사라지면 안 된다 (`cloud/useOcean.ts:145`
 *   가 해양 데이터에 대해 내린 것과 같은 판단).
 *
 * ⚠ 폴링하지 않는다. 지난 사고는 과거라 바뀌지 않고, 새 사고는 MQTT 로 온다.
 *   대신 `reload()` 를 내서 화면이 필요할 때만 다시 받는다.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  fetchAccident, fetchAccidents, fetchBuoyTrack, fetchTimeline,
  PAGE_SIZE,
} from './accidents';
import type {
  AccidentDetail, AccidentRow, AccidentStatus, BuoyPoint, TimelineEntry,
} from './accidents';

/** 궤적을 몇 점마다 받을지. 1Hz 라 5면 5초 간격이 된다. */
const TRACK_EVERY = 5;

export interface HistoryList {
  rows: AccidentRow[];
  total: number;
  loading: boolean;
  /** 사람이 읽는 실패 문구. 없으면 null. */
  error: string | null;
  hasMore: boolean;
  loadMore: () => void;
  reload: () => void;
}

const message = (e: unknown): string => {
  const m = e instanceof Error ? e.message : '';
  if (m.includes('aborted') || m === '') return 'Pi 응답 없음';
  if (m.startsWith('HTTP 5')) return `Pi 오류 (${m})`;
  return m;
};

export function useAccidentList(status: AccidentStatus | null): HistoryList {
  const [rows, setRows] = useState<AccidentRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [nonce, setNonce] = useState(0);

  // 필터가 바뀌면 처음부터 다시 받는다
  useEffect(() => { setOffset(0); }, [status]);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    fetchAccidents({ limit: PAGE_SIZE, offset, status }, ctrl.signal)
      .then((page) => {
        setTotal(page.total);
        // offset 0 이면 갈아끼우고, 더 받기면 이어 붙인다
        setRows((prev) => (offset === 0 ? page.rows : [...prev, ...page.rows]));
        setError(null);
      })
      .catch((e) => { if (!ctrl.signal.aborted) setError(message(e)); })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [offset, status, nonce]);

  const loadMore = useCallback(() => {
    setOffset((o) => o + PAGE_SIZE);
  }, []);
  const reload = useCallback(() => {
    setOffset(0);
    setNonce((n) => n + 1);
  }, []);

  return {
    rows, total, loading, error,
    hasMore: rows.length < total,
    loadMore, reload,
  };
}

export interface HistoryDetail {
  detail: AccidentDetail | null;
  timeline: TimelineEntry[];
  track: BuoyPoint[];
  loading: boolean;
  error: string | null;
}

/**
 * 사고 하나. 상세·타임라인·궤적을 **한꺼번에** 받는다.
 *
 * ⚠ 셋을 따로 기다리면 화면이 세 번 덜컥인다. 병렬로 보내되 하나로 모은다.
 *
 * ⚠ 궤적은 없을 수 있다 (투하 실패, 부표 두절). 그때도 상세는 보여야 하므로
 *   궤적 실패가 전체를 실패로 만들지 않는다.
 */
export function useAccidentDetail(id: string | null): HistoryDetail {
  const [detail, setDetail] = useState<AccidentDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [track, setTrack] = useState<BuoyPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shown = useRef<string | null>(null);

  useEffect(() => {
    if (!id) { setDetail(null); setTimeline([]); setTrack([]); setError(null); return; }
    const ctrl = new AbortController();
    setLoading(true);
    // 다른 사고로 넘어가면 앞 사고의 궤적이 잠깐 겹쳐 보인다. 먼저 비운다
    if (shown.current !== id) { setTimeline([]); setTrack([]); }
    shown.current = id;

    Promise.all([
      fetchAccident(id, ctrl.signal),
      fetchTimeline(id, ctrl.signal).catch(() => [] as TimelineEntry[]),
      fetchBuoyTrack(id, TRACK_EVERY, ctrl.signal).catch(() => [] as BuoyPoint[]),
    ])
      .then(([d, t, b]) => {
        if (ctrl.signal.aborted) return;
        setDetail(d); setTimeline(t); setTrack(b); setError(null);
      })
      .catch((e) => { if (!ctrl.signal.aborted) setError(message(e)); })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [id]);

  return { detail, timeline, track, loading, error };
}
