/**
 * MQTT 공통 Envelope — `ref/mqtt.md` §3.
 *
 * 모든 페이로드를 감싸고 실제 내용은 `data` 배열에 넣는다. 단건도 길이 1이다.
 * 배열로 고정해 두면 부표 위치를 "1초 단건"에서 "10초 10건 묶음"으로 바꿀 때
 * 인터페이스가 바뀌지 않는다 (§3.2 — 그 결정이 아직 미정이다).
 *
 * ⚠ 필드명은 전부 snake_case 다 (§3.5 확정). MQTT 필드명과 DB 컬럼명이 같아서
 *    변환 계층 자체가 없다 — 여기서 camelCase 로 바꾸면 그 이점이 사라진다.
 *    앱 타입(messages.ts)으로의 변환은 decode 한 곳에서만 한다.
 */

/** 단방향 — 텔레메트리·이벤트. 응답이 없다 */
export interface Envelope<T> {
  /** UUID v7. 중복 제거 + 응답 상관관계 (§3.3) */
  request_id: string;
  /** 페이로드 스키마 버전 */
  v: number;
  /** Unix 초. **발행** 시각 — data 원소의 measured_at 과 다르다 (§3.4) */
  ts: number;
  data: T[];
}

export interface ErrorInfo {
  code: string;
  message: string;
}

/**
 * 요청-응답 — `pi/command/response` 전용.
 *
 * ⚠ **data 가 배열이 아니라 단건이다** (IoT contracts/envelope.py `CommandAck`). Envelope 를 상속하지 않는 이유
 */
export interface ResponseEnvelope<T> {
  /** 요청의 request_id 를 그대로 반사 */
  request_id: string;
  v: number;
  ts: number;
  is_success: boolean;
  data: T;
  error: ErrorInfo | null;
}

/**
 * UUID v7. 앞 48비트가 Unix ms 라 시간순으로 정렬된다.
 *
 * v4(`crypto.randomUUID()`)를 쓰지 않는 이유는 규격이 v7 이기 때문이다 —
 * Pi 가 `request_id` 로 정렬하거나 시각을 뽑아 쓸 여지를 남긴다.
 */
export function newRequestId(): string {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  const ms = Date.now();
  b[0] = (ms / 2 ** 40) & 0xff;
  b[1] = (ms / 2 ** 32) & 0xff;
  b[2] = (ms / 2 ** 24) & 0xff;
  b[3] = (ms / 2 ** 16) & 0xff;
  b[4] = (ms / 2 ** 8) & 0xff;
  b[5] = ms & 0xff;
  // noUncheckedIndexedAccess 가 켜져 있어 인덱스 읽기가 undefined 가능이다.
  // 길이 16 은 위에서 보장되므로 지역 변수로 한 번만 좁힌다
  b[6] = 0x70 | ((b[6] ?? 0) & 0x0f); // version 7
  b[8] = 0x80 | ((b[8] ?? 0) & 0x3f); // variant 10
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/**
 * QoS 1 중복 제거 (§3.3).
 *
 * QoS 1 은 at-least-once 라 같은 메시지가 두 번 온다. 텔레메트리가 두 번 와도
 * 화면은 같은 값을 두 번 그릴 뿐이지만, **상태 전이 메시지가 두 번 처리되면**
 * 로그가 어긋나고 사고 경위 설명이 틀어진다.
 *
 * 최근 N개만 기억한다. 무한히 모으면 장시간 켜 둔 단말의 메모리를 먹는다.
 */
export function makeDedupe(size = 100): (requestId: string) => boolean {
  const seen = new Set<string>();
  const order: string[] = [];
  return (id) => {
    if (seen.has(id)) return false; // 이미 본 것
    seen.add(id);
    order.push(id);
    if (order.length > size) {
      const gone = order.shift();
      if (gone !== undefined) seen.delete(gone);
    }
    return true;
  };
}

/** 파싱 실패를 예외로 올리지 않는다 — 깨진 메시지 하나로 연결을 끊지 않는다 */
export function parseEnvelope<T>(raw: string): Envelope<T> | null {
  try {
    const e = JSON.parse(raw) as Envelope<T>;
    if (typeof e?.request_id !== 'string' || !Array.isArray(e?.data)) return null;
    // 모르는 스키마 버전은 버린다 — 필드 뜻이 달라졌을 수 있다 (IoT contracts/envelope.py `v: Literal[1]`)
    if (e.v !== 1) return null;
    return e;
  } catch {
    return null;
  }
}
