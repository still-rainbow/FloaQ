package com.floaq.ocean.cluster;

import org.springframework.stereotype.Component;

import java.net.InetAddress;
import java.util.UUID;

/**
 * 이 백엔드 인스턴스의 이름 — DB 리스의 소유자 표식.
 *
 * 호스트명만 쓰지 않는다 — 같은 호스트에서 재기동한 새 프로세스가 죽은 프로세스의 리스를 제 것으로 풀면
 * 받는 중이던 수집과 겹친다. 기동마다 새 접미사를 붙인다.
 */
@Component
public class InstanceId {

    /** 컬럼 varchar(64) */
    private static final int MAX_LENGTH = 64;

    private final String value;

    public InstanceId() {
        String id = host() + "-" + UUID.randomUUID().toString().substring(0, 8);
        this.value = id.length() <= MAX_LENGTH ? id : id.substring(id.length() - MAX_LENGTH);
    }

    public String value() {
        return value;
    }

    private static String host() {
        try {
            return InetAddress.getLocalHost().getHostName();
        } catch (Exception e) {
            return "unknown";
        }
    }
}
