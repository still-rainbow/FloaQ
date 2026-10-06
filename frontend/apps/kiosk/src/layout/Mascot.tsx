/** 데모 원본에서 추출한 마스코트. 경로 좌표를 손으로 옮기지 않았다 */
export function Mascot({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: `<circle cx="16" cy="16" r="11" fill="#ff8a4c"/><path d="M5 16a11 11 0 0 1 22 0Z" fill="#ffb185"/><circle cx="16" cy="16" r="5.1" fill="#0c2a3d"/><circle cx="13.9" cy="14.9" r="1.75" fill="#eafcff"/><circle cx="18.1" cy="14.9" r="1.75" fill="#eafcff"/><circle cx="14.25" cy="15.2" r=".85" fill="#06131f"/><circle cx="18.45" cy="15.2" r=".85" fill="#06131f"/><path d="M14.5 18.7q1.5 1.15 3 0" stroke="#eafcff" stroke-width="1.05" fill="none" stroke-linecap="round"/>` }} />
  );
}
