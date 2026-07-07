from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REQUIRED_TASK_KEYS = frozenset({"id", "prompt", "image", "seed"})


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    prompt: str
    image: str
    seed: int

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def load_tasks(path: Path) -> tuple[TaskDefinition, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array")

    tasks: list[TaskDefinition] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"task[{index}] must be an object")

        keys = set(item)
        missing = REQUIRED_TASK_KEYS - keys
        unknown = keys - REQUIRED_TASK_KEYS
        if missing:
            raise ValueError(f"task[{index}] missing required field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"task[{index}] contains unknown field(s): {', '.join(sorted(unknown))}")

        task = TaskDefinition(
            id=_required_string(item["id"], f"task[{index}].id"),
            prompt=_required_string(item["prompt"], f"task[{index}].prompt"),
            image=_required_string(item["image"], f"task[{index}].image"),
            seed=_required_int(item["seed"], f"task[{index}].seed"),
        )
        if task.id in seen_ids:
            raise ValueError(f"duplicate task id: {task.id}")
        seen_ids.add(task.id)
        tasks.append(task)
    return tuple(tasks)


def write_tasks(path: Path, tasks: tuple[TaskDefinition, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([task.to_json() for task in tasks], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _required_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value
