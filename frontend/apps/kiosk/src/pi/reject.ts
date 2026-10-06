/**
 * 명령 거절·실패 사유 → 화면 문구. 본 화면·경보·해양 화면이 같은 문구를 쓴다.
 *
 * Pi 의 error.message 는 영어 로그용이라 띄우지 않는다 — code 로 문구를 고른다 (IoT contracts/envelope.py)
 */
const REJECT_TEXT: Record<string, string> = {
  ALREADY_REPORTED: '이미 신고됐습니다',
  ALREADY_RESOLVED: '이미 종결된 사고입니다',
  ALREADY_CANCELLED: '이미 취소된 사고입니다',
  NO_ACTIVE_INCIDENT: '진행 중인 사고가 없습니다',
  INVALID_STATE: '지금은 할 수 없습니다',
  ACCIDENT_IN_PROGRESS: '진행 중인 사고가 있습니다',
  ACCIDENT_NOT_FOUND: '사고를 찾을 수 없습니다',
  DEVICE_ERROR: 'Pi 장치 오류',
  NOT_FOUND: '사고를 찾을 수 없습니다',
  BAD_REQUEST: '명령 형식 오류 — 단말 버전 확인',
  REJECTED: 'Pi 가 거부했습니다',
  // 아래 둘은 Pi 의 답이 아니라 통신 실패다. "거부당한 것"과 "닿지 않은 것"을 문구로 가른다
  TIMEOUT: 'Pi 응답 없음 — 처리됐는지 모릅니다',
  OFFLINE: 'Pi 연결 끊김 — 명령이 나가지 않았습니다',
};

export const rejectText = (reason?: string | null): string =>
  REJECT_TEXT[reason ?? ''] ?? reason ?? '사유 없음';
