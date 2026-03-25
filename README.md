# Monitor de Recursos da Máquina

Projeto Python para monitorar CPU, memória, swap e disco em Windows/Linux.
Gera histórico de coletas, alertas e relatório para análise de capacidade.

## Estrutura real do projeto

```text
monitora_minha_maquina/
|-- src/
|   |-- monitor_base.py
|   |-- monitor_collect.py
|   |-- monitor_io.py
|   `-- monitor_recursos.py   <- entrypoint
|-- requirements.txt
|-- .gitignore
`-- README.md
```

## Entry point

O script executável é:

```bash
python src/monitor_recursos.py
```

## Instalação de dependências

O projeto funciona sem bibliotecas externas, mas recomenda `psutil`.

Instalar via `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Onde os logs são gravados

O valor padrão é `logs_monitoramento`, relativo ao diretório atual (cwd):

- Se rodar no root do projeto: `logs_monitoramento/`
- Se rodar dentro de `src/`: `src/logs_monitoramento/`

Para evitar dúvida, defina explicitamente:

```bash
python src/monitor_recursos.py --output-dir src/logs_monitoramento
```

## Arquivos gerados

No diretório de saída:

- `monitoramento.csv`
- `monitoramento.jsonl`
- `alertas.log`
- `execucao.log`
- `relatorio.html`
- `parecer_substituicao.txt`

## Recursos do relatorio.html

- resumo executivo com recomendação automática:
  - substituição recomendada
  - upgrade recomendado
  - manter com monitoramento
- indicadores e gráficos
- recorrência de estados críticos
- processos mais pesados da última coleta
- seção "Parecer para Envio":
  - copiar parecer
  - abrir envio por e-mail (mailto)
  - baixar `parecer_substituicao.txt`

## Exemplos

Rodar continuamente:

```bash
python src/monitor_recursos.py
```

Rodar 20 amostras:

```bash
python src/monitor_recursos.py --interval 60 --samples 20
```

Rodar com saída fixa em `src/logs_monitoramento`:

```bash
python src/monitor_recursos.py --output-dir src/logs_monitoramento
```

## Regras padrão de alerta

- CPU >= 85%
- Memória >= 85%
- Swap >= 20%
- Disco >= 85%
- Memória livre <= 2 GB
- Disco livre <= 10 GB

## Parametrização de alertas

Você pode alterar os limites por linha de comando:

- `--cpu-threshold`
- `--mem-threshold`
- `--disk-threshold`
- `--swap-threshold`
- `--min-available-mem-gb`
- `--min-available-disk-gb`

Exemplo:

```bash
python src/monitor_recursos.py \
  --cpu-threshold 75 \
  --mem-threshold 80 \
  --disk-threshold 80 \
  --swap-threshold 15 \
  --min-available-mem-gb 4 \
  --min-available-disk-gb 20
```

## Requisitos

- Python 3.10+
- Windows 10/11 ou Linux
- Dependências opcionais/recomendadas em `requirements.txt`
  - `psutil` (melhora coleta de processos e métricas)
