package com.floaq.pi;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.HexFormat;

/**
 * 선박 Pi 키의 발급과 해시 (docs/api.md §1.1 · V20260917_1730).
 *
 * <p><b>평문은 발급 응답에만 실리고 서버에 남지 않는다.</b> DB 에는 SHA-256 만 둔다 —
 * 덤프·백업으로 새어도 그것만으로는 쓸 수 없다(리프레시 토큰과 같은 방식, 계획.md §2).</p>
 *
 * <p><b>왜 bcrypt 가 아닌가.</b> 이 해시는 <b>조회에 쓴다</b> — "이 키의 주인이 누구인가"를
 * 인덱스로 찾아야 한다. bcrypt 는 salt 가 행마다 달라 그게 불가능하다(모든 행을 하나씩 대조해야 한다).
 * 키가 32바이트 난수라 비밀번호와 달리 사전 공격 대상이 아니므로 salt·stretching 이 필요 없다.</p>
 */
public final class PiKeys {

    /** 32바이트 = hex 64자. 추측으로 뚫는 것이 논외가 되는 길이다. */
    private static final int KEY_BYTES = 32;

    private static final SecureRandom RANDOM = new SecureRandom();

    private PiKeys() {
    }

    /** 새 선박 키(평문). <b>호출한 쪽이 응답에 실어 보내고 버린다</b> — 어디에도 저장하지 않는다. */
    public static String newKey() {
        byte[] bytes = new byte[KEY_BYTES];
        RANDOM.nextBytes(bytes);
        return HexFormat.of().formatHex(bytes);
    }

    /** SHA-256 hex 64자. DB 의 {@code ship.edge_key_hash} 와 같은 형식이다. */
    public static String hash(String key) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(key.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException e) {
            // SHA-256 은 JDK 필수 알고리즘이다. 여기 오면 런타임이 망가진 것이다
            throw new IllegalStateException("SHA-256 을 쓸 수 없습니다", e);
        }
    }
}
