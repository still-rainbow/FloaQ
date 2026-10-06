/** 아이콘. 라이브러리를 넣지 않는다 — 쓰는 게 열몇 개이고 전부 24px 스트로크다 */
type P = { size?: number; className?: string };

const S = ({ size = 16, className = '', d, extra }:
  P & { d: string; extra?: React.ReactNode }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className}
    aria-hidden="true">
    <path d={d} />{extra}
  </svg>
);

export const IcoWifi = (p: P) => (
  <svg width={p.size ?? 14} height={p.size ?? 14} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" className={p.className} aria-hidden="true">
    <path d="M4 8.5a13 13 0 0 1 16 0M7 12a9 9 0 0 1 10 0M10 15.4a5 5 0 0 1 4 0" />
    <circle cx="12" cy="19" r=".9" fill="currentColor" />
  </svg>
);

export const IcoWifiOff = (p: P) => (
  <svg width={p.size ?? 14} height={p.size ?? 14} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" className={p.className} aria-hidden="true">
    <path d="m2 2 20 20M8.8 12.6a5 5 0 0 1 6.4 0M5.5 9.1a10 10 0 0 1 3-1.8M19 9.4a10 10 0 0 0-4.6-2.2" />
    <circle cx="12" cy="17.5" r=".8" fill="currentColor" />
  </svg>
);

export const IcoMoon = (p: P) => <S {...p} d="M20.5 14.2A8.6 8.6 0 0 1 9.8 3.5a8.6 8.6 0 1 0 10.7 10.7Z" />;
export const IcoSun = (p: P) => (
  <S {...p} d="M12 2.4v2.2M12 19.4v2.2M2.4 12h2.2M19.4 12h2.2M5.2 5.2l1.6 1.6M17.2 17.2l1.6 1.6M18.8 5.2l-1.6 1.6M6.8 17.2l-1.6 1.6"
    extra={<circle cx="12" cy="12" r="4" />} />
);
export const IcoGear = (p: P) => (
  <S {...p} d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-3-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-3l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 2.9-1.2V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 3 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"
    extra={<circle cx="12" cy="12" r="3" />} />
);
export const IcoClose = (p: P) => <S {...p} d="M6 6l12 12M18 6 6 18" />;
export const IcoCheck = (p: P) => <S {...p} d="M20 6 9 17l-5-5" />;
export const IcoWarn = (p: P) => <S {...p} d="M12 3 1.8 20.5h20.4ZM12 9.5v5M12 17.6v.1" />;
export const IcoClock = (p: P) => <S {...p} d="M12 7.5v5l3 2" extra={<circle cx="12" cy="12" r="9" />} />;
export const IcoTarget = (p: P) => (
  <S {...p} d="M12 2.6v3M12 18.4v3M2.6 12h3M18.4 12h3" extra={<circle cx="12" cy="12" r="3.2" />} />
);
export const IcoSpark = (p: P) => (
  <S {...p} d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6 7.7 7.7M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"
    extra={<circle cx="12" cy="12" r="3.2" />} />
);

/* 장비 아이콘 */
export const IcoCamera = (p: P) => (
  <S {...p} d="M3 8.5A1.5 1.5 0 0 1 4.5 7h3l1.5-2h6l1.5 2h3A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5Z"
    extra={<circle cx="12" cy="12.8" r="3.4" />} />
);
export const IcoChip = (p: P) => (
  <S {...p} d="M9 1.8v2.2M15 1.8v2.2M9 20v2.2M15 20v2.2M1.8 9H4M1.8 15H4M20 9h2.2M20 15h2.2"
    extra={<><rect x="4" y="4" width="16" height="16" rx="3" /><rect x="9" y="9" width="6" height="6" rx="1" /></>} />
);
export const IcoWaves = (p: P) => (
  <S {...p} d="M3 13.5c2.6 0 2.6-3 5.2-3s2.6 3 5.2 3 2.6-3 5.2-3 2.4 3 2.4 3M3 18.4c2.6 0 2.6-3 5.2-3s2.6 3 5.2 3 2.6-3 5.2-3 2.4 3 2.4 3"
    extra={<circle cx="12" cy="5.6" r="2.4" />} />
);
export const IcoBuoy = (p: P) => (
  <S {...p} d="M6.6 9.6 12 13l5.4-3.4M12 3.2V7" extra={<circle cx="12" cy="13" r="6" />} />
);

/* 카테고리 탭 */
export const IcoShield = (p: P) => <S {...p} d="M12 3 4.5 6v6c0 4.6 3.1 7.9 7.5 9 4.4-1.1 7.5-4.4 7.5-9V6Z" />;
export const IcoFish = (p: P) => (
  <S {...p} d="M3 12c3-4.5 7-6.5 11-6.5 3.5 0 6 2 7 6.5-1 4.5-3.5 6.5-7 6.5-4 0-8-2-11-6.5Z"
    extra={<circle cx="16.5" cy="10.5" r=".9" fill="currentColor" />} />
);
export const IcoCompass = (p: P) => (
  <S {...p} d="m15.5 8.5-2 5-5 2 2-5Z" extra={<circle cx="12" cy="12" r="9" />} />
);
export const IcoBoat = (p: P) => <S {...p} d="M4 17h16l-2 4H6ZM6 17V9l6-3 6 3v8M12 6V3" />;
/** 펼쳐 보기. 좁은 패널 → 넓은 지면 */
/**
 * 필름 스트립 — 사고 전후 프레임을 되감아 보는 화면.
 * 카메라 라이브(IcoCamera)와 갈라야 한다. 전에 쓰던 경고 삼각형(IcoWarn)은
 * 하단 `긴급 신고` 와 같은 모양이라 사고를 내는 버튼으로 읽혔다.
 */
export const IcoFilm = (p: P) => (
  <S {...p} d="M3.5 5.5h17v13h-17zM8 5.5v13M16 5.5v13"
    extra={(
      <>
        <circle cx="5.75" cy="9" r=".75" fill="currentColor" stroke="none" />
        <circle cx="5.75" cy="15" r=".75" fill="currentColor" stroke="none" />
        <circle cx="18.25" cy="9" r=".75" fill="currentColor" stroke="none" />
        <circle cx="18.25" cy="15" r=".75" fill="currentColor" stroke="none" />
      </>
    )} />
);

export const IcoExpand = (p: P) => <S {...p} d="M9 21H3v-6M15 3h6v6M3 21 10.5 13.5M21 3l-7.5 7.5" />;
