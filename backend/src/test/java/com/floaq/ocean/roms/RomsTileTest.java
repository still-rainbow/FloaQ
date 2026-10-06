package com.floaq.ocean.roms;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/** 0.25° 타일 — 좌표만 보고 정해져야 선박들이 수집 범위를 서로 빼앗지 않는다 */
class RomsTileTest {

    @Test
    void 좌표로_타일이_정해진다() {
        // 2026-09-15 화면 재현 좌표 (기장 앞)
        var tile = RomsTile.of(35.1992, 129.267);

        assertThat(tile).isEqualTo(new RomsTile(140, 517));
        assertThat(tile.south()).isEqualTo(35.0);
        assertThat(tile.north()).isEqualTo(35.25);
        assertThat(tile.west()).isEqualTo(129.25);
        assertThat(tile.east()).isEqualTo(129.5);
    }

    @Test
    void 경계_격자점은_한_타일만_갖는다() {
        // API bbox 는 양끝 포함이라 이웃 타일 응답에 같은 점이 온다 — 둘 다 가지면 한쪽 재수집이 남의 칸을 지운다
        var south = new RomsTile(140, 517);
        var north = new RomsTile(141, 517);

        assertThat(south.owns(35.0, 129.3)).isTrue();
        assertThat(south.owns(35.25, 129.3)).isFalse();
        assertThat(north.owns(35.25, 129.3)).isTrue();
    }

    @Test
    void 음수_좌표도_아래로_내린다() {
        // 정수 나눗셈(0 쪽으로 버림)이면 -0.1 이 0.1 과 같은 타일이 된다
        assertThat(RomsTile.of(-0.1, -0.1)).isEqualTo(new RomsTile(-1, -1));
    }

    @Test
    void 타일_가운데_본선의_수집_범위는_한_타일이다() {
        // 반폭 0.1° 는 타일 절반(0.125°)보다 작다 — 가운데면 1개, 모서리여도 4개를 넘지 않는다
        assertThat(RomsTile.covering(35.125, 129.375, RomsTileService.DEMAND_HALF_DEG, RomsTileService.DEMAND_HALF_DEG))
                .containsExactly(new RomsTile(140, 517));
        assertThat(RomsTile.covering(35.24, 129.49, RomsTileService.DEMAND_HALF_DEG, RomsTileService.DEMAND_HALF_DEG))
                .hasSize(4);
    }

    @Test
    void 이웃_한_칸이_경계를_넘으면_두_타일이_필요하다() {
        var tiles = RomsTile.covering(35.24, 129.375, 0.0286, 0.032);

        assertThat(tiles).containsExactly(new RomsTile(140, 517), new RomsTile(141, 517));
    }
}
