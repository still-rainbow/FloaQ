from __future__ import annotations

import argparse

from ultralytics import YOLO

from .utils import load_config


def predict(config_path: str, weights: str, source: str) -> None:
    config = load_config(config_path)
    model = YOLO(weights)
    model.predict(
        source=source,
        imgsz=int(config.get("imgsz", 640)),
        conf=float(config.get("conf", 0.25)),
        iou=float(config.get("iou", 0.7)),
        device=config.get("device", 0),
        save=True,
        project="outputs",
        name=config.get("name", "baseline"),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run person/animal/float detection inference.")
    parser.add_argument("--config", default="configs/baseline.yaml")
    parser.add_argument("--weights", required=True)
    parser.add_argument("--source", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    predict(args.config, args.weights, args.source)
