import type { FormEvent } from 'react';
import { useState } from 'react';
import { Mascot } from '../layout/Mascot';

/**
 * 최초 1회 선박 등록. 단말 하나에 선박 하나다.
 *
 * ⚠ **캘리브레이션(카메라 높이·발사장치 거리)은 여기서 받지 않는다**(2026-09-17).
 * Pi 가 자기 `env` 로 갖고 추락 위치 계산도 Pi 가 한다 — 두 곳에서 받으면
 * **어느 값으로 쐈는지 알 수 없다.** 설정 화면이 Pi 가 알려준 값을 보여주기만 한다.
 *
 * [[질문.md]] Q0-2("어선마다 구조가 다른데?")의 답은 그대로다 —
 * 선박마다 다른 값은 그 둘뿐이고, 설치할 때 한 번 잰다. **재는 곳이 Pi 로 옮겨졌을 뿐이다.**
 *
 * 가로 2단: 선내 단말은 가로 화면이라 세로로 쌓으면 아래가 잘린다 (2026-09-15 화면 확인)
 */
/** 신청서. 네 값이 전부다 — `ref/kiosk_시연.md` §4 */
export interface RegisterForm {
  name: string;
  regno: string;
  /** DSC·AIS 가 전파에 싣는 자기 식별자의 원본. **숫자 9자리** */
  mmsi: string;
  hasBuoy: boolean;
}

/** @param onSubmit 오류 문구를 돌려준다. null 이면 접수됨 */
export function Register(
  { onSubmit, busy }: { onSubmit: (v: RegisterForm) => Promise<string | null>; busy?: boolean },
) {
  const [form, setForm] = useState<RegisterForm>({ name: '', regno: '', mmsi: '', hasBuoy: true });
  const [err, setErr] = useState<string | null>(null);

  const set = (k: 'name' | 'regno' | 'mmsi') => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    void onSubmit(form).then(setErr);
  };

  return (
    <div className="screen">
      <form className="reg reg-wide" onSubmit={submit}>
        <div className="reg-head">
          <Mascot />
          <h2>선박 등록</h2>
        </div>

        <div className="card reg-grid">
          <div className="fields">
            <label><span className="lbl">선박명</span>
              <input type="text" required placeholder="제1해성호" autoComplete="off"
                value={form.name} onChange={set('name')} /></label>
            <label><span className="lbl">등록번호</span>
              <input type="text" required placeholder="부산선적 25-1104" autoComplete="off"
                value={form.regno} onChange={set('regno')} /></label>
            <label><span className="lbl">MMSI</span>
              <input type="text" required inputMode="numeric" pattern="[0-9]{9}"
                placeholder="440123456" autoComplete="off"
                value={form.mmsi} onChange={set('mmsi')} />
              {/* 9자리를 화면에서 막는다. Pi 가 400 으로 돌려주면 왜 거부됐는지 안 보인다 */}
              <span className="hint">숫자 9자리 · 조난 전파의 자기 식별자</span></label>
            <label className="chk">
              <input type="checkbox" checked={form.hasBuoy}
                onChange={(e) => setForm((f) => ({ ...f, hasBuoy: e.target.checked }))} />
              <span>구조 부표 장착</span></label>
          </div>

          <div className="fields">
            <div className="fieldset">
              <span className="eyebrow">설치 값 · 발사 위치 계산</span>
              {/* 입력이 아니라 안내다. 값은 Pi 가 갖고 있고 계산도 Pi 가 한다 */}
              <p className="hint calib-note">
                카메라 높이와 발사장치 거리는 <b>Pi 설정</b>에서 읽습니다.
                여기서 입력하면 값이 두 곳에 생겨 어느 것으로 쐈는지 알 수 없습니다.
              </p>
            </div>
            {err && <p className="reg-err" role="alert">{err}</p>}
            <div className="reg-actions">
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? '신청 중…' : '등록 신청'}
              </button>
              <button type="button" className="btn btn-ghost btn-sample" disabled={busy}
                onClick={() => setForm({ name: '제7해성호', regno: '부산선적 25-1104', mmsi: '440123456', hasBuoy: true })}>
                예시 값 채우기</button>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}
