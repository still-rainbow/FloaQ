# FloaQ Pi 개발 스크립트 (Windows / PowerShell)
#
# 사용:
#   .\scripts\dev.ps1 reset     DB·프레임·등록 대기 전부 지운다. 등록부터 다시
#   .\scripts\dev.ps1 broker    mosquitto 기동 (1883 + 9001)
#   .\scripts\dev.ps1 pi        오케스트레이터 기동
#   .\scripts\dev.ps1 sub       전체 메시지 덤프
#   .\scripts\dev.ps1 kiosk     개발용 키오스크 + 웹서버 (ws://9001)
#   .\scripts\dev.ps1 detect    가짜 탐지 1회 발행
#   .\scripts\dev.ps1 status    떠 있는 것 확인
#   .\scripts\dev.ps1 stop      전부 종료
#
# broker / pi / sub / kiosk 는 각각 별도 창에서 띄운다. 전부 포그라운드로 돈다.
#
# ⚠ 이 파일은 UTF-8 **with BOM** 으로 저장해야 한다.
#   Windows PowerShell 5.1 은 BOM 이 없으면 ANSI 로 읽어서 한글이 깨진다.
#
# ⚠ param() 에 파라미터를 하나만 둔다. [ValidateSet] 와 두 번째 파라미터를 같이 두면
#   PowerShell 5.1 이 "매개 변수 이름이 잘못되었습니다" 로 파싱에 실패한다. 실제로 밟았다.
#   detect 에 붙일 추가 인자(--no-solution 등)는 자동 변수 $args 로 받는다.

param(
    [ValidateSet('reset', 'broker', 'pi', 'sub', 'detect', 'kiosk', 'lora-a', 'lora-b',
                 'distress', 'status', 'stop', 'help')]
    [string]$Command = 'help'
)

# ── UTF-8 고정 ───────────────────────────────────────────────────────
# 셋 다 필요하다. 하나라도 빠지면 어딘가에서 깨진다.
#   chcp              콘솔 코드페이지 (외부 exe 출력)
#   OutputEncoding    PowerShell 이 화면에 쓸 때
#   PYTHONIOENCODING  파이썬 stdout/stderr
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot          # IoT/PI
$Schema = Join-Path $Root '..\..\database\pi.sql'
$ShipFile = Join-Path $Root '.ship_id'
Set-Location $Root

# mosquitto 위치. PATH 에 없을 수 있어 기본 설치 경로도 본다.
$Mosquitto = (Get-Command mosquitto.exe -ErrorAction SilentlyContinue).Source
if (-not $Mosquitto) { $Mosquitto = 'C:\Program Files\mosquitto\mosquitto.exe' }
$MosquittoSub = Join-Path (Split-Path $Mosquitto) 'mosquitto_sub.exe'


function Get-ShipId {
    if (-not (Test-Path $ShipFile)) {
        Write-Host "SHIP_ID 가 없다. 먼저 실행:  .\scripts\dev.ps1 reset" -ForegroundColor Red
        exit 1
    }
    (Get-Content $ShipFile -Raw).Trim()
}

function Invoke-Stop {
    Get-CimInstance Win32_Process |
        Where-Object { ($_.Name -eq 'python.exe'    -and $_.CommandLine -like '*main.py*') -or
                       ($_.Name -eq 'mosquitto.exe' -and $_.CommandLine -like '*mosquitto.conf*') } |
        ForEach-Object {
            Write-Host "  종료  $($_.ProcessId) $($_.Name)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

function Show-Status {
    Write-Host ''
    Write-Host '-- 리스너 --' -ForegroundColor Cyan
    $lines = netstat -ano | Select-String ':1883|:9001' | Select-String 'LISTENING'
    if ($lines) { $lines | ForEach-Object { Write-Host "  $_" } }
    else { Write-Host '  없음' -ForegroundColor DarkGray }

    Write-Host ''
    Write-Host '-- 프로세스 --' -ForegroundColor Cyan
    $procs = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -in 'mosquitto.exe', 'python.exe' -and
                       ($_.CommandLine -like '*mosquitto.conf*' -or $_.CommandLine -like '*main.py*') }
    if ($procs) { $procs | ForEach-Object { Write-Host ("  {0,-6} {1}" -f $_.ProcessId, $_.Name) } }
    else { Write-Host '  없음' -ForegroundColor DarkGray }

    # ⚠ winget 으로 설치하면 mosquitto 가 Windows 서비스로 자동 등록된다.
    #   그러면 127.0.0.1:1883 을 먼저 잡아서 우리 conf 가 적용 안 되고 9001 이 안 열린다.
    $svc = Get-Service mosquitto -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') {
        Write-Host ''
        Write-Host '  경고: mosquitto Windows 서비스가 돌고 있다.' -ForegroundColor Yellow
        Write-Host '  우리 conf 가 무시되고 9001 이 안 열린다. 관리자 권한으로 중지할 것:' -ForegroundColor Yellow
        Write-Host '    Stop-Service mosquitto -Force; Set-Service mosquitto -StartupType Manual' -ForegroundColor Yellow
    }

    if (Test-Path $ShipFile) {
        Write-Host ''
        Write-Host "  SHIP_ID  $(Get-ShipId)"
    }
    Write-Host ''
}


switch ($Command) {

    'reset' {
        # 🔴 선박 키가 같이 날아간다. pi_credential 이 DB 안에 있고, 서버는 같은
        #   registration_no 로 다시 등록해도 ship_key 를 다시 주지 않는다
        #   (실측: 재전송이면 200 + ship_key: null). 그 배는 영영 EC2 에 못 붙는다.
        #   초기화 뒤에는 **새 registration_no** 로 등록해야 한다.
        if (Test-Path 'floaq.db') {
            Write-Host '경고: 선박 키가 지워진다. 서버는 같은 등록번호로 키를 다시 주지 않는다.' -ForegroundColor Yellow
            Write-Host '      초기화 뒤에는 새 등록번호로 등록할 것.' -ForegroundColor Yellow
            $ans = Read-Host "계속하려면 'yes' 입력"
            if ($ans -ne 'yes') { Write-Host '취소했다'; exit 1 }
        }

        # 떠 있으면 DB 파일이 잠긴다. 먼저 내린다.
        Invoke-Stop
        Start-Sleep -Milliseconds 500
        Remove-Item 'floaq.db', 'floaq.db-wal', 'floaq.db-shm', 'pi.log',
                    'floaq.db.pending-ship.json', 'floaq.db.pending-ship.json.part',
                    '.ship_id', '.aid' -ErrorAction SilentlyContinue
        Remove-Item 'data' -Recurse -Force -ErrorAction SilentlyContinue

        Write-Host '지웠다: DB · 등록 대기 · 프레임(data/)' -ForegroundColor Green
        Write-Host '.env 는 그대로 둔다 (등록 키)' -ForegroundColor Yellow
        Write-Host ''
        Write-Host '다음:'
        Write-Host '  .\scripts\dev.ps1 broker      별도 창'
        Write-Host '  uv run main.py               등록 모드로 뜬다'
        Write-Host '  그리고 키오스크나 curl 로 POST /api/ship'
    }

    'broker' {
        if (-not (Test-Path $Mosquitto)) {
            Write-Host "mosquitto 를 찾을 수 없다: $Mosquitto" -ForegroundColor Red
            Write-Host '설치:  winget install EclipseFoundation.Mosquitto' -ForegroundColor Yellow
            exit 1
        }
        Write-Host '브로커 기동  1883(TCP) + 9001(WebSocket)' -ForegroundColor Green
        Write-Host 'Ctrl+C 로 종료' -ForegroundColor DarkGray
        Write-Host ''
        & $Mosquitto -c mosquitto.conf -v
    }

    'pi' {
        $ship = Get-ShipId
        Write-Host "오케스트레이터 기동  ship=$ship" -ForegroundColor Green
        Write-Host '로그는 pi.log 에도 남는다. Ctrl+C 로 종료' -ForegroundColor DarkGray
        Write-Host ''

        # ⚠ `2>&1 | Tee-Object` 를 쓰지 않는다. 파이썬 logging 은 stderr 로 나가는데
        #   PowerShell 은 네이티브 exe 의 stderr 를 에러 레코드로 감싸서
        #   로그 한 줄마다 NativeCommandError 를 찍는다. 화면을 못 볼 지경이 된다.
        #   파이썬이 직접 파일에 쓰게 하고 PowerShell 은 건드리지 않는다.
        Remove-Item pi.log -ErrorAction SilentlyContinue
        $env:FLOAQ_LOG_FILE = 'pi.log'

        # --fake-hw: GPIO·LoRa·GPS·UDP 어댑터가 아직 없다. 실제로 발사되지 않는다.
        python main.py --ship-id $ship --fake-hw -v
    }

    'sub' {
        $ship = Get-ShipId
        Write-Host "구독  ship/$ship/#" -ForegroundColor Green
        Write-Host 'Ctrl+C 로 종료' -ForegroundColor DarkGray
        Write-Host ''
        & $MosquittoSub -t "ship/$ship/#" -v
    }

    'detect' {
        # 추가 인자는 $args 로 그대로 넘어간다:
        #   detect --no-solution   조준 해 없음      -> NO_SOLUTION
        #   detect --bad-angle     범위 밖 각도      -> OUT_OF_RANGE
        #   detect --bad-profile   미등록 프로파일    -> OUT_OF_RANGE
        #   detect --stale         묵은 해           -> OUT_OF_RANGE
        python tools\fake_jetson.py --ship-id (Get-ShipId) @args
    }

    'kiosk' {
        $ship = Get-ShipId

        # 계약을 먼저 뽑는다. 키오스크가 이걸 읽어 토픽·유효명령을 채운다.
        # 손으로 복제하면 갈라지므로 파이썬을 정본으로 둔다.
        python -m floaq.contracts -o tools\contract.json

        # ⚠ file:// 로 열면 fetch 가 막혀 contract.json 을 못 읽는다. http 로 띄운다.
        Write-Host "SHIP_ID  $ship" -ForegroundColor Green
        Write-Host 'http://localhost:8765/kiosk.html' -ForegroundColor Green
        Write-Host 'Ctrl+C 로 종료' -ForegroundColor DarkGray
        Write-Host ''
        Start-Process 'http://localhost:8765/kiosk.html'
        Set-Location (Join-Path $Root 'tools')
        python -m http.server 8765
    }

    'lora-b' {
        # LoRa 수신기 역할. 먼저 띄운다. 라디오 없이 UDP 로 돈다.
        # 실물이 오면:  .\scripts\dev.ps1 lora-b --link serial --port COM3
        Write-Host 'LoRa B(Pi 역할) 수신 대기' -ForegroundColor Green
        Write-Host 'Ctrl+C 로 종료' -ForegroundColor DarkGray
        Write-Host ''
        python -u tools\lora_ab.py b @args
    }

    'lora-a' {
        # LoRa 송신기 역할(부표). --drop 0.2 로 유실을 흉내낼 수 있다.
        Write-Host 'LoRa A(부표 역할) 송신' -ForegroundColor Green
        Write-Host 'Ctrl+C 로 종료' -ForegroundColor DarkGray
        Write-Host ''
        python -u tools\lora_ab.py a @args
    }

    'distress' {
        # 조난 신고를 UDP 로 내보낸다. OpenCPN 등에서 확인용.
        #   OpenCPN: Options > Connections > Add > Network > UDP, 0.0.0.0 : 10110
        # ⚠ 실제 조난 신고가 아니다. 목적지를 확인할 것.
        Write-Host '조난 신고 UDP 송출 (시뮬레이션)' -ForegroundColor Yellow
        Write-Host 'OpenCPN: Options > Connections > Network > UDP, 0.0.0.0 : 10110' -ForegroundColor DarkGray
        Write-Host ''
        python -u tools\distress_send.py @args
    }

    'status' { Show-Status }

    'stop' {
        Invoke-Stop
        Write-Host '종료 완료' -ForegroundColor Green
    }

    default {
        Write-Host ''
        Write-Host 'FloaQ Pi 개발 스크립트'
        Write-Host ''
        Write-Host '  .\scripts\dev.ps1 reset     전부 지운다. 등록부터 다시'
        Write-Host '  .\scripts\dev.ps1 broker    mosquitto 기동        (별도 창)'
        Write-Host '  .\scripts\dev.ps1 pi        오케스트레이터 기동    (별도 창)'
        Write-Host '  .\scripts\dev.ps1 sub       메시지 덤프           (별도 창)'
        Write-Host '  .\scripts\dev.ps1 kiosk     키오스크 + 웹서버      (별도 창)'
        Write-Host '  .\scripts\dev.ps1 detect    가짜 탐지 1회'
        Write-Host '  .\scripts\dev.ps1 lora-b    LoRa 수신 검증      (별도 창, 먼저 띄움)'
        Write-Host '  .\scripts\dev.ps1 lora-a    LoRa 송신 검증      (별도 창)'
        Write-Host '  .\scripts\dev.ps1 distress  조난 신고 UDP 송출   (DSC + AIS)'
        Write-Host '  .\scripts\dev.ps1 status    상태 확인'
        Write-Host '  .\scripts\dev.ps1 stop      전부 종료'
        Write-Host ''
        Write-Host '처음이면:  broker -> pi(등록 모드) -> POST /api/ship -> kiosk -> detect'
        Write-Host ''
    }
}
