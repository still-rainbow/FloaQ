from __future__ import annotations

from pathlib import Path
from typing import Any


def validate_dataset_config(data: str | Path) -> str:
    """Validate local dataset YAML paths while allowing Ultralytics dataset names."""
    value = str(data)
    if value.lower().endswith(('.yaml', '.yml')) and not Path(value).is_file():
        raise FileNotFoundError(f"Dataset YAML not found: {value}")
    return value


def dataset_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": config.get("data"),
        "class_names": config.get("class_names", ["person", "animal", "float"]),
        "primary_target_class": config.get("primary_target_class", "person"),
        "split": config.get("split", "val"),
    }
