import type { AlertType, Urgency } from '@floaq/shared';
import { IcoClose, IcoWarn } from '../layout/Icons';

/**
 * 수동 신고 (§9.21). AI 감지와 무관한 별도 진입점이다.
 *
 * **유예가 없다** — 유형까지 골라서 누른 것은 이미 확인된 판단이고,
 * 30초를 다시 세우면 방금 한 판단을 시스템이 되묻는 꼴이 된다.
 *
 * 유형은 ITU-R M.493 DSC nature of distress 코드를 인용한다 — 우리가 분류를 정의하면 근거를 못 댄다.
 * 긴급도를 가르는 이유: 받는 쪽이 다르게 움직인다. 응급 환자를 조난으로 쏘면 구조 세력이 출동한다.
 */
interface Item { type: AlertType; label: string }

const SECTIONS: { urg: Urgency; key: string; tag: string; cls: string; note: string; items: Item[] }[] = [
  {
    urg: 'DISTRESS', key: 'distress', tag: '조난', cls: 'urg-d', note: '구조 출동',
    items: [
      { type: 'MOB', label: '사람 추락' },          // DSC 110
      { type: 'FIRE', label: '화재' },              // 100
      // UI 한 버튼, DSC 는 101/104 — Pi 가 IMU 롤 각으로 가른다. 물이 드는 배에서 둘을 고르라 할 수 없다
      { type: 'FLOODING', label: '침수 · 전복' },
      { type: 'COLLISION', label: '충돌' },         // 102
      { type: 'DISABLED', label: '기관 고장' },     // 106
      { type: 'GROUNDING', label: '좌초' },         // 103
      { type: 'UNDESIGNATED', label: '기타 조난' }, // 107
    ],
  },
  {
    urg: 'URGENCY', key: 'urgency', tag: '긴급', cls: 'urg-u', note: '지원 요청',
    items: [{ type: 'MEDICAL', label: '응급 환자' }],
  },
  // ⚠ '안전(위험물 발견)' 칸을 뺐다 (2026-09-18). IoT `AccidentType` 에서 HAZARD 가 사라져
  //   누르면 Pi 가 ValidationError 로 버리고 **응답도 주지 않는다** — 화면에는 5초 뒤 타임아웃만 떴다.
  //   되살린다면 IoT 쪽 enum 부터다. 화면에만 두는 버튼은 만들지 않는다.
];

interface Props {
  onClose: () => void;
  onSend: (urgency: Urgency, type: AlertType) => void;
  busy: string | null;
}

export function SosSheet({ onClose, onSend, busy }: Props) {
  const section = (s: (typeof SECTIONS)[number]) => (
    <section key={s.urg} className="sos-sec" data-urg={s.key}>
      <div className="sos-head">
        <span className={`urg-tag ${s.cls}`}>{s.tag}</span>
        <span className="sos-head-note">{s.note}</span>
      </div>
      <div className="sos-grid">
        {s.items.map((it) => (
          <button key={it.type} className="sos-btn" data-type={it.type} disabled={!!busy}
            onClick={() => onSend(s.urg, it.type)}>
            {it.label}
          </button>
        ))}
      </div>
    </section>
  );

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="sosTitle">
      <div className="sheet-card sos-card">
        <div className="sheet-top">
          <IcoWarn size={30} />
          <h3 id="sosTitle">긴급 신고</h3>
          <button className="icon-btn" onClick={onClose} aria-label="닫기"><IcoClose size={22} /></button>
        </div>

        <div className="sheet-body">
          <p className="sos-lede">누르면 <b>바로 발신됩니다</b></p>
          {/* 조난은 한 줄 전체, 긴급·안전은 버튼이 하나씩이라 나란히 */}
          {SECTIONS.slice(0, 1).map(section)}
          <div className="sos-pair">{SECTIONS.slice(1).map(section)}</div>
          {busy && <p className="sos-busy">{busy}</p>}
        </div>
      </div>
    </div>
  );
}
