/**
 * 지도에 올린 사고에 붙이는 번호.
 *
 * 색은 이미 긴급도(빨강·주황)와 실측/추정(채움·점선)에 다 쓰고 있어 더 쓸 수 없다.
 * 번호는 기존 색 체계를 건드리지 않으면서 카드와 지도 위 덩어리를 이어 준다.
 *
 * 순서는 **켠 순서**다. 포커스를 옮길 때마다 번호가 바뀌면 방금 외운 번호가 무의미해진다.
 */
const GLYPH = '①②③④⑤⑥⑦⑧⑨⑩';

export const noOf = (picked: string[], id: string) => picked.indexOf(id) + 1;

export const glyph = (n: number) => (n >= 1 && n <= GLYPH.length ? GLYPH[n - 1]! : `(${n})`);

/** 번호가 없으면(지도에 없으면) 빈 문자열 */
export const mark = (picked: string[], id: string) => {
  const n = noOf(picked, id);
  return n > 0 ? glyph(n) : '';
};
