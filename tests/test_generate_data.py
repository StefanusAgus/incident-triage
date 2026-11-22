"""Dataset contract and standalone reproducibility checks."""

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data.generate_data import generate_incidents


@pytest.mark.parametrize("num_sample", [0, 1, 25, 300, 301])
def test_incidents_match_assignment_contract(num_sample: int) -> None:
    incidents = generate_incidents(num_sample=num_sample)
    fields = {
        "id", "created_at", "environment", "service", "severity", "title",
        "description", "resolution_summary", "tags",
    }
    assert len(incidents) == num_sample
    assert len({incident["id"] for incident in incidents}) == num_sample
    assert [incident["id"] for incident in incidents] == [
        f"INC-{index:04d}" for index in range(1, num_sample + 1)
    ]
    for incident in incidents:
        assert set(incident) == fields
        for field in fields - {"tags"}:
            assert isinstance(incident[field], str) and incident[field].strip()
        assert incident["environment"] in {"dev", "qa", "stage", "prod"}
        assert incident["severity"] in {"SEV1", "SEV2", "SEV3", "SEV4"}
        assert incident["created_at"].endswith("Z")
        created_at = datetime.fromisoformat(incident["created_at"])
        assert datetime(2026, 1, 1, tzinfo=timezone.utc) <= created_at
        assert created_at < datetime(2026, 7, 1, tzinfo=timezone.utc)
        assert isinstance(incident["tags"], list) and incident["tags"]
        assert all(isinstance(tag, str) and tag.strip() for tag in incident["tags"])


@pytest.mark.parametrize("num_sample", [0, 17, 300])
def test_standalone_script_writes_identical_json_on_repeated_runs(
    tmp_path: Path, num_sample: int,
) -> None:
    # Copy only the script: it must not depend on app imports, installed packages,
    # or the working directory. Run from the parent of the output directory.
    script_dir = tmp_path / "data"
    script_dir.mkdir()
    script = script_dir / "generate_data.py"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "data" / script.name, script)
    command = [sys.executable, str(script), "--num-sample", str(num_sample)]
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True, text=True)
    output = script_dir / "incidents.json"
    first_run = output.read_bytes()
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True, text=True)
    assert output.read_bytes() == first_run
    records = json.loads(first_run)
    assert len(records) == num_sample
    assert records == generate_incidents(num_sample=num_sample)


def test_negative_sample_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="num_sample must be non-negative"):
        generate_incidents(num_sample=-1)
