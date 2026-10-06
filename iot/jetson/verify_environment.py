"""Jetson의 Python 및 GPU 환경을 확인합니다. 실패 시 종료 코드 1을 반환합니다."""

import platform
import sys
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    print(f"Python: {sys.version}")
    print(f"실행 파일: {sys.executable}")
    require(platform.system() == "Linux", "Jetson Linux에서 실행하세요.")
    require(platform.machine() == "aarch64", "aarch64 보드에서 실행하세요.")
    require(sys.version_info[:3] == (3, 10, 12), "팀 Python 기준은 3.10.12입니다.")
    require(sys.prefix != sys.base_prefix, "프로젝트 가상환경을 활성화하세요.")
    config = Path(sys.prefix, "pyvenv.cfg").read_text(encoding="utf-8")
    settings = dict(
        (key.strip().lower(), value.strip().lower())
        for line in config.splitlines()
        if "=" in line
        for key, value in [line.split("=", 1)]
    )
    require(
        settings.get("include-system-site-packages") == "true",
        "--system-site-packages로 가상환경을 생성하세요.",
    )

    import cv2
    import numpy
    import onnxruntime
    import tensorrt
    import torch
    import torchvision

    for module in (cv2, numpy, onnxruntime, tensorrt, torch, torchvision):
        print(f"{module.__name__}: {module.__version__} ({module.__file__})")

    require(torch.version.cuda is not None, "CUDA가 포함된 Jetson torch 빌드가 필요합니다.")
    require(torch.cuda.is_available(), "PyTorch CUDA를 사용할 수 없습니다.")
    value = torch.ones(1, device="cuda") + 1
    torch.cuda.synchronize()
    require(value.item() == 2, "CUDA 연산 검증에 실패했습니다.")
    print(f"GPU: {torch.cuda.get_device_name(0)} / torch CUDA: {torch.version.cuda}")

    providers = onnxruntime.get_available_providers()
    print(f"ONNX Runtime providers: {providers}")
    require(
        bool({"CUDAExecutionProvider", "TensorrtExecutionProvider"}.intersection(providers)),
        "ONNX Runtime에 GPU provider가 등록되지 않았습니다.",
    )
    print("기본 환경 검증 통과. 실제 모델의 GPU 추론은 별도로 검증하세요.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"환경 검증 실패: {error}", file=sys.stderr)
        sys.exit(1)
