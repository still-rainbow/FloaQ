# CAD sources

- spring_launcher_v01: 스프링 슬라이더 코어와 공용 메쉬 검사 도구
- spring_launcher_v02_modular: 분리형 카세트·서보·트리거 구조
- yaw_base_v01: 발사기와 분리된 yaw 회전 베이스

v02는 v01의 launcher.scad와 build.py를 사용하므로 둘을 함께 유지합니다.
OpenSCAD가 필요하며 현재 build.py의 기본 설치 경로는 Windows용입니다.
Linux에서는 해당 도구의 CAD 실행 파일 경로를 자기 설치에 맞춰 지정하세요.
생성된 STL, PNG, QA 보고서와 zip 패키지는 Git에 포함하지 않습니다.
기존 하위 README의 렌더 결과와 검사 수치는 이전 실험 기록이며,
이 공개 준비 작업에서는 OpenSCAD 렌더나 물리 장치 검증을 다시 실행하지 않았습니다.
