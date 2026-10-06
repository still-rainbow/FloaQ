import { useId } from 'react';

/**
 * 목록 검색. 사고 · 기록 · 등록 선박 · 계정 관리가 <b>같은 상자</b>를 쓴다.
 *
 * <p>화면마다 다르게 생기면 같은 조작을 여러 번 배우게 된다. 찾는 대상만 바뀌고
 * 놓이는 자리(정렬 옆)와 생김새는 같다.</p>
 *
 * <p>서버에 묻지 않고 <b>이미 받아 둔 목록을 거른다</b> — 한 화면에 수십 건이라
 * 왕복할 이유가 없고, 글자마다 요청을 보내면 폴링과 섞여 순서가 뒤엉킨다.</p>
 */
export function SearchBox({ value, onChange, placeholder, hits }: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  /** 찾은 건수. 입력이 있을 때만 옆에 적는다 — 0 이면 "없다"가 분명해진다 */
  hits?: number;
}) {
  const id = useId();
  return (
    <div className="searchbox">
      <svg className="sb-ico" width="13" height="13" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
        <circle cx="11" cy="11" r="7" /><path d="m20 20-3.6-3.6" />
      </svg>
      <input
        id={id}
        type="search"
        value={value}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {/* 건수는 입력했을 때만. 늘 띄우면 "몇 건인지"가 목록 위 두 군데에 적힌다 */}
      {value && hits !== undefined ? (
        <span className={`sb-hits${hits === 0 ? ' is-none' : ''}`}>{hits}</span>
      ) : null}
      {value ? (
        <button className="sb-x" aria-label="검색어 지우기" onClick={() => onChange('')}>×</button>
      ) : null}
    </div>
  );
}

/**
 * 검색어가 이 값들 중 하나에 들어 있나.
 *
 * <p>공백과 하이픈을 지우고 비교한다 — 등록번호가 화면에는 {@code 부산-기장-0412} 로
 * 보이는데 사람은 {@code 부산기장0412} 나 {@code 0412} 로 친다. 그때 안 걸리면
 * 검색이 있으나 마나다.</p>
 */
const flat = (v: string) => v.toLowerCase().replace(/[\s-]/g, '');

export function matches(q: string, ...fields: (string | null | undefined)[]): boolean {
  const needle = flat(q);
  if (!needle) return true;
  return fields.some((f) => f && flat(f).includes(needle));
}
