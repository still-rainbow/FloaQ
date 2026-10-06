import { useEffect, useMemo, useState } from 'react';
import { cameraLabel, fileSrc, type PiFile, type PiFileType } from '../pi/files';
import { useAccidentFiles } from '../pi/useAccidentFiles';

/**
 * 사고 전후 프레임 (`ref/mqtt-연동-웹.md` §11).
 *
 * <p>앞 15초 · 뒤 10초를 Pi 가 들고 있다(IoT `config.py` `FRAME_PRE_SEC`·`FRAME_POST_SEC`).
 * <b>사고가 난 뒤에는 그 전 장면을 다시 만들 수 없다</b> — 앞 구간은 Jetson 이 링 버퍼로
 * 상시 들고 있다가 탐지 순간에 쏟아낸 것이다.</p>
 *
 * <p>🔴 <b>Pi 로컬 HTTP 에서 받는다. R2 가 아니다.</b> 선내 화면이 인터넷에 기대면
 * 사고 상황에서 가장 먼저 끊긴다 (IoT `architecture.md` §4).</p>
 */

/**
 * 시간순 정렬 키.
 *
 * 🔴 <b>Pi 가 주는 순서를 그대로 쓰면 안 된다.</b> `ORDER BY file_type, sequence_no` 라
 * 글자순으로 <b>AFTER → BEFORE → DETECT_SNAPSHOT</b> 이 온다 — 사고 후가 맨 앞이다.
 */
const ORDER: Record<PiFileType, number> = { BEFORE: 0, DETECT_SNAPSHOT: 1, AFTER: 2 };

const SECTION: Record<PiFileType, string> = {
  BEFORE: '사고 전', DETECT_SNAPSHOT: '감지 순간', AFTER: '사고 후',
};

/**
 * 재생 간격.
 *
 * ⚠ <b>실제 시간축이 아니라 보기 속도다.</b> IoT 의 `FRAME_FPS = 5` 는 두 카메라를 합친
 * 초당 장수라, 카메라 하나만 고르면 실제 간격이 두 배다. 몇 장이 어느 카메라에서
 * 왔는지는 Jetson 이 그때 무엇을 먹였는지에 달려 있어 우리가 계산할 수 없다 —
 * 그래서 화면에 <b>경과 초를 적지 않는다.</b> 순번만 적는다.
 */
const PLAY_MS = 200;

interface Props {
  /** 볼 사고. null 이면 볼 것이 없다 */
  incidentId: string | null;
  /** 가상 모드. 🔴 Pi 가 없는 모드라 조회를 끈다 */
  virtual: boolean;
  /**
   * 처음 설 자리.
   *
   * `detect`(기본) — 지금 벌어지는 사고다. 사람이 제일 먼저 볼 장면은 감지 순간이다.
   * `begin`  — 지난 사고를 다시 보는 중이다. **앞 15초부터 봐야 무슨 일이 있었는지 안다.**
   *
   * 🔴 지난 사고에서 `detect` 로 두면 사고 후 프레임이 없는 경우 곧바로 **맨 끝**에
   *    서게 되고, 재생을 눌러도 아무 일도 일어나지 않는다 (2026-09-21 화면에서 확인).
   */
  start?: 'detect' | 'begin';
  /** 열자마자 재생. 지난 사고처럼 "보러 온" 화면에서만 켠다 */
  autoPlay?: boolean;
}

export function FramesPane({ incidentId, virtual, start = 'detect', autoPlay = false }: Props) {
  const { files, error, settled } = useAccidentFiles(incidentId, { enabled: !virtual });
  const [cam, setCam] = useState<'L' | 'R' | null>(null);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  /**
   * 사람이 위치를 건드렸나.
   *
   * 🔴 <b>"처음 한 번만 자리를 잡는다"를 플래그로 만들지 않는다.</b> 목록이 폴링으로
   * 계속 자라서, 한 번 잡고 마는 방식이면 그 순간에 몇 장 와 있었는지에 따라
   * 엉뚱한 자리에 선다. 안 건드린 동안은 <b>매번 감지 순간으로 다시 맞춘다.</b>
   */
  const [touched, setTouched] = useState(false);
  /**
   * 자동 재생을 이미 한 번 걸었나.
   *
   * ⚠ 목록이 폴링으로 자라므로 장수를 의존성에 넣으면 사람이 멈춰도 다음 폴링에서
   *   다시 돌아간다. 사고당 한 번으로 못 박는다.
   */
  const [autoDone, setAutoDone] = useState(false);

  // 사고가 바뀌면 렌더 중에 되돌린다 — effect 로 미루면 새 사고 화면에 옛 사고의
  // 프레임 번호가 한 번 비친다
  const [prevInc, setPrevInc] = useState(incidentId);
  if (prevInc !== incidentId) {
    setPrevInc(incidentId);
    setI(0); setTouched(false); setPlaying(false); setCam(null); setAutoDone(false);
  }

  /**
   * 사진이 들어오면 한 번 재생을 건다. 보러 온 화면(지난 사고)에서만 켠다.
   *
   * 🔴 `touched` 를 같이 켜야 한다. 안 켜면 화면이 `home` 에 고정돼서, 재생이
   *    도는데도 **사진이 안 넘어간다** — 타이머는 `i` 를 올리지만 `at` 이 `i` 를
   *    안 보기 때문이다.
   * ⚠ `start="begin"` 과 같이 쓴다. 그때 `home` 이 0 이라 `i` 의 초깃값과 같다.
   */
  useEffect(() => {
    if (!autoPlay || autoDone || files.length === 0 || start !== 'begin') return;
    setAutoDone(true);
    setI(0);
    setTouched(true);
    setPlaying(true);
  }, [autoPlay, autoDone, files.length, start]);

  const sorted = useMemo(
    () => [...files].sort((a, b) =>
      ORDER[a.fileType] - ORDER[b.fileType] || (a.sequenceNo ?? 0) - (b.sequenceNo ?? 0)),
    [files]);

  /** 실제로 들어온 카메라. 한 대만 쓰면 토글을 띄우지 않는다 */
  const cams = useMemo(() => {
    const set = new Set<'L' | 'R'>();
    for (const f of sorted) if (f.camera) set.add(f.camera);
    return [...set].sort();
  }, [sorted]);

  // 카메라를 안 고르면 좌우가 번갈아 나와 재생이 눈에 튄다 — 한 대로 고정한다.
  // 기본값은 **탐지한 카메라**다. 사람이 찍힌 쪽이 그쪽이다
  useEffect(() => {
    if (cam || cams.length === 0) return;
    const shot = sorted.find((f) => f.fileType === 'DETECT_SNAPSHOT');
    setCam(shot?.camera ?? cams[0] ?? null);
  }, [cam, cams, sorted]);

  const shown = useMemo(
    // camera 가 비어 있는 행(X-Camera 를 안 실은 업로드)은 어느 쪽을 골라도 남긴다
    () => (cam ? sorted.filter((f) => f.camera === cam || f.camera === null) : sorted),
    [sorted, cam]);

  useEffect(() => {
    if (!playing || shown.length === 0) return;
    const id = setInterval(() => {
      setI((n) => {
        // 끝에서 멈춘다. 돌아가면 "방금 그 장면"을 다시 찾아야 한다
        if (n + 1 >= shown.length) { setPlaying(false); return n; }
        return n + 1;
      });
    }, PLAY_MS);
    return () => clearInterval(id);
  }, [playing, shown.length]);

  if (!incidentId) {
    return <div className="frames-pane frames-empty">진행 중인 사고가 없습니다</div>;
  }
  if (virtual) {
    // 🔴 "없다"고 말하지 않는다. 가상 모드에는 Pi 가 없을 뿐 사진이 없는 것이 아니다
    return <div className="frames-pane frames-empty">가상 모드에서는 사고 사진을 받지 않습니다</div>;
  }
  if (shown.length === 0) {
    return (
      <div className="frames-pane frames-empty">
        {error ? `사진 목록을 받지 못했습니다 — ${error}` : settled ? '사고 사진이 없습니다' : '사고 사진을 받는 중입니다…'}
      </div>
    );
  }

  // 안 건드린 동안은 정해진 자리에 선다 — 목록이 폴링으로 자라도 매번 다시 맞춘다
  const detectAt = shown.findIndex((f) => f.fileType !== 'BEFORE');
  const home = start === 'begin' ? 0 : (detectAt < 0 ? shown.length - 1 : detectAt);
  const at = touched ? Math.min(i, shown.length - 1) : home;
  const cur = shown[at] as PiFile;
  /** 위치를 사람 손에 넘긴다. 지금 보던 자리에서 이어져야 한다 */
  const take = (next: number) => { setTouched(true); setI(next); };
  const before = shown.filter((f) => f.fileType === 'BEFORE').length;
  const after = shown.filter((f) => f.fileType === 'AFTER').length;

  return (
    <div className="frames-pane">
      <div className="frames-bar">
        <span className="frames-counts mono">
          사고 전 {before}장 · 사고 후 {after}장
          {/* 아직 들어오는 중이면 그렇다고 말한다. 안 그러면 "이게 전부"로 읽는다 */}
          {!settled && <b className="frames-live"> · 받는 중</b>}
        </span>
        {cams.length > 1 && (
          <span className="frames-cams">
            {cams.map((c) => (
              <button key={c} className="btn btn-ghost" aria-pressed={cam === c}
                onClick={() => { setCam(c); setPlaying(false); setTouched(false); }}>
                {cameraLabel(c)}
              </button>
            ))}
          </span>
        )}
      </div>

      <figure className="frames-stage">
        {/* 🔴 파일명을 만들지 않고 목록이 준 url 을 쓴다 — 순번 자릿수를 Pi 만 정확히 안다 */}
        <img src={fileSrc(cur)} alt={`${SECTION[cur.fileType]} ${cur.sequenceNo ?? 0}번 프레임`} />
        <figcaption className="mono">
          <b className={cur.fileType === 'DETECT_SNAPSHOT' ? 'is-detect' : undefined}>
            {SECTION[cur.fileType]}
          </b>
          {` · ${at + 1}/${shown.length}`}
          {cameraLabel(cur.camera) && ` · ${cameraLabel(cur.camera)}`}
        </figcaption>
      </figure>

      <div className="frames-controls">
        <button className="btn" onClick={() => { setPlaying(false); take(Math.max(0, at - 1)); }}
          disabled={at === 0} aria-label="이전 프레임">◀</button>
        <button className="btn btn-play"
          onClick={() => { take(at); setPlaying((p) => !p); }}>
          {playing ? '멈춤' : '재생'}
        </button>
        <button className="btn"
          onClick={() => { setPlaying(false); take(Math.min(shown.length - 1, at + 1)); }}
          disabled={at >= shown.length - 1} aria-label="다음 프레임">▶</button>
        {/* 장갑 낀 손으로도 잡히도록 트랙을 크게 — CSS 에서 높이를 키운다 */}
        <input className="frames-scrub" type="range" min={0} max={shown.length - 1} value={at}
          onChange={(e) => { setPlaying(false); take(Number(e.target.value)); }}
          aria-label="프레임 위치" />
      </div>

      {/* 목록을 못 받아도 이미 받은 사진은 그대로 둔다. 이유만 아래에 적는다 */}
      {error && <p className="frames-note" role="alert">목록 갱신 실패 — {error}</p>}
    </div>
  );
}
