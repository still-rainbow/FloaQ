# Infrastructure

## Local development

```bash
cp .env.example .env
docker compose up -d postgres redis
```

`docker-compose.yml`은 TimescaleDB와 Redis만 실행합니다.
서버와 프론트는 각각의 개발 명령으로 띄웁니다.
로컬 DB 계정 `floaq/floaq`는 개발 예제이며 외부 배포에 사용하지 않습니다.

## Deployment example

`docker-compose.prod.yml`과 nginx 설정은 배포 구조의 예제입니다.
예제 도메인 `floaq.example.com`, TLS 인증서 경로, 서버 비밀값,
프론트 빌드 결과와 저장소 설정을 자기 환경에 맞춰 구성한 뒤 사용합니다.
기존 CI 서버와 네트워크는 필요하지 않습니다. 배포용 예제 계정은 생성하지 않습니다.
LLM 요약은 기본 비활성이며 OpenAI 호환 `/chat/completions` 엔드포인트를
`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`로 지정할 수 있습니다.
