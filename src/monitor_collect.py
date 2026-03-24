#!/usr/bin/env python3
"""Coletores de metricas de sistema."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import time
from ctypes import Structure, byref, c_ulong, c_ulonglong, sizeof
from typing import Dict, List

from monitor_base import CpuSnapshot, MonitorConfig, bytes_to_gb, now_iso

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None


if os.name == "nt":
    class FILETIME(Structure):
        _fields_ = [("dwLowDateTime", c_ulong), ("dwHighDateTime", c_ulong)]


    class MEMORYSTATUSEX(Structure):
        _fields_ = [
            ("dwLength", c_ulong),
            ("dwMemoryLoad", c_ulong),
            ("ullTotalPhys", c_ulonglong),
            ("ullAvailPhys", c_ulonglong),
            ("ullTotalPageFile", c_ulonglong),
            ("ullAvailPageFile", c_ulonglong),
            ("ullTotalVirtual", c_ulonglong),
            ("ullAvailVirtual", c_ulonglong),
            ("ullAvailExtendedVirtual", c_ulonglong),
        ]


def read_cpu_snapshot() -> CpuSnapshot:
    with open("/proc/stat", "r", encoding="utf-8") as proc_stat:
        parts = proc_stat.readline().strip().split()

    if not parts or parts[0] != "cpu":
        raise RuntimeError("Nao foi possivel ler /proc/stat para medir CPU.")

    values = [int(value) for value in parts[1:]]
    return CpuSnapshot(idle=values[3] + values[4], total=sum(values))


def read_windows_cpu_snapshot() -> CpuSnapshot:
    idle_time = FILETIME()
    kernel_time = FILETIME()
    user_time = FILETIME()
    if ctypes.windll.kernel32.GetSystemTimes(byref(idle_time), byref(kernel_time), byref(user_time)) == 0:
        raise RuntimeError("Nao foi possivel ler contadores de CPU no Windows.")

    def to_int(filetime: FILETIME) -> int:
        return (filetime.dwHighDateTime << 32) | filetime.dwLowDateTime

    idle = to_int(idle_time)
    kernel = to_int(kernel_time)
    user = to_int(user_time)
    total = kernel + user
    return CpuSnapshot(idle=idle, total=total)


def calculate_cpu_usage(interval_seconds: float) -> float:
    if psutil:
        return round(psutil.cpu_percent(interval=interval_seconds), 2)

    if os.name == "nt":
        start = read_windows_cpu_snapshot()
        time.sleep(interval_seconds)
        end = read_windows_cpu_snapshot()
        total_delta = end.total - start.total
        idle_delta = end.idle - start.idle
        if total_delta <= 0:
            return 0.0
        usage = 1 - (idle_delta / total_delta)
        return round(max(0.0, min(100.0, usage * 100)), 2)

    start = read_cpu_snapshot()
    time.sleep(interval_seconds)
    end = read_cpu_snapshot()

    total_delta = end.total - start.total
    idle_delta = end.idle - start.idle
    if total_delta <= 0:
        return 0.0

    usage = 1 - (idle_delta / total_delta)
    return round(max(0.0, min(100.0, usage * 100)), 2)


def read_meminfo() -> Dict[str, int]:
    meminfo: Dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as meminfo_file:
        for line in meminfo_file:
            key, raw_value = line.split(":", 1)
            meminfo[key] = int(raw_value.strip().split()[0]) * 1024
    return meminfo


def collect_memory_metrics() -> Dict[str, float]:
    if psutil:
        vm = psutil.virtual_memory()
        return {
            "mem_total_gb": bytes_to_gb(int(vm.total)),
            "mem_used_gb": bytes_to_gb(int(vm.used)),
            "mem_available_gb": bytes_to_gb(int(vm.available)),
            "mem_usage_percent": round(float(vm.percent), 2),
        }

    if os.name == "nt":
        status = MEMORYSTATUSEX()
        status.dwLength = sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(status)) == 0:
            raise RuntimeError("Nao foi possivel ler memoria no Windows.")
        total = int(status.ullTotalPhys)
        available = int(status.ullAvailPhys)
        used = max(0, total - available)
        usage_percent = (used / total * 100) if total else 0.0
        return {
            "mem_total_gb": bytes_to_gb(total),
            "mem_used_gb": bytes_to_gb(used),
            "mem_available_gb": bytes_to_gb(available),
            "mem_usage_percent": round(usage_percent, 2),
        }

    meminfo = read_meminfo()
    total = meminfo["MemTotal"]
    available = meminfo.get("MemAvailable", 0)
    used = max(0, total - available)
    usage_percent = (used / total * 100) if total else 0.0
    return {
        "mem_total_gb": bytes_to_gb(total),
        "mem_used_gb": bytes_to_gb(used),
        "mem_available_gb": bytes_to_gb(available),
        "mem_usage_percent": round(usage_percent, 2),
    }


def collect_swap_metrics() -> Dict[str, float]:
    if psutil:
        swap = psutil.swap_memory()
        return {
            "swap_total_gb": bytes_to_gb(int(swap.total)),
            "swap_used_gb": bytes_to_gb(int(swap.used)),
            "swap_free_gb": bytes_to_gb(int(swap.free)),
            "swap_usage_percent": round(float(swap.percent), 2),
        }

    if os.name == "nt":
        status = MEMORYSTATUSEX()
        status.dwLength = sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(status)) == 0:
            raise RuntimeError("Nao foi possivel ler swap no Windows.")
        total = int(status.ullTotalPageFile)
        free = int(status.ullAvailPageFile)
        used = max(0, total - free)
        usage_percent = (used / total * 100) if total else 0.0
        return {
            "swap_total_gb": bytes_to_gb(total),
            "swap_used_gb": bytes_to_gb(used),
            "swap_free_gb": bytes_to_gb(free),
            "swap_usage_percent": round(usage_percent, 2),
        }

    meminfo = read_meminfo()
    total = meminfo.get("SwapTotal", 0)
    free = meminfo.get("SwapFree", 0)
    used = max(0, total - free)
    usage_percent = (used / total * 100) if total else 0.0
    return {
        "swap_total_gb": bytes_to_gb(total),
        "swap_used_gb": bytes_to_gb(used),
        "swap_free_gb": bytes_to_gb(free),
        "swap_usage_percent": round(usage_percent, 2),
    }


def collect_disk_metrics(path: str) -> Dict[str, float]:
    usage = shutil.disk_usage(path)
    used = usage.total - usage.free
    usage_percent = (used / usage.total * 100) if usage.total else 0.0
    return {
        "disk_path": path,
        "disk_total_gb": bytes_to_gb(usage.total),
        "disk_used_gb": bytes_to_gb(used),
        "disk_available_gb": bytes_to_gb(usage.free),
        "disk_usage_percent": round(usage_percent, 2),
    }


def collect_load_average() -> Dict[str, float]:
    if hasattr(os, "getloadavg"):
        try:
            load_1, load_5, load_15 = os.getloadavg()
        except OSError:
            load_1, load_5, load_15 = 0.0, 0.0, 0.0
    else:
        load_1, load_5, load_15 = 0.0, 0.0, 0.0
    return {
        "load_1m": round(load_1, 2),
        "load_5m": round(load_5, 2),
        "load_15m": round(load_15, 2),
        "cpu_cores": os.cpu_count() or 1,
    }


def get_windows_total_memory_bytes() -> int:
    if os.name != "nt":
        return 1
    status = MEMORYSTATUSEX()
    status.dwLength = sizeof(MEMORYSTATUSEX)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(status)) == 0:
        return 1
    return max(1, int(status.ullTotalPhys))


def list_windows_process_snapshot() -> Dict[int, Dict[str, float | int | str]]:
    ps_command = (
        "$ErrorActionPreference='Stop'; "
        "Get-Process | Select-Object Id,ProcessName,CPU,WorkingSet64 | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_command],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = result.stdout.strip()
    if not raw:
        return {}

    parsed = json.loads(raw)
    entries = parsed if isinstance(parsed, list) else [parsed]
    snapshot: Dict[int, Dict[str, float | int | str]] = {}

    for item in entries:
        if not isinstance(item, dict):
            continue
        pid = int(item.get("Id", 0) or 0)
        if pid <= 0:
            continue
        snapshot[pid] = {
            "command": str(item.get("ProcessName", "-")),
            "cpu_seconds": float(item.get("CPU", 0.0) or 0.0),
            "working_set": int(item.get("WorkingSet64", 0) or 0),
        }
    return snapshot


def collect_process_metrics_windows(limit: int) -> Dict[str, object]:
    process_count = 0
    top_cpu_processes: List[Dict[str, object]] = []
    top_mem_processes: List[Dict[str, object]] = []
    ignored_pids = {os.getpid(), os.getppid()}
    ignored_commands = {"powershell", "pwsh"}

    try:
        sample_seconds = 0.25
        start = list_windows_process_snapshot()
        time.sleep(sample_seconds)
        end = list_windows_process_snapshot()
        if not end:
            return {
                "process_count": 0,
                "top_cpu_processes_json": "[]",
                "top_mem_processes_json": "[]",
            }

        process_count = len(end)
        total_mem = get_windows_total_memory_bytes()
        cpu_cores = max(1, os.cpu_count() or 1)
        collected: List[Dict[str, object]] = []

        for pid, current in end.items():
            command = str(current.get("command", "-"))
            if pid in ignored_pids or command.lower() in ignored_commands:
                continue

            current_cpu_seconds = float(current.get("cpu_seconds", 0.0) or 0.0)
            start_cpu_seconds = float(start.get(pid, {}).get("cpu_seconds", 0.0) or 0.0)
            cpu_delta = max(0.0, current_cpu_seconds - start_cpu_seconds)
            cpu_percent = (cpu_delta / sample_seconds) / cpu_cores * 100.0
            cpu_percent = max(0.0, min(100.0, cpu_percent))

            mem_bytes = int(current.get("working_set", 0) or 0)
            mem_percent = (mem_bytes / total_mem * 100.0) if total_mem else 0.0
            collected.append(
                {
                    "pid": pid,
                    "command": command,
                    "cpu_percent": round(cpu_percent, 2),
                    "mem_percent": round(mem_percent, 2),
                }
            )

        top_cpu_processes = sorted(collected, key=lambda item: float(item["cpu_percent"]), reverse=True)[:limit]
        top_mem_processes = sorted(collected, key=lambda item: float(item["mem_percent"]), reverse=True)[:limit]
    except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError, ValueError):
        pass

    return {
        "process_count": process_count,
        "top_cpu_processes_json": json.dumps(top_cpu_processes, ensure_ascii=True),
        "top_mem_processes_json": json.dumps(top_mem_processes, ensure_ascii=True),
    }


def collect_process_metrics(limit: int = 5) -> Dict[str, object]:
    if psutil:
        process_count = 0
        processes: List[Dict[str, object]] = []
        ignored_pids = {os.getpid(), os.getppid()}

        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                pid = int(info.get("pid", 0))
                if pid in ignored_pids:
                    continue
                processes.append(
                    {
                        "pid": pid,
                        "command": str(info.get("name", "-")),
                        "cpu_percent": round(float(info.get("cpu_percent") or 0.0), 2),
                        "mem_percent": round(float(info.get("memory_percent") or 0.0), 2),
                    }
                )
                process_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        top_cpu = sorted(processes, key=lambda item: float(item["cpu_percent"]), reverse=True)[:limit]
        top_mem = sorted(processes, key=lambda item: float(item["mem_percent"]), reverse=True)[:limit]
        return {
            "process_count": process_count,
            "top_cpu_processes_json": json.dumps(top_cpu, ensure_ascii=True),
            "top_mem_processes_json": json.dumps(top_mem, ensure_ascii=True),
        }

    if os.name == "nt":
        return collect_process_metrics_windows(limit)

    process_count = 0
    top_cpu_processes: List[Dict[str, object]] = []
    top_mem_processes: List[Dict[str, object]] = []
    ignored_pids = {os.getpid(), os.getppid()}
    ignored_commands = {"ps"}

    try:
        cpu_result = subprocess.run(
            ["ps", "-eo", "pid=,comm=,%cpu=,%mem=", "--sort=-%cpu"],
            capture_output=True,
            text=True,
            check=True,
        )
        mem_result = subprocess.run(
            ["ps", "-eo", "pid=,comm=,%cpu=,%mem=", "--sort=-%mem"],
            capture_output=True,
            text=True,
            check=True,
        )
        count_result = subprocess.run(
            ["ps", "-e", "--no-headers"],
            capture_output=True,
            text=True,
            check=True,
        )
        process_count = len([line for line in count_result.stdout.splitlines() if line.strip()])
        top_cpu_processes = parse_top_processes(cpu_result.stdout, limit, ignored_pids, ignored_commands)
        top_mem_processes = parse_top_processes(mem_result.stdout, limit, ignored_pids, ignored_commands)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return {
        "process_count": process_count,
        "top_cpu_processes_json": json.dumps(top_cpu_processes, ensure_ascii=True),
        "top_mem_processes_json": json.dumps(top_mem_processes, ensure_ascii=True),
    }


def parse_top_processes(
    output: str,
    limit: int,
    ignored_pids: set[int],
    ignored_commands: set[str],
) -> List[Dict[str, object]]:
    processes: List[Dict[str, object]] = []
    for line in output.splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = raw.split(None, 3)
        if len(parts) != 4:
            continue
        pid, command, cpu, mem = parts
        try:
            pid_value = int(pid)
            cpu_value = float(cpu)
            mem_value = float(mem)
        except ValueError:
            continue
        if pid_value in ignored_pids or command in ignored_commands:
            continue
        processes.append(
            {
                "pid": pid_value,
                "command": command,
                "cpu_percent": round(cpu_value, 2),
                "mem_percent": round(mem_value, 2),
            }
        )
        if len(processes) >= limit:
            break
    return processes


def collect_measurement(hostname: str, config: MonitorConfig) -> Dict[str, object]:
    row: Dict[str, object] = {
        "timestamp": now_iso(),
        "hostname": hostname,
        "cpu_usage_percent": calculate_cpu_usage(config.cpu_sample),
    }
    row.update(collect_memory_metrics())
    row.update(collect_swap_metrics())
    row.update(collect_disk_metrics(config.disk_path))
    row.update(collect_load_average())
    row.update(collect_process_metrics())
    return row
