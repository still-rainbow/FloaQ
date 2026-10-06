import type { SnapshotMsg } from '@floaq/shared';
import { cameraLabel, fileSrc, type PiFile } from '../pi/files';

/**
 * 감지 스틸컷 — 경보 화면의 판단 근거 (기획서 §11 우선순위 3위).
 *
 * <p><b>없으면 대기·취소 판단이 불가능하다.</b> 선원이 "오탐인가 진짜인가"를 가르는 유일한 근거고,
 * 그 판단으로 신고 취소 버튼을 누른다.</p>
 *
 * <h2>출처가 둘이다 (2026-09-20)</h2>
 * <table>
 *   <tr><td>`shot`</td><td>`jetson/snapshot` MQTT base64 + bbox</td><td>⚠ <b>발행하는 코드가 없다</b></td></tr>
 *   <tr><td>`file`</td><td>Pi 의 `DETECT_SNAPSHOT` 파일</td><td>실제로 오는 쪽</td></tr>
 * </table>
 *
 * <p>🔴 <b>MQTT 쪽을 지우지 않는다.</b> 계약에 살아 있고(`contracts/jetson.py` `AccidentSnapshot`)
 * 가상 모드 fixture 가 그 경로로 그린다. 발행이 붙는 날 bbox 까지 같이 돌아온다 —
 * 그래서 있으면 그쪽을 먼저 쓴다.</p>
 *
 * <p>⚠ <b>Pi 파일에는 bbox 가 없다.</b> 박스는 `jetson/detection` 이 들고 있는데 그건 retained 가
 * 아니라 새로고침하면 사라진다. 사진만 그리고 박스는 비운다 — <b>지어내지 않는다.</b></p>
 *
 * <p>bbox 를 <b>비율</b>로 그린다 — 이미지가 화면 크기에 맞춰 줄어드는데 px 로 그리면 박스만 제자리에 남는다.</p>
 */
interface Props {
  /** MQTT 스냅샷. 있으면 이쪽이 이긴다 — bbox·확신도가 같이 온다 */
  shot: SnapshotMsg | null;
  /** Pi 가 들고 있는 `DETECT_SNAPSHOT`. `shot` 이 없을 때 쓴다 */
  file?: PiFile | null;
  /** Pi 에 아직 안 올라왔나. "없다"와 "받는 중"을 사람이 구분해야 한다 */
  pending?: boolean;
}

export function SnapshotView({ shot, file, pending }: Props) {
  if (!shot && file) {
    return (
      <figure className="snap">
        <div className="snap-frame">
          {/* 🔴 파일명을 만들지 않고 목록이 준 url 을 쓴다 — 순번 자릿수를 Pi 만 정확히 안다 */}
          <img src={fileSrc(file)} alt="감지 순간" />
        </div>
        <figcaption className="mono">
          {cameraLabel(file.camera) && `${cameraLabel(file.camera)} · `}
          {/* 확신도는 MQTT 스냅샷에만 있다. 없는 값을 0% 로 그리지 않는다 */}
          Pi 저장본
        </figcaption>
      </figure>
    );
  }

  if (!shot) {
    // 🔴 자리를 비워 두지 않는다. 없는 것과 "아직 안 온 것"을 사람이 구분해야 한다
    return <div className="snap snap-empty">{pending ? '감지 사진 받는 중…' : '감지 사진 없음'}</div>;
  }

  const { bbox, width, height } = shot;
  // 원본 해상도를 모르면 박스를 그릴 기준이 없다 — 사진만 보여준다
  const box = bbox && width && height ? {
    left: `${(bbox[0] / width) * 100}%`,
    top: `${(bbox[1] / height) * 100}%`,
    width: `${(bbox[2] / width) * 100}%`,
    height: `${(bbox[3] / height) * 100}%`,
  } : null;

  return (
    <figure className="snap">
      <div className="snap-frame">
        <img src={`data:image/${shot.format};base64,${shot.data}`} alt="감지 순간" />
        {box && <span className="snap-box" style={box} aria-hidden="true" />}
      </div>
      <figcaption className="mono">
        {shot.camera && `${shot.camera === 'L' ? '좌현' : '우현'} · `}
        {/* 확신도를 적는다 — 낮으면 사람이 더 봐야 한다는 신호다 */}
        {shot.confidence != null && `확신도 ${Math.round(shot.confidence * 100)}%`}
      </figcaption>
    </figure>
  );
}
