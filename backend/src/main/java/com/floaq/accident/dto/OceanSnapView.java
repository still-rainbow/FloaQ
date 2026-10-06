package com.floaq.accident.dto;

import com.floaq.accident.entity.Accident;

import java.time.Instant;

/**
 * 사고가 나던 때의 바다 (V20260921_1210).
 *
 * <p>화면은 <b>이 값을 먼저 쓴다</b>. 없을 때만 해양 조회로 메우고, 그마저 24시간이 지났으면
 * "기록이 남아 있지 않다"고 말한다. 있는 사고는 몇 년 뒤에 열어도 같은 값이 나온다.</p>
 *
 * <p>{@code windDirDeg} 는 <b>불어오는 쪽</b>이다 — 기상 관례 그대로다. 표류 계산이 쓰는
 * "흘러가는 쪽"으로 미리 돌려 두면 기상청 값과 달라 보여 그 자체가 오해를 부른다.</p>
 */
public record OceanSnapView(Float currentSpeedMs, Float currentDirDeg,
                            Float windSpeedMs, Float windDirDeg,
                            Float spreadMs, Instant observedAt) {

    /** 관측 시각이 없으면 받아 둔 적이 없는 것이다 — 그때는 아예 내려보내지 않는다 */
    public static OceanSnapView of(Accident a) {
        if (a.getOceanObservedAt() == null) {
            return null;
        }
        return new OceanSnapView(a.getOceanCurrentSpeedMs(), a.getOceanCurrentDirDeg(),
                a.getOceanWindSpeedMs(), a.getOceanWindDirDeg(),
                a.getOceanSpreadMs(), a.getOceanObservedAt());
    }
}
