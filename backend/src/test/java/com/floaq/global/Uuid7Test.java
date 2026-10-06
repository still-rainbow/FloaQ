package com.floaq.global;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/** UUID v7 형식과 시간순 정렬 (RFC 9562). */
class Uuid7Test {

    @Test
    void 버전과_변형이_v7_이다() {
        for (int i = 0; i < 100; i++) {
            UUID id = Uuid7.next();
            assertThat(id.version()).isEqualTo(7);
            assertThat(id.variant()).isEqualTo(2);  // RFC 4122/9562 variant 10x
        }
    }

    /**
     * <b>정렬이 곧 시간 순서라는 것이 이 클래스를 쓰는 이유 전부다.</b>
     * 깨지면 v4 를 쓰는 것과 다를 바 없어지고, 배치 삽입에서 인덱스가 잘게 쪼개진다.
     */
    @Test
    void 나중에_만든_것이_뒤로_정렬된다() throws InterruptedException {
        List<UUID> 순서대로 = new ArrayList<>();
        for (int i = 0; i < 5; i++) {
            순서대로.add(Uuid7.next());
            Thread.sleep(2);  // 밀리초 해상도라 같은 ms 안에서는 순서를 보장하지 않는다
        }
        List<UUID> 정렬본 = new ArrayList<>(순서대로);
        정렬본.sort(Uuid7Test::unsignedCompare);
        assertThat(정렬본).isEqualTo(순서대로);
    }

    @Test
    void 같은_값이_나오지_않는다() {
        assertThat(java.util.stream.Stream.generate(Uuid7::next).limit(10_000).distinct().count())
                .isEqualTo(10_000);
    }

    /**
     * {@code UUID.compareTo} 는 <b>부호 있는</b> long 비교라 최상위 비트가 켜지는 순간 순서가 뒤집힌다.
     * DB(PostgreSQL {@code uuid})는 바이트 순서로 비교하므로 여기서도 부호 없이 본다.
     */
    private static int unsignedCompare(UUID a, UUID b) {
        int hi = Long.compareUnsigned(a.getMostSignificantBits(), b.getMostSignificantBits());
        return hi != 0 ? hi : Long.compareUnsigned(a.getLeastSignificantBits(), b.getLeastSignificantBits());
    }
}
