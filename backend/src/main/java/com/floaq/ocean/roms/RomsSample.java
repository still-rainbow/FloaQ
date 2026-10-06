package com.floaq.ocean.roms;

/**
 * 표류 추정에 넘길 한 지점의 값 + 그 값을 얼마나 믿을 수 있는지.
 *
 * 값만 주면 화면이 격자 오차를 모른 채 점 하나를 그린다. 2026-09-13 실측에서
 * 3km 떨어진 이웃 격자가 유속 0.289 와 0.035 로 10배 갈리는 경계가 있었다 —
 * 부산 앞 북쪽 2칸이 육지에 둘러싸인 정체수역이었다.
 *
 * 보간으로 뭉개지 않는다. 0.289 와 0.035 를 평균한 0.16 은 어느 해역의 값도 아니다.
 * 대신 산포를 함께 내보내 표류 범위의 반경으로 쓴다.
 *
 * @param distanceKm        요청 좌표에서 이 격자까지. 한 칸(약 3km)을 넘으면 육지를 건너뛴 것이다
 * @param neighborSpreadMs  이웃 격자와의 유속 최대 차이. 경계에 걸리면 커진다
 * @param neighborCount     산포를 계산한 격자 수(자기 자신 포함). 1 이면 이웃이 없어 산포가 null
 */
public record RomsSample(
        RomsGrid grid,
        double distanceKm,
        Double neighborSpreadMs,
        int neighborCount) {
}
