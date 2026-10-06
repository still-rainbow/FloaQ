#!/usr/bin/env python3
"""E22 설정 실패 진단 — 어느 계층에서 끊겼는지 순서대로 확인한다."""
import glob, sys, time
import serial
import RPi.GPIO as GPIO          # rpi-lgpio 셤. PI 의존성에 이미 있다

M0, M1, AUX = 23, 24, 18         # 실제 배선에 맞게 수정
PORT = "/dev/ttyAMA2"            # Pi 5는 serial0 이 아니다

print("=== 1. 시리얼 장치")
for p in sorted(glob.glob("/dev/ttyAMA*") + glob.glob("/dev/serial*")):
    import os
    tgt = os.path.realpath(p)
    print(f"   {p:16} -> {tgt}")
print(f"   사용할 포트: {PORT}")

print("\n=== 2. 콘솔이 UART를 잡고 있는지")
print("   " + open("/boot/firmware/cmdline.txt").read().strip())
cfg = open("/boot/firmware/config.txt").read()
print(f"   dtparam=uart0=on 있음: {'dtparam=uart0=on' in cfg}")

GPIO.setmode(GPIO.BCM)
GPIO.setup([M0, M1], GPIO.OUT)
GPIO.setup(AUX, GPIO.IN)

def mode(m1, m0, label):
    GPIO.output(M1, m1); GPIO.output(M0, m0)
    time.sleep(0.05)
    print(f"   M1={m1} M0={m0} ({label:8}) -> AUX={GPIO.input(AUX)}")

print("\n=== 3. AUX 반응 (모듈 전원·배선 확인)")
print("   AUX는 유휴 시 HIGH(1)여야 한다. 전부 0이면 전원이나 AUX 배선 문제다.")
mode(0, 0, "일반"); mode(0, 1, "설정"); mode(0, 0, "일반")

print("\n=== 4. 루프백 (Pi UART 자체가 동작하는가)")
print("   >>> 지금 GPIO14(8번핀)와 GPIO15(10번핀)를 점퍼로 직접 연결하고 Enter")
input()
try:
    with serial.Serial(PORT, 9600, timeout=0.5) as s:
        s.reset_input_buffer()
        s.write(b"LOOPBACK123"); s.flush()
        got = s.read(11)
    print(f"   보낸 것 b'LOOPBACK123' / 받은 것 {got!r}")
    print("   => " + ("Pi UART 정상. 문제는 모듈이나 배선 쪽이다."
                      if got == b"LOOPBACK123" else
                      "Pi UART 문제다. 포트/오버레이/콘솔부터 고쳐야 한다."))
except Exception as e:
    print(f"   포트 열기 실패: {e}")
print("   >>> 점퍼를 빼고 모듈을 다시 연결한 뒤 Enter")
input()

print("\n=== 5. 설정 모드에서 레지스터 읽기 (보레이트 훑기)")
GPIO.output(M1, 1); GPIO.output(M0, 1)
time.sleep(0.1)
for baud in (9600, 115200, 19200, 38400, 57600):
    try:
        with serial.Serial(PORT, baud, timeout=0.6) as s:
            s.reset_input_buffer()
            s.write(bytes([0xC1, 0x00, 0x09])); s.flush()
            time.sleep(0.3)
            r = s.read(64)
        print(f"   {baud:6} baud -> {len(r):2}바이트  {r.hex(' ') if r else '(무응답)'}")
        if r[:1] == b"\xC1":
            print("   => 응답 확인. 이 보레이트로 설정하면 된다.")
    except Exception as e:
        print(f"   {baud:6} baud -> 실패 {e}")

GPIO.output(M1, 0); GPIO.output(M0, 0)
GPIO.cleanup()
print("\n끝. 위 출력 전체를 그대로 붙여주세요.")
