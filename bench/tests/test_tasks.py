import json
from pathlib import Path

import pytest

from bench_harness.tasks import TaskDefinition, load_tasks


def test_load_tasks_rejects_missing_required_fields(tmp_path: Path) -> None:
    task_file = tmp_path / "tasks.json"
    task_file.write_text(json.dumps([{"id": "apple", "prompt": "red apple", "image": "references/apple.png"}]))

    with pytest.raises(ValueError, match="seed"):
        load_tasks(task_file)


def test_load_tasks_rejects_unknown_fields(tmp_path: Path) -> None:
    task_file = tmp_path / "tasks.json"
    task_file.write_text(
        json.dumps(
            [
                {
                    "id": "apple",
                    "prompt": "red apple",
                    "image": "references/apple.png",
                    "seed": 20260708,
                    "probe": "not part of runner contract",
                }
            ]
        )
    )

    with pytest.raises(ValueError, match="probe"):
        load_tasks(task_file)


def test_repository_tasks_match_runner_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    tasks = load_tasks(repo_root / "tasks" / "tasks.json")

    assert len(tasks) == 20
    assert tasks[0] == TaskDefinition(
        id="cartoon-apple",
        prompt="A stylized cartoon red apple with a green leaf on the stem, smooth glossy surface",
        image="references/cartoon-apple.png",
        seed=20260708,
    )
    assert {task.id for task in tasks} == {
        "arcade-cabinet",
        "cartoon-apple",
        "chained-anchor",
        "chrome-espresso-machine",
        "crusty-bread-loaf",
        "fluffy-monster-plush",
        "forest-goblin-creature",
        "medieval-longsword",
        "modular-dungeon-gate",
        "old-oak-tree",
        "ornate-treasure-chest",
        "plasma-rifle",
        "potted-monstera",
        "rusty-pickup-truck",
        "scifi-supply-crate",
        "stained-glass-lantern",
        "stylized-hover-bike",
        "toon-knight-character",
        "victorian-street-lamp",
        "wooden-rocking-chair",
    }
