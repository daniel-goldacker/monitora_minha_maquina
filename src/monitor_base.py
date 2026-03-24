#!/usr/bin/env python3
"""Tipos, configuracao e utilitarios basicos do monitor."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

FIELDNAMES: Tuple[str, ...] = (
    "timestamp",
    "hostname",
    "cpu_usage_percent",
    "mem_total_gb",
    "mem_used_gb",
    "mem_available_gb",
    "mem_usage_percent",
    "swap_total_gb",
    "swap_used_gb",
    "swap_free_gb",
    "swap_usage_percent",
    "disk_path",
    "disk_total_gb",
    "disk_used_gb",
    "disk_available_gb",
    "disk_usage_percent",
    "load_1m",
    "load_5m",
    "load_15m",
    "cpu_cores",
    "process_count",
    "top_cpu_processes_json",
    "top_mem_processes_json",
)

NUMERIC_FIELDS = {
    "cpu_usage_percent",
    "mem_total_gb",
    "mem_used_gb",
    "mem_available_gb",
    "mem_usage_percent",
    "swap_total_gb",
    "swap_used_gb",
    "swap_free_gb",
    "swap_usage_percent",
    "disk_total_gb",
    "disk_used_gb",
    "disk_available_gb",
    "disk_usage_percent",
    "load_1m",
    "load_5m",
    "load_15m",
    "cpu_cores",
    "process_count",
}


@dataclass(frozen=True)
class MonitorConfig:
    interval: float
    cpu_sample: float
    disk_path: str
    output_dir: Path
    cpu_threshold: float
    mem_threshold: float
    disk_threshold: float
    swap_threshold: float
    min_available_mem_gb: float
    min_available_disk_gb: float
    samples: int


@dataclass(frozen=True)
class CpuSnapshot:
    idle: int
    total: int


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def bytes_to_gb(value: int) -> float:
    return round(value / (1024**3), 2)


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("O valor deve ser maior que zero.")
    return parsed


def percent_float(value: str) -> float:
    parsed = float(value)
    if not 0 < parsed <= 100:
        raise argparse.ArgumentTypeError("O percentual deve estar entre 0 e 100.")
    return parsed


def default_disk_path() -> str:
    if os.name != "nt":
        return "/"
    return os.environ.get("SystemDrive", "C:") + "\\"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Monitora recursos da maquina e gera logs comprobatarios."
    )
    parser.add_argument("--interval", type=positive_float, default=60.0, help="Intervalo em segundos entre cada coleta. Padrao: 60")
    parser.add_argument("--cpu-sample", type=positive_float, default=1.0, help="Janela em segundos usada para medir CPU em cada coleta. Padrao: 1")
    parser.add_argument(
        "--disk-path",
        default=default_disk_path(),
        help="Caminho do sistema de arquivos a ser monitorado. Padrao: raiz do sistema.",
    )
    parser.add_argument("--output-dir", default="logs_monitoramento", help="Diretorio onde os logs serao gravados. Padrao: logs_monitoramento")
    parser.add_argument("--cpu-threshold", type=percent_float, default=85.0, help="Percentual de uso de CPU para alerta. Padrao: 85")
    parser.add_argument("--mem-threshold", type=percent_float, default=85.0, help="Percentual de uso de memoria para alerta. Padrao: 85")
    parser.add_argument("--disk-threshold", type=percent_float, default=85.0, help="Percentual de uso de disco para alerta. Padrao: 85")
    parser.add_argument("--swap-threshold", type=percent_float, default=20.0, help="Percentual de uso de swap para alerta. Padrao: 20")
    parser.add_argument("--min-available-mem-gb", type=float, default=2.0, help="Memoria minima disponivel em GB para alerta. Padrao: 2")
    parser.add_argument("--min-available-disk-gb", type=float, default=10.0, help="Espaco minimo disponivel em GB para alerta. Padrao: 10")
    parser.add_argument("--samples", type=int, default=0, help="Quantidade de coletas antes de encerrar. Use 0 para rodar continuamente.")
    return parser


def parse_config() -> MonitorConfig:
    args = build_parser().parse_args()
    return MonitorConfig(
        interval=args.interval,
        cpu_sample=args.cpu_sample,
        disk_path=args.disk_path,
        output_dir=Path(args.output_dir),
        cpu_threshold=args.cpu_threshold,
        mem_threshold=args.mem_threshold,
        disk_threshold=args.disk_threshold,
        swap_threshold=args.swap_threshold,
        min_available_mem_gb=args.min_available_mem_gb,
        min_available_disk_gb=args.min_available_disk_gb,
        samples=args.samples,
    )
