#!/usr/bin/env python3
"""Monitor de recursos da maquina com geracao de logs e relatorio HTML."""

from __future__ import annotations

import html
import json
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Dict, List

from monitor_base import MonitorConfig, now_iso, parse_config
from monitor_collect import collect_measurement
from monitor_io import (
    append_csv,
    append_jsonl,
    append_line,
    count_non_empty_lines,
    ensure_output_dir,
    load_rows,
    normalize_csv_schema,
)

def evaluate_alerts(row: Dict[str, object], config: MonitorConfig) -> List[str]:
    alerts: List[str] = []
    timestamp = str(row["timestamp"])
    cpu = float(row["cpu_usage_percent"])
    mem = float(row["mem_usage_percent"])
    swap = float(row["swap_usage_percent"])
    disk = float(row["disk_usage_percent"])
    available_mem = float(row["mem_available_gb"])
    available_disk = float(row["disk_available_gb"])
    swap_used = float(row["swap_used_gb"])

    if cpu >= config.cpu_threshold:
        alerts.append(f"{timestamp} ALERTA CPU alta: uso={cpu:.2f}% limite={config.cpu_threshold:.2f}%")
    if mem >= config.mem_threshold:
        alerts.append(f"{timestamp} ALERTA memoria alta: uso={mem:.2f}% limite={config.mem_threshold:.2f}%")
    if swap > 0 and swap >= config.swap_threshold:
        alerts.append(
            f"{timestamp} ALERTA swap alta: uso={swap:.2f}% usado={swap_used:.2f}GB limite={config.swap_threshold:.2f}%"
        )
    if disk >= config.disk_threshold:
        alerts.append(f"{timestamp} ALERTA disco alto: uso={disk:.2f}% limite={config.disk_threshold:.2f}%")
    if available_mem <= config.min_available_mem_gb:
        alerts.append(
            f"{timestamp} ALERTA memoria livre baixa: disponivel={available_mem:.2f}GB "
            f"limite={config.min_available_mem_gb:.2f}GB"
        )
    if available_disk <= config.min_available_disk_gb:
        alerts.append(
            f"{timestamp} ALERTA disco livre baixo: disponivel={available_disk:.2f}GB "
            f"limite={config.min_available_disk_gb:.2f}GB"
        )
    return alerts


def metric_status(value: float, warning: float, critical: float) -> str:
    if value >= critical:
        return "critico"
    if value >= warning:
        return "atencao"
    return "ok"


def parse_processes(raw_json: object) -> List[Dict[str, object]]:
    if not raw_json:
        return []
    if isinstance(raw_json, list):
        return raw_json
    if isinstance(raw_json, str):
        try:
            parsed = json.loads(raw_json)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def count_threshold_occurrences(rows: List[Dict[str, object]], field: str, threshold: float) -> int:
    return sum(1 for row in rows if float(row.get(field, 0.0)) >= threshold)


def count_below_occurrences(rows: List[Dict[str, object]], field: str, threshold: float) -> int:
    return sum(1 for row in rows if float(row.get(field, 0.0)) <= threshold)


def percentage(part: int, total: int) -> float:
    return round((part / total * 100.0), 2) if total else 0.0


def build_replacement_assessment(rows: List[Dict[str, object]], alert_total: int, config: MonitorConfig) -> Dict[str, object]:
    total = len(rows)
    if total == 0:
        return {
            "status": "dados_insuficientes",
            "title": "Dados insuficientes para conclusão",
            "summary": "Não há amostras para justificar substituição ou manutenção.",
            "reasons": ["Execute o monitor por mais tempo para gerar histórico comparável."],
            "score": 0,
            "metrics": {},
        }

    latest = rows[-1]
    cpu_values = [float(row.get("cpu_usage_percent", 0.0)) for row in rows]
    mem_values = [float(row.get("mem_usage_percent", 0.0)) for row in rows]
    swap_values = [float(row.get("swap_usage_percent", 0.0)) for row in rows]
    disk_values = [float(row.get("disk_usage_percent", 0.0)) for row in rows]

    cpu_count = count_threshold_occurrences(rows, "cpu_usage_percent", config.cpu_threshold)
    mem_count = count_threshold_occurrences(rows, "mem_usage_percent", config.mem_threshold)
    swap_count = count_threshold_occurrences(rows, "swap_usage_percent", config.swap_threshold)
    disk_count = count_threshold_occurrences(rows, "disk_usage_percent", config.disk_threshold)
    low_mem_count = count_below_occurrences(rows, "mem_available_gb", config.min_available_mem_gb)
    low_disk_count = count_below_occurrences(rows, "disk_available_gb", config.min_available_disk_gb)

    cpu_rate = percentage(cpu_count, total)
    mem_rate = percentage(mem_count, total)
    swap_rate = percentage(swap_count, total)
    disk_rate = percentage(disk_count, total)
    low_mem_rate = percentage(low_mem_count, total)
    low_disk_rate = percentage(low_disk_count, total)

    reasons: List[str] = []
    score = 0

    if cpu_rate >= 30 or max(cpu_values) >= 95:
        score += 1
        reasons.append(
            f"CPU em faixa crítica em {cpu_rate:.2f}% das amostras (limite: {config.cpu_threshold:.2f}%)."
        )
    if mem_rate >= 30 or (sum(mem_values) / total) >= 85:
        score += 1
        reasons.append(
            f"Memória em alta recorrente: {mem_rate:.2f}% das amostras acima do limite ({config.mem_threshold:.2f}%)."
        )
    if swap_rate >= 30 or float(latest.get("swap_usage_percent", 0.0)) >= 50 or max(swap_values) >= 70:
        score += 1
        reasons.append(
            f"Uso de swap elevado/recorrente ({swap_rate:.2f}% das amostras), sinal de pressão de RAM."
        )
    if low_mem_rate >= 20:
        score += 1
        reasons.append(
            f"Memória livre abaixo do mínimo em {low_mem_rate:.2f}% das amostras ({config.min_available_mem_gb:.2f} GB)."
        )
    if disk_rate >= 20 or float(latest.get("disk_usage_percent", 0.0)) >= 90 or low_disk_rate >= 20:
        score += 1
        reasons.append("Disco próximo do limite operacional com recorrência de baixa disponibilidade.")
    if alert_total >= max(10, int(total * 0.5)):
        score += 1
        reasons.append(f"Volume de alertas elevado: {alert_total} eventos para {total} amostras.")

    if score >= 4:
        status = "substituicao_recomendada"
        title = "Substituição de máquina recomendada"
        summary = "Há evidências recorrentes de saturação de recursos com impacto potencial em desempenho e estabilidade."
    elif score >= 2:
        status = "upgrade_recomendado"
        title = "Upgrade de hardware recomendado"
        summary = "Os dados indicam gargalos relevantes. Upgrade de memória/CPU/disco e revisão de capacidade são recomendados."
    else:
        status = "monitorar"
        title = "Manter com monitoramento"
        summary = "Não há recorrência suficiente para justificar substituição imediata com base no período analisado."

    if not reasons:
        reasons.append("No período analisado, os limites configurados foram pouco acionados.")

    return {
        "status": status,
        "title": title,
        "summary": summary,
        "reasons": reasons,
        "score": score,
        "metrics": {
            "total_amostras": total,
            "alertas": alert_total,
            "cpu_rate": cpu_rate,
            "mem_rate": mem_rate,
            "swap_rate": swap_rate,
            "disk_rate": disk_rate,
            "low_mem_rate": low_mem_rate,
            "low_disk_rate": low_disk_rate,
            "cpu_max": round(max(cpu_values), 2),
            "mem_max": round(max(mem_values), 2),
            "swap_max": round(max(swap_values), 2),
            "disk_max": round(max(disk_values), 2),
        },
    }


def build_justification_text(rows: List[Dict[str, object]], alert_total: int, config: MonitorConfig) -> str:
    assessment = build_replacement_assessment(rows, alert_total, config)
    metrics = assessment.get("metrics", {})
    now = now_iso()
    start = str(rows[0]["timestamp"]) if rows else "-"
    end = str(rows[-1]["timestamp"]) if rows else "-"
    hostname = str(rows[-1].get("hostname", "-")) if rows else "-"
    lines = [
        "PARECER TECNICO PARA CAPACIDADE DE MAQUINA",
        f"Data de emissao: {now}",
        f"Hostname: {hostname}",
        f"Periodo analisado: {start} ate {end}",
        "",
        f"Conclusao: {assessment['title']}",
        f"Resumo: {assessment['summary']}",
        "",
        "Evidencias objetivas:",
    ]
    for reason in assessment["reasons"]:
        lines.append(f"- {reason}")

    if metrics:
        lines.extend(
            [
                "",
                "Indicadores consolidados:",
                f"- Total de amostras: {int(metrics['total_amostras'])}",
                f"- Total de alertas: {int(metrics['alertas'])}",
                f"- CPU acima do limite: {float(metrics['cpu_rate']):.2f}% das amostras (pico {float(metrics['cpu_max']):.2f}%)",
                f"- Memoria acima do limite: {float(metrics['mem_rate']):.2f}% das amostras (pico {float(metrics['mem_max']):.2f}%)",
                f"- Swap acima do limite: {float(metrics['swap_rate']):.2f}% das amostras (pico {float(metrics['swap_max']):.2f}%)",
                f"- Disco acima do limite: {float(metrics['disk_rate']):.2f}% das amostras (pico {float(metrics['disk_max']):.2f}%)",
                f"- Memoria livre abaixo do minimo: {float(metrics['low_mem_rate']):.2f}% das amostras",
                f"- Disco livre abaixo do minimo: {float(metrics['low_disk_rate']):.2f}% das amostras",
            ]
        )

    lines.extend(
        [
            "",
            "Parametros avaliados:",
            f"- CPU limite: {config.cpu_threshold:.2f}%",
            f"- Memoria limite: {config.mem_threshold:.2f}%",
            f"- Swap limite: {config.swap_threshold:.2f}%",
            f"- Disco limite: {config.disk_threshold:.2f}%",
            f"- Memoria livre minima: {config.min_available_mem_gb:.2f} GB",
            f"- Disco livre minimo: {config.min_available_disk_gb:.2f} GB",
        ]
    )
    return "\n".join(lines) + "\n"


def render_process_list(processes: List[Dict[str, object]], title: str) -> str:
    if not processes:
        return f"<div class='process-card'><h3>{html.escape(title)}</h3><p>Sem dados de processo.</p></div>"

    items_html = "\n".join(
        (
            "<li>"
            f"<strong>{html.escape(str(item.get('command', '-')))}</strong> "
            f"(PID {int(item.get('pid', 0))})"
            f"<span>CPU: {float(item.get('cpu_percent', 0.0)):.2f}% | Mem: {float(item.get('mem_percent', 0.0)):.2f}%</span>"
            "</li>"
        )
        for item in processes
    )
    return f"""
    <div class="process-card">
      <h3>{html.escape(title)}</h3>
      <ul class="process-list">{items_html}</ul>
    </div>
    """


def svg_line_chart(
    rows: List[Dict[str, object]],
    field: str,
    title: str,
    unit: str,
    color: str,
    max_value: float | None = None,
) -> str:
    width = 640
    height = 220
    padding = 28

    if not rows:
        return f"<section class='chart-card'><h3>{html.escape(title)}</h3><p>Sem dados.</p></section>"

    values = [float(row[field]) for row in rows]
    max_data = max(values)
    upper_bound = max(max_value if max_value is not None else max_data * 1.15, 1.0)

    if len(values) == 1:
        polyline_points = f"{width / 2:.2f},{height - padding:.2f}"
    else:
        x_step = (width - 2 * padding) / (len(values) - 1)
        coordinates = []
        for index, value in enumerate(values):
            x = padding + index * x_step
            y = height - padding - (value / upper_bound) * (height - 2 * padding)
            coordinates.append(f"{x:.2f},{y:.2f}")
        polyline_points = " ".join(coordinates)

    latest = values[-1]
    average = sum(values) / len(values)
    return f"""
    <section class="chart-card">
      <div class="chart-header">
        <h3>{html.escape(title)}</h3>
        <div class="chart-meta">Atual: {latest:.2f}{html.escape(unit)} | Média: {average:.2f}{html.escape(unit)} | Pico: {max_data:.2f}{html.escape(unit)}</div>
      </div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">
        <line x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}" class="axis" />
        <line x1="{padding}" y1="{padding}" x2="{padding}" y2="{height - padding}" class="axis" />
        <polyline fill="none" stroke="{color}" stroke-width="3" points="{polyline_points}" />
      </svg>
    </section>
    """


def build_html_report(rows: List[Dict[str, object]], alert_total: int, config: MonitorConfig) -> str:
    latest = rows[-1] if rows else {}
    assessment = build_replacement_assessment(rows, alert_total, config)
    assessment_title = html.escape(str(assessment["title"]))
    assessment_summary = html.escape(str(assessment["summary"]))
    assessment_reasons_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in assessment["reasons"])
    assessment_status = str(assessment["status"])
    status_class_map = {
        "substituicao_recomendada": "critico",
        "upgrade_recomendado": "atencao",
        "monitorar": "ok",
        "dados_insuficientes": "atencao",
    }
    assessment_css_class = status_class_map.get(assessment_status, "ok")
    assessment_metrics = assessment.get("metrics", {})

    hostname = html.escape(str(latest.get("hostname", "-")))
    disk_path = html.escape(str(latest.get("disk_path", config.disk_path)))
    period_start = html.escape(str(rows[0]["timestamp"])) if rows else "-"
    period_end = html.escape(str(rows[-1]["timestamp"])) if rows else "-"
    mem_total = float(latest.get("mem_total_gb", 0.0))
    swap_total = float(latest.get("swap_total_gb", 0.0))
    disk_total = float(latest.get("disk_total_gb", 0.0))

    cpu_values = [float(row["cpu_usage_percent"]) for row in rows] or [0.0]
    mem_values = [float(row["mem_usage_percent"]) for row in rows] or [0.0]
    swap_values = [float(row["swap_usage_percent"]) for row in rows] or [0.0]
    disk_values = [float(row["disk_usage_percent"]) for row in rows] or [0.0]
    top_cpu_processes = parse_processes(latest.get("top_cpu_processes_json"))
    top_mem_processes = parse_processes(latest.get("top_mem_processes_json"))

    cards = [
        (
            "CPU atual",
            f"{float(latest.get('cpu_usage_percent', 0.0)):.2f}%",
            f"Pico: {max(cpu_values):.2f}% | Média: {sum(cpu_values) / len(cpu_values):.2f}%",
            metric_status(float(latest.get("cpu_usage_percent", 0.0)), 70, config.cpu_threshold),
        ),
        (
            "Memória atual",
            f"{float(latest.get('mem_usage_percent', 0.0)):.2f}%",
            f"Livre: {float(latest.get('mem_available_gb', 0.0)):.2f} GB",
            metric_status(float(latest.get("mem_usage_percent", 0.0)), 75, config.mem_threshold),
        ),
        (
            "Swap atual",
            f"{float(latest.get('swap_usage_percent', 0.0)):.2f}%",
            f"Usada: {float(latest.get('swap_used_gb', 0.0)):.2f} GB",
            metric_status(float(latest.get("swap_usage_percent", 0.0)), 5, config.swap_threshold),
        ),
        (
            "Disco atual",
            f"{float(latest.get('disk_usage_percent', 0.0)):.2f}%",
            f"Livre em {disk_path}: {float(latest.get('disk_available_gb', 0.0)):.2f} GB",
            metric_status(float(latest.get("disk_usage_percent", 0.0)), 75, config.disk_threshold),
        ),
        (
            "Alertas",
            str(alert_total),
            "Ocorrências registradas no arquivo de alertas",
            "critico" if alert_total else "ok",
        ),
    ]

    cards_html = "\n".join(
        f"""
        <article class="metric {status}">
          <p class="metric-label">{html.escape(label)}</p>
          <strong>{html.escape(value)}</strong>
          <span>{html.escape(detail)}</span>
        </article>
        """
        for label, value, detail, status in cards
    )

    table_html = "\n".join(
        f"""
        <tr>
          <td>{html.escape(str(row['timestamp']))}</td>
          <td>{float(row['cpu_usage_percent']):.2f}%</td>
          <td>{float(row['mem_usage_percent']):.2f}%</td>
          <td>{float(row.get('swap_usage_percent', 0.0)):.2f}%</td>
          <td>{float(row['mem_available_gb']):.2f} GB</td>
          <td>{float(row['disk_usage_percent']):.2f}%</td>
          <td>{float(row['disk_available_gb']):.2f} GB</td>
          <td>{float(row['load_1m']):.2f}</td>
        </tr>
        """
        for row in reversed(rows[-12:])
    )

    recurrence_cards = [
        ("CPU acima do limite", count_threshold_occurrences(rows, "cpu_usage_percent", config.cpu_threshold)),
        ("Memória acima do limite", count_threshold_occurrences(rows, "mem_usage_percent", config.mem_threshold)),
        ("Swap acima do limite", count_threshold_occurrences(rows, "swap_usage_percent", config.swap_threshold)),
        ("Disco acima do limite", count_threshold_occurrences(rows, "disk_usage_percent", config.disk_threshold)),
        ("Memória livre baixa", count_below_occurrences(rows, "mem_available_gb", config.min_available_mem_gb)),
        ("Disco livre baixo", count_below_occurrences(rows, "disk_available_gb", config.min_available_disk_gb)),
    ]
    recurrence_html = "\n".join(
        f"<div class='rule-card'><span>{html.escape(label)}</span><strong>{count} ocorrência(s)</strong></div>"
        for label, count in recurrence_cards
    )
    executive_metrics_html = ""
    if assessment_metrics:
        executive_metrics_html = f"""
      <div class="capacity-grid">
        <div class="capacity-card"><span>Amostras analisadas</span><strong>{int(assessment_metrics["total_amostras"])}</strong></div>
        <div class="capacity-card"><span>Alertas totais</span><strong>{int(assessment_metrics["alertas"])}</strong></div>
        <div class="capacity-card"><span>CPU acima do limite</span><strong>{float(assessment_metrics["cpu_rate"]):.2f}%</strong></div>
        <div class="capacity-card"><span>Memória acima do limite</span><strong>{float(assessment_metrics["mem_rate"]):.2f}%</strong></div>
        <div class="capacity-card"><span>Swap acima do limite</span><strong>{float(assessment_metrics["swap_rate"]):.2f}%</strong></div>
        <div class="capacity-card"><span>Disco acima do limite</span><strong>{float(assessment_metrics["disk_rate"]):.2f}%</strong></div>
      </div>
        """
    quick_read_html = ""
    if assessment_metrics:
        quick_read_html = f"""
      <div class="rules-grid">
        <div class="rule-card"><span>Decisão</span><strong>{assessment_title}</strong></div>
        <div class="rule-card"><span>Pressão de memória</span><strong>{float(assessment_metrics["mem_rate"]):.2f}% acima do limite</strong></div>
        <div class="rule-card"><span>Pressão de swap</span><strong>{float(assessment_metrics["swap_rate"]):.2f}% acima do limite</strong></div>
        <div class="rule-card"><span>Alertas no período</span><strong>{int(assessment_metrics["alertas"])}</strong></div>
      </div>
        """
    justification_text = build_justification_text(rows, alert_total, config)
    justification_text_html = html.escape(justification_text)
    email_subject = html.escape(f"Parecer técnico de capacidade - {str(latest.get('hostname', '-'))}")

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Relatório de Monitoramento</title>
  <style>
    :root {{
      --bg: #f4efe8;
      --panel: #fffdf8;
      --ink: #1f2933;
      --muted: #52606d;
      --ok: #1f7a4d;
      --warn: #b7791f;
      --danger: #b83232;
      --line: #d9d2c7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "DejaVu Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.16), transparent 24rem),
        linear-gradient(180deg, #fbf7f1, var(--bg));
    }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }}
    .hero, .section-card, .chart-card, .table-card, .metric {{
      background: rgba(255, 253, 248, 0.92);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: 0 12px 28px rgba(31, 41, 51, 0.06);
    }}
    .hero {{ padding: 28px; border-radius: 24px; }}
    h1, h2, h3 {{ margin: 0; font-weight: 700; }}
    h1 {{ font-size: 2rem; letter-spacing: -0.03em; }}
    .subtitle {{ margin-top: 10px; color: var(--muted); line-height: 1.5; }}
    .hero-grid, .metrics, .capacity-grid, .rules-grid, .charts, .process-grid {{
      display: grid;
      gap: 14px;
    }}
    .hero-grid, .metrics, .capacity-grid, .rules-grid, .process-grid {{
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }}
    .charts {{ grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); margin-top: 24px; gap: 18px; }}
    .hero-grid {{ margin-top: 20px; }}
    .hero-chip, .capacity-card, .rule-card {{
      padding: 14px 16px;
      background: #f7f2ea;
      border-radius: 16px;
      border: 1px solid var(--line);
    }}
    .hero-chip span, .capacity-card span, .rule-card span {{
      display: block;
      font-size: 0.84rem;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .metrics {{ margin-top: 22px; gap: 16px; }}
    .metric {{ padding: 18px; }}
    .metric.ok {{ border-left: 8px solid var(--ok); }}
    .metric.atencao {{ border-left: 8px solid var(--warn); }}
    .metric.critico {{ border-left: 8px solid var(--danger); }}
    .metric-label {{
      margin: 0 0 12px;
      color: var(--muted);
      text-transform: uppercase;
      font-size: 0.78rem;
      letter-spacing: 0.08em;
    }}
    .metric strong {{ display: block; font-size: 2rem; margin-bottom: 6px; }}
    .metric span {{ color: var(--muted); line-height: 1.4; }}
    .section-card, .table-card, .chart-card {{ padding: 18px; margin-top: 24px; }}
    .parecer-tools {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 10px;
    }}
    .parecer-tools input {{
      flex: 1 1 260px;
      min-width: 220px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 0.95rem;
    }}
    .parecer-tools button, .parecer-tools a {{
      border: 1px solid var(--line);
      background: #f7f2ea;
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 0.92rem;
      color: var(--ink);
      text-decoration: none;
      cursor: pointer;
    }}
    .parecer-text {{
      width: 100%;
      min-height: 280px;
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      resize: vertical;
      font-family: "DejaVu Sans Mono", "Consolas", monospace;
      font-size: 0.88rem;
      line-height: 1.45;
      background: #fffefb;
      color: var(--ink);
    }}
    details.fold {{
      margin-top: 18px;
      background: rgba(255, 253, 248, 0.92);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 12px 28px rgba(31, 41, 51, 0.04);
      padding: 4px 14px 14px;
    }}
    details.fold summary {{
      cursor: pointer;
      font-weight: 700;
      padding: 12px 4px;
      color: var(--ink);
    }}
    details.fold .section-card,
    details.fold .table-card,
    details.fold .charts {{
      margin-top: 10px;
    }}
    .decision-card {{
      padding: 18px;
      margin-top: 24px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: rgba(255, 253, 248, 0.92);
      box-shadow: 0 12px 28px rgba(31, 41, 51, 0.06);
      border-left-width: 10px;
    }}
    .decision-card.ok {{ border-left-color: var(--ok); }}
    .decision-card.atencao {{ border-left-color: var(--warn); }}
    .decision-card.critico {{ border-left-color: var(--danger); }}
    .decision-card ul {{ margin: 12px 0 0; padding-left: 18px; }}
    .decision-card li {{ margin-bottom: 8px; }}
    .subsection-title {{
      margin: 18px 0 12px;
      font-size: 1rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .chart-header {{ margin-bottom: 12px; }}
    .chart-meta {{ margin-top: 6px; color: var(--muted); font-size: 0.92rem; }}
    .process-card {{
      padding: 16px;
      background: #f7f2ea;
      border-radius: 16px;
      border: 1px solid var(--line);
    }}
    .process-list {{
      margin: 12px 0 0;
      padding-left: 18px;
    }}
    .process-list li {{
      margin-bottom: 10px;
    }}
    .process-list span {{
      display: block;
      color: var(--muted);
      font-size: 0.92rem;
      margin-top: 2px;
    }}
    svg {{
      width: 100%;
      height: auto;
      background: linear-gradient(180deg, rgba(15, 118, 110, 0.05), rgba(15, 118, 110, 0.01));
      border-radius: 14px;
    }}
    .axis {{ stroke: #b9b2a8; stroke-width: 1; }}
    .table-card {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    th, td {{
      padding: 12px 10px;
      border-bottom: 1px solid #ece4d8;
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    @media (max-width: 720px) {{
      h1 {{ font-size: 1.6rem; }}
      .wrap {{ padding: 18px 14px 36px; }}
      .hero {{ padding: 20px; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <h1>Relatório de Monitoramento da Máquina</h1>
      <p class="subtitle">
        Painel resumido para visualizar pressão de CPU, memória e disco ao longo da coleta.
        Hostname: <strong>{hostname}</strong>.
      </p>
      <div class="hero-grid">
        <div class="hero-chip"><span>Início da coleta</span><strong>{period_start}</strong></div>
        <div class="hero-chip"><span>Última coleta</span><strong>{period_end}</strong></div>
        <div class="hero-chip"><span>Total de amostras</span><strong>{len(rows)}</strong></div>
        <div class="hero-chip"><span>Disco monitorado</span><strong>{disk_path}</strong></div>
      </div>
    </section>
    <section class="metrics">{cards_html}</section>
    <section class="decision-card {assessment_css_class}">
      <h2>Parecer Técnico para Capacidade</h2>
      <h3 class="subsection-title">{assessment_title}</h3>
      <p class="subtitle">{assessment_summary}</p>
      {quick_read_html}
      <ul>{assessment_reasons_html}</ul>
      <h3 class="subsection-title">Resumo Executivo</h3>
      {executive_metrics_html}
    </section>
    <section class="section-card">
      <h2>Parecer para Envio</h2>
      <p class="subtitle">
        Use esta seção para copiar ou enviar por e-mail o conteúdo do parecer técnico.
      </p>
      <div class="parecer-tools">
        <input id="email-to" type="email" placeholder="destinatario@empresa.com" />
        <button type="button" onclick="copyParecer()">Copiar parecer</button>
        <button type="button" onclick="sendParecerEmail()">Enviar por e-mail</button>
        <a href="parecer_substituicao.txt" download>Baixar .txt</a>
      </div>
      <textarea id="parecer-text" class="parecer-text" readonly>{justification_text_html}</textarea>
      <input id="email-subject" type="hidden" value="{email_subject}" />
    </section>
    <details class="fold">
      <summary>Detalhes Técnicos de Capacidade e Regras</summary>
      <section class="section-card">
        <h2>Capacidade e Disponibilidade</h2>
        <h3 class="subsection-title">Capacidade Total da Máquina</h3>
        <div class="capacity-grid">
          <div class="capacity-card"><span>Memória total instalada na máquina</span><strong>{mem_total:.2f} GB</strong></div>
          <div class="capacity-card"><span>Swap total configurada</span><strong>{swap_total:.2f} GB</strong></div>
          <div class="capacity-card"><span>Disco total monitorado na máquina</span><strong>{disk_total:.2f} GB</strong></div>
        </div>
        <h3 class="subsection-title">Última Coleta</h3>
        <div class="capacity-grid">
          <div class="capacity-card"><span>Memória disponível na última coleta</span><strong>{float(latest.get('mem_available_gb', 0.0)):.2f} GB</strong></div>
          <div class="capacity-card"><span>Swap usada na última coleta</span><strong>{float(latest.get('swap_used_gb', 0.0)):.2f} GB</strong></div>
          <div class="capacity-card"><span>Disco disponível na última coleta</span><strong>{float(latest.get('disk_available_gb', 0.0)):.2f} GB</strong></div>
          <div class="capacity-card"><span>Processos em execução</span><strong>{int(float(latest.get('process_count', 0.0)))} </strong></div>
        </div>
      </section>
      <section class="section-card">
        <h2>Regras de Alerta</h2>
        <div class="rules-grid">
          <div class="rule-card"><span>CPU alta</span><strong>dispara em {config.cpu_threshold:.2f}% ou mais</strong></div>
          <div class="rule-card"><span>Memória alta</span><strong>dispara em {config.mem_threshold:.2f}% ou mais</strong></div>
          <div class="rule-card"><span>Swap alta</span><strong>dispara em {config.swap_threshold:.2f}% ou mais</strong></div>
          <div class="rule-card"><span>Disco alto</span><strong>dispara em {config.disk_threshold:.2f}% ou mais</strong></div>
          <div class="rule-card"><span>Memória livre baixa</span><strong>dispara abaixo de {config.min_available_mem_gb:.2f} GB</strong></div>
          <div class="rule-card"><span>Disco livre baixo</span><strong>dispara abaixo de {config.min_available_disk_gb:.2f} GB</strong></div>
          <div class="rule-card"><span>Intervalo de coleta</span><strong>{config.interval:.2f} segundos</strong></div>
        </div>
      </section>
    </details>
    <details class="fold">
      <summary>Evidências e Histórico Técnico</summary>
      <section class="charts">
        {svg_line_chart(rows, "cpu_usage_percent", "Uso de CPU", "%", "#0f766e", 100)}
        {svg_line_chart(rows, "mem_usage_percent", "Uso de Memória", "%", "#c05621", 100)}
        {svg_line_chart(rows, "swap_usage_percent", "Uso de Swap", "%", "#9f1239", 100)}
        {svg_line_chart(rows, "disk_usage_percent", "Uso de Disco", "%", "#2b6cb0", 100)}
        {svg_line_chart(rows, "mem_available_gb", "Memória Disponível", " GB", "#1f7a4d")}
      </section>
      <section class="section-card">
        <h2>Recorrência de Estados Críticos</h2>
        <div class="rules-grid">{recurrence_html}</div>
      </section>
      <section class="section-card">
        <h2>Processos Mais Pesados na Última Coleta</h2>
        <div class="process-grid">
          {render_process_list(top_cpu_processes, "Top processos por CPU")}
          {render_process_list(top_mem_processes, "Top processos por Memória")}
        </div>
      </section>
      <section class="table-card">
        <h2>Últimas Coletas</h2>
        <table>
          <thead>
            <tr>
              <th>Momento</th>
              <th>CPU</th>
              <th>Memória</th>
              <th>Swap</th>
              <th>Memória livre</th>
              <th>Disco</th>
              <th>Disco livre</th>
              <th>Load 1m</th>
            </tr>
          </thead>
          <tbody>{table_html}</tbody>
        </table>
      </section>
    </details>
  </main>
  <script>
    function copyParecer() {{
      const textArea = document.getElementById("parecer-text");
      if (!textArea) return;
      textArea.select();
      textArea.setSelectionRange(0, 999999);
      try {{
        document.execCommand("copy");
      }} catch (error) {{
        // sem acao: fallback manual pelo proprio textarea selecionado
      }}
    }}

    function sendParecerEmail() {{
      const toField = document.getElementById("email-to");
      const subjectField = document.getElementById("email-subject");
      const bodyField = document.getElementById("parecer-text");
      const to = toField ? toField.value.trim() : "";
      const subject = subjectField ? subjectField.value : "Parecer técnico de capacidade";
      const body = bodyField ? bodyField.value : "";
      const recipient = to ? to : "";
      const mailto = `mailto:${{recipient}}?subject=${{encodeURIComponent(subject)}}&body=${{encodeURIComponent(body)}}`;
      window.location.href = mailto;
    }}
  </script>
</body>
</html>
"""


def write_html_report(report_path: Path, rows: List[Dict[str, object]], alert_total: int, config: MonitorConfig) -> None:
    report_path.write_text(build_html_report(rows, alert_total, config), encoding="utf-8")


def write_justification_report(report_path: Path, rows: List[Dict[str, object]], alert_total: int, config: MonitorConfig) -> None:
    report_path.write_text(build_justification_text(rows, alert_total, config), encoding="utf-8")


def run_monitor(config: MonitorConfig) -> int:
    ensure_output_dir(config.output_dir)
    csv_path = config.output_dir / "monitoramento.csv"
    jsonl_path = config.output_dir / "monitoramento.jsonl"
    alert_path = config.output_dir / "alertas.log"
    event_path = config.output_dir / "execucao.log"
    report_path = config.output_dir / "relatorio.html"
    justification_path = config.output_dir / "parecer_substituicao.txt"

    normalize_csv_schema(csv_path)
    hostname = socket.gethostname()
    rows = load_rows(csv_path)
    stop_requested = False
    sample_count = 0

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        append_line(event_path, f"{now_iso()} INFO encerramento solicitado por sinal {signum}.")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    append_line(
        event_path,
        (
            f"{now_iso()} INFO monitor iniciado hostname={hostname} "
            f"interval={config.interval}s disco={config.disk_path} output_dir={config.output_dir}"
        ),
    )

    while not stop_requested:
        loop_started_at = time.time()
        row = collect_measurement(hostname, config)
        append_csv(csv_path, row)
        append_jsonl(jsonl_path, row)
        rows.append(row)

        for alert in evaluate_alerts(row, config):
            append_line(alert_path, alert)

        alert_total = count_non_empty_lines(alert_path)
        write_html_report(report_path, rows, alert_total, config)
        write_justification_report(justification_path, rows, alert_total, config)

        sample_count += 1
        if config.samples and sample_count >= config.samples:
            break

        elapsed = time.time() - loop_started_at
        time.sleep(max(0.0, config.interval - elapsed))

    append_line(event_path, f"{now_iso()} INFO monitor finalizado apos {sample_count} coleta(s).")
    alert_total = count_non_empty_lines(alert_path)
    write_html_report(report_path, rows, alert_total, config)
    write_justification_report(justification_path, rows, alert_total, config)
    return 0


def main() -> int:
    config = parse_config()
    return run_monitor(config)


if __name__ == "__main__":
    sys.exit(main())

