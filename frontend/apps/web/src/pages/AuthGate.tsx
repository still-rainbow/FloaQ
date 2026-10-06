import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { DEMO, apply, login } from '../lib/auth';
import type { ApplyError, LoginError, Session } from '../lib/auth';

/**
 * 로그인(WEB-01) · 가입 신청(WEB-02). 로그인하지 않으면 관제 화면 대신 이 화면만 뜬다.
 *
 * 셀프 가입은 없다 — 가입 신청은 승인 대기로 들어가고, 관리자(SA)가 승인해야 로그인된다.
 * 로그인·가입 신청 모두 서버에 붙었다. 신청 칸은 이름 · 기관 이메일 · 비밀번호뿐이다 —
 * 해경 쪽에서는 신고를 받았는지만 알 수 있어 소속·계급을 받을 이유가 없다(2026-09-15).
 */

const LOGIN_MESSAGE: Record<LoginError, string> = {
  invalid: '이메일 또는 비밀번호가 맞지 않습니다.',
  pending: '가입 신청이 아직 승인되지 않았습니다. 관리자가 승인하면 로그인할 수 있습니다.',
  // 반려된 이메일은 다시 신청할 수 있다 — 서버가 옛 신청을 지우고 새로 받는다
  rejected: '가입 신청이 반려되었습니다. 내용을 확인해 다시 신청해 주세요.',
  deleted: '사용할 수 없는 계정입니다. 관리자에게 문의해 주세요.',
  server: '서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.',
};

/** 칸 하나에 붙일 수 없는 가입 실패. 중복은 이메일 칸에 붙인다 */
const APPLY_MESSAGE: Record<Exclude<ApplyError, 'duplicate'>, string> = {
  invalid: '입력한 내용을 다시 확인해 주세요.',
  server: '서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.',
};

const Mascot = () => (
  <svg className="mascot" viewBox="0 0 32 32" aria-hidden="true">
    <circle cx="16" cy="16" r="11" fill="#e2643a" />
    <path d="M5 16a11 11 0 0 1 22 0Z" fill="#ffb185" />
    <circle cx="16" cy="16" r="5.1" fill="#0c2a3d" />
    <circle cx="13.9" cy="14.9" r="1.75" fill="#eafcff" />
    <circle cx="18.1" cy="14.9" r="1.75" fill="#eafcff" />
    <circle cx="14.25" cy="15.2" r=".85" fill="#06131f" />
    <circle cx="18.45" cy="15.2" r=".85" fill="#06131f" />
    <path d="M14.5 18.7q1.5 1.15 3 0" stroke="#eafcff" strokeWidth="1.05" fill="none" strokeLinecap="round" />
  </svg>
);

export function AuthGate({ onLogin }: { onLogin: (s: Session) => void }) {
  const [mode, setMode] = useState<'login' | 'apply' | 'applied'>('login');
  const [appliedEmail, setAppliedEmail] = useState('');

  return (
    <main className="auth">
      <div className="auth-brand">
        <Mascot />
        <span className="brand-name">Floa<em>Q</em></span>
      </div>

      {mode === 'login' ? <LoginCard onLogin={onLogin} onApply={() => setMode('apply')} /> : null}
      {mode === 'apply'
        ? <ApplyCard onBack={() => setMode('login')} onDone={(email) => { setAppliedEmail(email); setMode('applied'); }} />
        : null}
      {mode === 'applied' ? (
        <section className="auth-card auth-done">
          <h1>신청을 받았습니다</h1>
          <p>
            관리자가 확인하고 승인하면{' '}
            <b className="mono">{appliedEmail}</b> 로 로그인할 수 있습니다.
          </p>
          <button className="btn primary auth-submit" onClick={() => setMode('login')}>로그인 화면으로</button>
        </section>
      ) : null}
    </main>
  );
}

function LoginCard({ onLogin, onApply }: { onLogin: (s: Session) => void; onApply: () => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError('기관 이메일과 비밀번호를 입력하세요.');
      return;
    }
    setBusy(true);
    setError(null);
    const r = await login(email, password);
    setBusy(false);
    if (r.ok) onLogin(r.session);
    else setError(LOGIN_MESSAGE[r.error]);
  }

  function fill(k: keyof typeof DEMO) {
    setEmail(DEMO[k].email);
    setPassword(DEMO[k].password);
    setError(null);
  }

  return (
    <form className="auth-card" onSubmit={submit} noValidate>
      <h1>로그인</h1>

      <label className="field">
        <span>기관 이메일</span>
        <input type="email" autoComplete="username" inputMode="email" value={email}
               onChange={(e) => setEmail(e.target.value)} placeholder="name@kcg.example" />
      </label>
      <label className="field">
        <span>비밀번호</span>
        <input type="password" autoComplete="current-password" value={password}
               onChange={(e) => setPassword(e.target.value)} />
      </label>

      {error ? <p className="auth-error" role="alert">{error}</p> : null}

      <button className="btn primary auth-submit" disabled={busy}>{busy ? '확인 중…' : '로그인'}</button>

      {/* 시연용 — 서버 local 프로파일이 만든 계정을 채운다 */}
      <div className="auth-demo">
        <span>시연용 계정</span>
        <button type="button" className="btn" onClick={() => fill('superadmin')}>관리자</button>
        <button type="button" className="btn" onClick={() => fill('admin')}>해경</button>
      </div>

      <p className="auth-switch">
        계정이 없나요? <button type="button" className="link-btn" onClick={onApply}>가입 신청</button>
      </p>
    </form>
  );
}

interface Draft {
  name: string;
  email: string;
  password: string;
  confirm: string;
}
type Errors = Partial<Record<keyof Draft, string>>;

const EMPTY: Draft = { name: '', email: '', password: '', confirm: '' };

// 서버 검사와 같은 상한이다. 어긋나면 화면은 통과시켰는데 서버가 거절해 칸을 짚어 줄 수 없다
/** users.name varchar(20) */
const NAME_MAX = 20;
/** users.login_id varchar(64) */
const EMAIL_MAX = 64;
const PASSWORD_MIN = 8;
/** bcrypt 가 받아들이는 상한. 글자 수가 아니라 바이트다 — 한글은 한 글자에 3바이트 */
const PASSWORD_MAX_BYTES = 72;

function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <label className={`field${error ? ' is-invalid' : ''}`}>
      <span>{label}</span>
      {children}
      {error ? <em className="field-error">{error}</em> : null}
    </label>
  );
}

function ApplyCard({ onBack, onDone }: { onBack: () => void; onDone: (email: string) => void }) {
  const [f, setF] = useState<Draft>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** 칸을 고치는 순간 그 칸의 오류는 지운다 — 다 채웠는데 빨간 글씨가 남아 있으면 아직 틀린 줄 안다 */
  const clearError = (k: keyof Errors) => setErrors((e) => {
    if (!e[k]) return e;
    const next = { ...e };
    delete next[k];
    return next;
  });
  const set = (k: keyof Draft) => (v: string) => {
    setF((p) => ({ ...p, [k]: v }));
    clearError(k);
    // 비밀번호를 고치면 확인 칸의 "서로 다릅니다"도 더는 맞지 않을 수 있다
    if (k === 'password') clearError('confirm');
  };

  function validate(): Errors {
    const e: Errors = {};
    const name = f.name.trim();
    const email = f.email.trim();
    if (!name) e.name = '이름을 입력하세요.';
    else if (name.length > NAME_MAX) e.name = `${NAME_MAX}자 이내로 입력하세요.`;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) e.email = '기관 이메일 형식이 아닙니다.';
    else if (email.length > EMAIL_MAX) e.email = `${EMAIL_MAX}자 이내로 입력하세요.`;
    if (f.password.length < PASSWORD_MIN) e.password = `${PASSWORD_MIN}자 이상으로 정하세요.`;
    else if (new TextEncoder().encode(f.password).length > PASSWORD_MAX_BYTES) e.password = '비밀번호가 너무 깁니다.';
    if (!f.confirm) e.confirm = '비밀번호를 한 번 더 입력하세요.';
    else if (f.confirm !== f.password) e.confirm = '비밀번호가 서로 다릅니다.';
    return e;
  }

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    const e = validate();
    setErrors(e);
    setFormError(null);
    if (Object.keys(e).length) return;
    setBusy(true);
    const r = await apply({ name: f.name, email: f.email, password: f.password });
    setBusy(false);
    if (r.ok) {
      onDone(f.email.trim());
      return;
    }
    if (r.error === 'duplicate') setErrors({ email: '이미 신청했거나 가입된 이메일입니다.' });
    else setFormError(APPLY_MESSAGE[r.error]);
  }

  return (
    <form className="auth-card is-wide" onSubmit={submit} noValidate>
      <h1>가입 신청</h1>
      <p className="auth-lede">관리자가 확인하고 승인하면 로그인할 수 있습니다.</p>

      <div className="field-row">
        <Field label="이름" error={errors.name}>
          <input type="text" autoComplete="name" value={f.name} onChange={(e) => set('name')(e.target.value)} />
        </Field>
        <Field label="기관 이메일" error={errors.email}>
          <input type="email" autoComplete="email" inputMode="email" value={f.email}
                 onChange={(e) => set('email')(e.target.value)} placeholder="name@kcg.example" />
        </Field>
      </div>

      <div className="field-row">
        <Field label="비밀번호" error={errors.password}>
          <input type="password" autoComplete="new-password" value={f.password}
                 onChange={(e) => set('password')(e.target.value)} placeholder={`${PASSWORD_MIN}자 이상`} />
        </Field>
        <Field label="비밀번호 확인" error={errors.confirm}>
          <input type="password" autoComplete="new-password" value={f.confirm}
                 onChange={(e) => set('confirm')(e.target.value)} />
        </Field>
      </div>

      {formError ? <p className="auth-error" role="alert">{formError}</p> : null}

      <button className="btn primary auth-submit" disabled={busy}>{busy ? '신청 중…' : '가입 신청'}</button>
      <p className="auth-switch">
        이미 계정이 있나요? <button type="button" className="link-btn" onClick={onBack}>로그인</button>
      </p>
    </form>
  );
}
