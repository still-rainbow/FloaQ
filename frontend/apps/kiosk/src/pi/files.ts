import { piUrl } from '@floaq/shared/origins';

/**
 * Pi 사고 파일 API (IoT `web/app.py` `list_files` · `get_file`).
 *
 * <p>🔴 <b>키오스크는 R2 를 보지 않는다.</b> 선내 화면이 인터넷에 의존하면 사고 상황에서
 * 가장 먼저 끊긴다. Pi 의 `pi_accident_file` 에 `file_path`(로컬)와 `object_key`(R2)가
 * 따로 있는 이유가 그것이다 — 우리는 앞쪽만 쓴다 (IoT `architecture.md` §4).</p>
 *
 * <h2>사진이 어디서 오는가</h2>
 * <pre>
 *   Jetson ──PUT /api/detections/{detection_id}/files/{type}/{seq}──▶ Pi 디스크
 *                                                                      │
 *                                          GET /api/accidents/{id}/files│  (여기)
 *                                          GET /files/{id}/{type}/{n}   ▼
 *                                                                   [키오스크]
 * </pre>
 *
 * <p>⚠ <b>`jetson/snapshot`(MQTT base64)을 기다리지 않는다.</b> 그 토픽은 계약에만 있고
 * 발행하는 코드가 없다(dev-iot 5cc70fd 확인). 그런데 <b>같은 사진이 Pi 디스크에는 있다</b> —
 * Jetson `_upload.py` 가 `DETECT_SNAPSHOT` 1장 + `BEFORE` + `AFTER` 를 올린다.</p>
 */

/** `pi_accident_file.file_type` CHECK 와 같은 값 */
export type PiFileType = 'DETECT_SNAPSHOT' | 'BEFORE' | 'AFTER';

export interface PiFile {
  fileId: number;
  fileType: PiFileType;
  /**
   * 프레임 순번.
   *
   * ⚠ `DETECT_SNAPSHOT` 도 `null` 이 아니라 <b>0</b> 이다. Jetson 이 `None` 을 보내고 싶어도
   * Pi 의 경로 파라미터가 `int` 필수라 `_upload.py` 가 0 으로 바꿔 보낸다 —
   * 그래서 실제 파일명이 `snapshot.jpg` 가 아니라 `0000.jpg` 다.
   */
  sequenceNo: number | null;
  camera: 'L' | 'R' | null;
  bytes: number;
  /**
   * Pi 기준 절대 경로 (`/files/{accident_id}/{file_type}/0000.jpg`).
   *
   * 🔴 <b>이름을 직접 만들지 말고 이 값을 쓴다.</b> 순번 자릿수(PUT 응답은 4자리, 타르볼은
   * 5자리)와 확장자가 경로마다 다르고, Pi 만 DB 를 보고 정확히 안다.
   */
  url: string;
  /**
   * R2 에 올라갔나.
   *
   * ⚠ <b>화면에서 이걸로 거르지 않는다.</b> 로컬 존재 여부가 아니라 업로드 여부다 —
   * 인터넷이 없으면 전부 false 이고, 그래도 사진은 Pi 에 있다.
   */
  uploaded: boolean;
}

interface RawFile {
  file_id: number;
  file_type: string;
  sequence_no: number | null;
  camera: string | null;
  bytes: number;
  url: string;
  uploaded: boolean;
}

const TYPES: readonly string[] = ['DETECT_SNAPSHOT', 'BEFORE', 'AFTER'];

/** 사고 직후에는 Pi 가 아직 받는 중이라 목록이 짧다. 넉넉히 주되 화면을 세우지는 않는다 */
const TIMEOUT_MS = 6_000;

/**
 * 사고 하나의 파일 목록. `sequence_no` 순으로 온다.
 *
 * @param fileType 주면 그 종류만. 스냅샷 한 장만 필요할 때 125장을 받지 않는다
 * @throws fetch 실패·비 2xx. 호출부가 "Pi 에 못 붙었다"로 처리한다
 */
export async function listAccidentFiles(
  accidentId: string, fileType?: PiFileType, signal?: AbortSignal,
): Promise<PiFile[]> {
  const q = fileType ? `?file_type=${fileType}` : '';
  // 상한을 호출부 신호로 대체하지 않는다 — 둘 다 걸어야 한다.
  // Pi 가 응답을 안 주면(디스크 지연 등) 폴링이 그 한 번에 멈춰 선다
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  signal?.addEventListener('abort', () => ctrl.abort());
  let res: Response;
  try {
    res = await fetch(piUrl(`/api/accidents/${accidentId}/files${q}`), { signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = (await res.json()) as { files?: RawFile[] };
  return (body.files ?? [])
    // 모르는 file_type 은 버린다. Pi 가 종류를 늘려도 화면이 깨지지 않는다
    .filter((f) => TYPES.includes(f.file_type))
    .map((f) => ({
      fileId: f.file_id,
      fileType: f.file_type as PiFileType,
      sequenceNo: f.sequence_no,
      camera: f.camera === 'L' || f.camera === 'R' ? f.camera : null,
      bytes: f.bytes,
      url: f.url,
      uploaded: f.uploaded,
    }));
}

/**
 * `<img src>` 에 넣을 주소.
 *
 * dev 는 vite 프록시(`/pi`)를 거쳐야 하고 빌드판은 상대 경로 그대로다 —
 * 페이지를 Pi 가 내려주므로 같은 오리진이다 (`packages/shared/origins.ts`).
 */
export const fileSrc = (f: PiFile): string => piUrl(f.url);

/** 좌현·우현. 없으면 빈 문자열 — "모름"을 지어내지 않는다 */
export const cameraLabel = (c: 'L' | 'R' | null): string =>
  c === 'L' ? '좌현' : c === 'R' ? '우현' : '';
