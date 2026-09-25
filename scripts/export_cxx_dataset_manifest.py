#!/usr/bin/env python3
"""Create a normalized, lossless inventory of the bundled CXXCrafter datasets."""

from __future__ import annotations

import csv
from pathlib import Path

import yaml


WORKSPACE = Path(__file__).resolve().parents[2]
CXX_DATA = WORKSPACE / "CXXCrafter-Community-Edition" / "data"
OUTPUT = Path(__file__).resolve().parents[1] / "cxx_dataset_manifest.csv"
PROJECTS_YAML = Path(__file__).resolve().parents[1] / "projects.yaml"
LANGUAGE_COMPATIBLE_OUTPUT = Path(__file__).resolve().parents[1] / "projects_cxx_compatible.yaml"
OVERLAP_OUTPUT = Path(__file__).resolve().parents[1] / "projects_cxx_overlap.yaml"
LOCAL_OVERLAP_OUTPUT = Path(__file__).resolve().parents[1] / "projects_cxx_overlap_local.yaml"
INITIAL_BUILD_OUTPUT = Path(__file__).resolve().parents[1] / "cxx_initial_build_projects.yaml"
SMOKE_TEST_OUTPUT = Path(__file__).resolve().parents[1] / "cxx_initial_build_smoke.yaml"

SOURCES = (
    ("top100", CXX_DATA / "top100_dataset.csv", "git_url"),
    ("awesome_cpp", CXX_DATA / "awesome_cpp_dataset.csv", "local_relative_path"),
)


def main() -> None:
    records: list[dict[str, str]] = []
    for dataset, source_file, source_kind in SOURCES:
        with source_file.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                source = row["path"].strip()
                if source_kind == "git_url":
                    availability = "cloneable_url"
                    suggested_mode = "initial_build"
                else:
                    availability = (
                        "local_source_present"
                        if (CXX_DATA.parent / source).is_dir()
                        else "source_not_bundled"
                    )
                    suggested_mode = (
                        "initial_build" if availability == "local_source_present" else "requires_source_acquisition"
                    )
                records.append(
                    {
                        "dataset": dataset,
                        "project_name": row["project_name"].strip(),
                        "source": source,
                        "source_kind": source_kind,
                        "source_availability": availability,
                        "suggested_fix_build_mode": suggested_mode,
                    }
                )

    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    # A record can be replayed by the existing OSS-Fuzz mode only when the
    # project also appears in BuildFixBench.  Top100 is matched by canonical
    # repository URL; Awesome C++ has no URLs in this release, so it is
    # matched by its published project name.
    def canonical_url(value: str) -> str:
        return value.lower().rstrip("/").removesuffix(".git").replace("git://", "https://")

    buildfix_entries = yaml.safe_load(PROJECTS_YAML.read_text(encoding="utf-8"))
    # CXXCrafter applies to C and C++ projects. This is the primary cohort:
    # method applicability follows the language, not CSV membership.
    language_compatible = []
    for entry in buildfix_entries:
        if str(entry.get("language", "")).strip().lower() in {"c", "c++"}:
            copied = dict(entry)
            copied["cxx_method_compatible"] = True
            language_compatible.append(copied)
    with LANGUAGE_COMPATIBLE_OUTPUT.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(language_compatible, handle, sort_keys=False, allow_unicode=True)
    top100_by_url = {
        canonical_url(row["source"]): row
        for row in records if row["dataset"] == "top100"
    }
    awesome_by_name = {
        row["project_name"].lower(): row
        for row in records if row["dataset"] == "awesome_cpp"
    }
    overlap: list[dict] = []
    for entry in buildfix_entries:
        memberships: list[dict] = []
        matched_top100 = top100_by_url.get(canonical_url(entry.get("software_repo_url", "")))
        if matched_top100:
            memberships.append({"dataset": "top100", "source": matched_top100["source"]})
        matched_awesome = awesome_by_name.get(str(entry.get("project", "")).lower())
        if matched_awesome:
            memberships.append({"dataset": "awesome_cpp", "source": matched_awesome["source"]})
        if memberships:
            copied = dict(entry)
            copied["cxx_membership"] = memberships
            overlap.append(copied)

    with OVERLAP_OUTPUT.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(overlap, handle, sort_keys=False, allow_unicode=True)

    def has_local_log(entry: dict) -> bool:
        year, month, day = str(entry["error_time"]).split("-")
        log_name = f"{year}_{int(month)}_{int(day)} error.txt"
        return (Path(__file__).resolve().parents[1] / "build_error_log" / entry["project"] / log_name).is_file()

    local_overlap = [entry for entry in overlap if has_local_log(entry)]
    with LOCAL_OVERLAP_OUTPUT.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(local_overlap, handle, sort_keys=False, allow_unicode=True)

    # This is the directly runnable initial-build cohort: Top100 supplies a
    # clone URL for every row.  Keep duplicate rows deliberately, because they
    # occur in the source benchmark and must remain auditable.
    initial_build = [
        {
            "project": row["project_name"],
            "source_repo_url": row["source"],
            "mode": "initial_build",
            "fixed_state": "no",
            "state": "no",
        }
        for row in records if row["dataset"] == "top100"
    ]
    with INITIAL_BUILD_OUTPUT.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(initial_build, handle, sort_keys=False, allow_unicode=True)

    # Both were validated by the CXXCrafter release: 8cc and mold execute
    # `make test` successfully and have consistent build output. They cover a
    # small C project and a C++ project while keeping the first run economical.
    smoke_names = {"8cc", "mold"}
    smoke_test = [entry for entry in initial_build if entry["project"] in smoke_names]
    with SMOKE_TEST_OUTPUT.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(smoke_test, handle, sort_keys=False, allow_unicode=True)

    print(f"Wrote {len(records)} records to {OUTPUT}")
    print(f"Wrote {len(language_compatible)} C/C++ method-compatible BuildFix cases to {LANGUAGE_COMPATIBLE_OUTPUT}")
    print(f"Wrote {len(overlap)} existing OSS-Fuzz replay cases to {OVERLAP_OUTPUT}")
    print(f"Wrote {len(local_overlap)} locally cached replay cases to {LOCAL_OVERLAP_OUTPUT}")
    print(f"Wrote {len(initial_build)} directly cloneable initial-build cases to {INITIAL_BUILD_OUTPUT}")
    print(f"Wrote {len(smoke_test)} CXX-validated smoke-test cases to {SMOKE_TEST_OUTPUT}")


if __name__ == "__main__":
    main()
