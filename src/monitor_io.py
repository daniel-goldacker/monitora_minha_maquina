#!/usr/bin/env python3
"""Persistencia e leitura dos artefatos de monitoramento."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List

from monitor_base import FIELDNAMES, NUMERIC_FIELDS


def ensure_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "alertas.log").touch(exist_ok=True)
    (output_dir / "execucao.log").touch(exist_ok=True)


def append_csv(csv_path: Path, row: Dict[str, object]) -> None:
    if not csv_path.exists():
        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
            writer.writeheader()

    with csv_path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
        writer.writerow(row)


def normalize_csv_schema(csv_path: Path) -> None:
    if not csv_path.exists():
        return

    with csv_path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file)
        header = next(reader, [])

    if tuple(header) == FIELDNAMES:
        return

    rows = load_rows(csv_path)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})


def append_jsonl(jsonl_path: Path, row: Dict[str, object]) -> None:
    with jsonl_path.open("a", encoding="utf-8") as jsonl_file:
        jsonl_file.write(json.dumps(row, ensure_ascii=True) + "\n")


def append_line(path: Path, message: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def load_rows(csv_path: Path) -> List[Dict[str, object]]:
    if not csv_path.exists():
        return []

    rows: List[Dict[str, object]] = []
    with csv_path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for raw_row in reader:
            row: Dict[str, object] = {}
            for key, value in raw_row.items():
                if key in NUMERIC_FIELDS:
                    row[key] = float(value) if value not in ("", None) else 0.0
                else:
                    row[key] = value
            rows.append(row)
    return rows


def count_non_empty_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())
