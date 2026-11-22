"""Dataset contract and standalone reproducibility checks."""

import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data.generate_data import FAMILIES, dataset_capacity, generate_incidents


@pytest.mark.parametrize("num_sample", [0, 1, 25, 300, 301, 500])
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


def test_narratives_are_unique_without_ids_dates_or_environment() -> None:
    records = generate_incidents(300)
    for fields in (
        ("title",), ("description",), ("resolution_summary",),
        ("title", "description", "resolution_summary"),
    ):
        fingerprints = {
            tuple(" ".join(record[field].casefold().split()) for field in fields)
            for record in records
        }
        assert len(fingerprints) == 300


def test_families_and_scenarios_have_balanced_coverage_and_matching_fixes() -> None:
    records = generate_incidents(300)
    scenario_lookup = {
        scenario.tag: (family, scenario)
        for family in FAMILIES for scenario in family.scenarios
    }
    counts = Counter(record["tags"][-1] for record in records)
    assert set(counts) == set(scenario_lookup)
    assert set(counts.values()) <= {8, 9}
    for family in FAMILIES:
        assert sum(counts[scenario.tag] for scenario in family.scenarios) == 25
    for record in records:
        family, scenario = scenario_lookup[record["tags"][-1]]
        assert record["service"] in family.services
        assert record["tags"] == [*family.tags, scenario.tag]
        assert scenario.symptom in record["description"]
        assert scenario.cause in record["description"]
        assert record["resolution_summary"].startswith(scenario.resolution)


def test_full_capacity_is_unique_and_larger_requests_fail_clearly() -> None:
    capacity = dataset_capacity()
    records = generate_incidents(capacity)
    assert len(records) == capacity
    assert len({record["title"] for record in records}) == capacity
    with pytest.raises(ValueError, match=f"available {capacity} unique balanced samples"):
        generate_incidents(capacity + 1)


def test_sample_prefix_is_stable_when_requesting_more_records() -> None:
    assert generate_incidents(25) == generate_incidents(300)[:25]


def test_cli_rejects_excess_capacity_without_creating_output(tmp_path: Path) -> None:
    script = tmp_path / "generate_data.py"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "data" / script.name, script)
    result = subprocess.run(
        [sys.executable, str(script), "--num-sample", str(dataset_capacity() + 1)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "unique balanced samples" in result.stderr
    assert not (tmp_path / "incidents.json").exists()
