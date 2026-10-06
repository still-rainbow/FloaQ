import type { MapTheme } from '@floaq/shared';
import type { Vessel } from '../types';
import { IcoBoat, IcoClose } from '../layout/Icons';

interface Props {
  vessel: Vessel;
  theme: MapTheme;
  setTheme: (v: MapTheme) => void;
  onClose: () => void;
  onWipe: () => void;
  onComms: () => void;
  /** 해양 상황판 — 같은 데이터를 넓게 펼쳐 보는 화면 */
  onOcean: () => void;
}

const THEMES: { key: MapTheme; label: string; swatch: string }[] = [
  { key: 'chart', label: '해도', swatch: '#dcecec' },
  { key: 'abyss', label: '심해', swatch: '#0d3348' },
  { key: 'dawn', label: '여명', swatch: '#4a3352' },
  { key: 'day', label: '백야', swatch: '#93cbde' },
];

/** 가로 3단. 세로로 쌓으면 선내 가로 화면에서 아래가 잘린다 (2026-09-15 화면 확인) */
export function SettingsSheet(p: Props) {
  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="setTitle">
      <div className="sheet-card set-card">
        <div className="sheet-top">
          <IcoBoat size={28} />
          <h3 id="setTitle">설정</h3>
          <button className="icon-btn" onClick={p.onClose} aria-label="닫기"><IcoClose size={22} /></button>
        </div>

        <div className="sheet-body">
          <section className="set-sec">
            <h4>화면</h4>
            {/* 밝기(주간·야간)는 없앴다 (2026-09-16) — terminal.css 에 data-ui 규칙이 없어 눌러도 아무것도 안 바뀌었다.
                야간 모드가 필요해지면 CSS 부터 만든다. 지도 테마는 실제로 동작하므로 남긴다 */}
            <div className="set-row">
              {/* 야간 조업에는 심해가 눈이 덜 부시다. 선택은 이 단말에 저장된다 */}
              <span className="set-label">지도</span>
              <div className="pick" role="group" aria-label="지도 테마">
                {THEMES.map((t) => (
                  <button key={t.key} className="pick-btn" aria-pressed={p.theme === t.key}
                    onClick={() => p.setTheme(t.key)}>
                    <i style={{ background: t.swatch }} />{t.label}
                  </button>
                ))}
              </div>
            </div>
          </section>

          <section className="set-sec">
            <h4>선박</h4>
            <dl className="kv">
              <div><dt>선박명</dt><dd>{p.vessel.name}</dd></div>
              <div><dt>등록번호</dt><dd className="mono">{p.vessel.regno}</dd></div>
              {/* 🔴 값이 없으면 **줄 자체를 안 그린다** (2026-09-18 요청).
                  'Pi 설정값 — 아직 받지 못했습니다' 를 늘 띄우던 자리인데, Pi 가 이 값을
                  보내는 경로가 아직 없어 사실상 상시 문구였다 — 설정 화면이 고장난 것처럼 보였다.
                  ⚠ 0 으로 채우지 않는다. 0 은 "카메라가 수면 높이"로 읽힌다.
                  Pi 가 보내기 시작하면 줄이 저절로 살아난다. */}
              {p.vessel.camH && p.vessel.launchOff && (
                <div><dt>카메라 높이 · 발사장치 거리</dt>
                  <dd className="mono">{p.vessel.camH} m · {p.vessel.launchOff} m</dd></div>
              )}
            </dl>
          </section>

          <div className="set-col">
            <section className="set-sec">
              <h4>점검</h4>
              {/* 주소로도 간다 — #/comms */}
              <div className="set-actions">
                <button className="btn btn-ghost" onClick={p.onOcean}>해양 상황판</button>
                <button className="btn btn-ghost" onClick={p.onComms}>통신 확인</button>
              </div>
            </section>

            <div className="danger-zone">
              <h4>등록 삭제</h4>
              <p>사고 기록은 서버에 남습니다</p>
              <button className="btn btn-danger" onClick={p.onWipe}>등록 정보 삭제</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
