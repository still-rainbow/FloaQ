from __future__ import annotations

import argparse

from ultralytics import YOLO

from .dataset import validate_dataset_config
from .utils import load_config


def evaluate(config_path: str, weights: str) -> None:
    config = load_config(config_path)
    model = YOLO(weights)
    model.val(
        data=validate_dataset_config(config["data"]),
        split=config.get("split", "val"),
        imgsz=int(config.get("imgsz", 640)),
        batch=config.get("batch", 16),
        device=config.get("device", 0),
        project=config.get("project", "experiments"),
        name=f"{config.get('name', 'baseline')}_evaluation",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate detection weights with person as the primary target.")
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--weights", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    evaluate(args.config, args.weights)
