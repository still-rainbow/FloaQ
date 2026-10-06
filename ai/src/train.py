from __future__ import annotations

import argparse

from ultralytics import YOLO

from .dataset import validate_dataset_config
from .utils import load_config, set_seed


def train(config_path: str) -> None:
    config = load_config(config_path)
    set_seed(int(config.get("seed", 42)))
    data = validate_dataset_config(config["data"])
    model = YOLO(config.get("model", "yolo11n.pt"))
    optional_keys = (
        "optimizer",
        "lr0",
        "lrf",
        "momentum",
        "weight_decay",
        "warmup_epochs",
        "warmup_momentum",
        "warmup_bias_lr",
        "mosaic",
        "mixup",
        "cutmix",
        "close_mosaic",
        "deterministic",
        "patience",
    )
    optional_args = {key: config[key] for key in optional_keys if key in config}
    model.train(
        data=data,
        epochs=int(config.get("epochs", 50)),
        imgsz=int(config.get("imgsz", 640)),
        batch=config.get("batch", 16),
        device=config.get("device", 0),
        workers=int(config.get("workers", 8)),
        project=config.get("project", "experiments"),
        name=config.get("name", "baseline"),
        exist_ok=bool(config.get("exist_ok", False)),
        seed=int(config.get("seed", 42)),
        **optional_args,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the person/animal/float detection baseline.")
    parser.add_argument("--config", default="configs/baseline.yaml")
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args().config)
