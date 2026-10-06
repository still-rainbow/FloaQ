# 빌드
FROM eclipse-temurin:21-jdk AS build
WORKDIR /app
COPY gradlew settings.gradle build.gradle ./
COPY gradle gradle
RUN chmod +x gradlew && ./gradlew dependencies --no-daemon || true
COPY src src
RUN ./gradlew bootJar --no-daemon -x test

# 런타임
# jre 아닌 jdk. jcmd/jstack/jmap 이 없으면 앱이 멈췄을 때 스레드 덤프를 뜰 수단이 사라진다.
# 빌드 스테이지와 같은 이미지라 레이어가 공유돼 디스크 비용은 사실상 0.
FROM eclipse-temurin:21-jdk
WORKDIR /app

ENV TZ=Asia/Seoul
ENV JAVA_TOOL_OPTIONS="\
-XX:MaxRAMPercentage=60.0 \
-XX:+HeapDumpOnOutOfMemoryError \
-XX:HeapDumpPath=/logs/ \
-Dfile.encoding=UTF-8"

COPY --from=build /app/build/libs/*.jar app.jar
EXPOSE 8080 9090
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
