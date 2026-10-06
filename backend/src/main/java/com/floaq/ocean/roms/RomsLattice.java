package com.floaq.ocean.roms;

/**
 * ROMS 격자의 기하. 저장된 값에서 읽어 낸다.
 *
 * 모델 격자는 공간에 고정돼 있다 — bbox 는 그중 어디를 받을지 고를 뿐이다.
 * 그래서 원점과 간격만 알면 <b>어떤 bbox 가 어떤 격자점을 고를지 미리 계산</b>할 수 있다.
 *
 * 상수로 박지 않고 데이터에서 읽는 이유: KHOA 가 해상도를 바꾸면 박아 둔 값은 조용히 틀린다.
 *
 * @param latStep 위도 간격. 2026-09-13 부산 앞 실측 0.02864° (3.19km)
 * @param lonStep 경도 간격. 0.03197° (2.91km at 35°N)
 */
public record RomsLattice(double latMin, double lonMin, double latStep, double lonStep) {

    /** 부동소수 비교 여유. 간격의 1% 면 격자를 가르기에 충분하다 */
    private static final double EPS_RATIO = 0.01;

    /** bbox 가 고르는 격자 인덱스 범위 */
    public record Selection(int latLo, int latHi, int lonLo, int lonHi) {

        /** 고르는 점이 하나도 없다. bbox 가 격자 사이에 끼었거나 범위 밖이다 */
        public boolean isEmpty() {
            return latLo > latHi || lonLo > lonHi;
        }

        public boolean contains(int latIndex, int lonIndex) {
            return latIndex >= latLo && latIndex <= latHi && lonIndex >= lonLo && lonIndex <= lonHi;
        }
    }

    /** bbox 가 고르는 격자 인덱스 범위 */
    public Selection selectionOf(double south, double north, double west, double east) {
        return new Selection(
                lo(south, latMin, latStep), hi(north, latMin, latStep),
                lo(west, lonMin, lonStep), hi(east, lonMin, lonStep));
    }

    /**
     * 이 좌표의 최근접 격자와 <b>이웃 한 칸까지</b> 선택 안에 있나.
     *
     * 최근접 점만 보면 안 된다 — 배가 가장자리 칸에 서면 한쪽에만 이웃이 있어
     * {@code neighborSpreadMs}(이웃 유속 산포)가 실제보다 작게 나온다.
     * 사방에 한 칸씩 있어야 그 값이 의미를 갖는다.
     *
     * bbox 선택 자체를 비교하지 않는 이유: 0.1° bbox 는 위도 4행뿐이라
     * 가장자리가 격자점을 스칠 때마다 선택이 바뀐다. 1km 만 움직여도 끝 행이 들락날락하는데,
     * 그건 배 근처에서 아무것도 달라지지 않는 변화다.
     */
    public boolean coversNeighborhood(Selection selection, double lat, double lon) {
        int i = nearestIndex(lat, latMin, latStep);
        int j = nearestIndex(lon, lonMin, lonStep);
        return selection.contains(i - 1, j - 1) && selection.contains(i + 1, j + 1);
    }

    private static int nearestIndex(double value, double origin, double step) {
        return (int) Math.round((value - origin) / step);
    }

    private static int lo(double bound, double origin, double step) {
        return (int) Math.ceil((bound - origin) / step - EPS_RATIO);
    }

    private static int hi(double bound, double origin, double step) {
        return (int) Math.floor((bound - origin) / step + EPS_RATIO);
    }
}
