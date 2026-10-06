package com.floaq.auth.dto;

import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.Set;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 가입 신청 입력 검증. 컨트롤러의 {@code @Valid} 와 같은 Bean Validation 을 직접 돌린다 — DB·서버 기동 없음.
 */
class SignupRequestTest {

    private static ValidatorFactory factory;
    private static Validator validator;

    @BeforeAll
    static void setUp() {
        factory = Validation.buildDefaultValidatorFactory();
        validator = factory.getValidator();
    }

    @AfterAll
    static void tearDown() {
        factory.close();
    }

    private static Set<String> invalidFields(SignupRequest request) {
        return validator.validate(request).stream()
                .map(ConstraintViolation::getPropertyPath)
                .map(Object::toString)
                .collect(Collectors.toSet());
    }

    @Test
    void 이메일과_이름의_앞뒤_공백은_검증_전에_지운다() {
        // 로그인은 공백 섞인 이메일을 받는다. 가입만 형식 오류로 거절하면 둘이 어긋난다
        SignupRequest request = new SignupRequest("  SIGNUP@kcg.example ", "floaq1234!", " 박서연 ");

        assertThat(request.loginId()).isEqualTo("SIGNUP@kcg.example");
        assertThat(request.name()).isEqualTo("박서연");
        assertThat(invalidFields(request)).isEmpty();
    }

    @Test
    void 비밀번호의_공백은_그대로_둔다() {
        assertThat(new SignupRequest("a@kcg.example", " floaq1234! ", "박서연").password())
                .isEqualTo(" floaq1234! ");
    }

    @Test
    void 공백만_있는_이름은_빈_값으로_거절한다() {
        assertThat(invalidFields(new SignupRequest("a@kcg.example", "floaq1234!", "   "))).containsExactly("name");
    }

    @Test
    void 칸이_빠져도_생성자에서_터지지_않고_검증이_잡는다() {
        // null 을 trim 하다 NullPointerException 이 나면 400 이 아니라 500 이 된다
        assertThat(invalidFields(new SignupRequest(null, "floaq1234!", null))).containsExactlyInAnyOrder("loginId", "name");
    }

    @Test
    void 테이블_길이를_넘으면_거절한다() {
        String longEmail = "a".repeat(60) + "@kcg.example";
        assertThat(invalidFields(new SignupRequest(longEmail, "floaq1234!", "가".repeat(21))))
                .containsExactlyInAnyOrder("loginId", "name");
    }
}
