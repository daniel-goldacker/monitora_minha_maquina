# Monitor de Recursos da Maquina

Projeto Python para monitorar CPU, memoria, swap e disco em Windows/Linux.
Gera historico de coletas, alertas e relatorio para analise de capacidade.

## Estrutura real do projeto

```text
monitora_minha_maquina/
|-- src/
|   |-- monitor_base.py
|   |-- monitor_collect.py
|   |-- monitor_io.py
|   |-- monitor_recursos.py   <- entrypoint
|   `-- logs_monitoramento/   <- pode existir aqui
|-- requirements.txt
|-- .gitignore
`-- README.md
```

## Entry point

O script executavel e:

```bash
python src/monitor_recursos.py
```

## Instalacao de dependencias

O projeto funciona sem bibliotecas externas, mas recomenda `psutil`.

Instalar via `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Onde os logs sao gravados

O valor padrao e `logs_monitoramento`, relativo ao diretorio atual (cwd):

- Se rodar no root do projeto: `logs_monitoramento/`
- Se rodar dentro de `src/`: `src/logs_monitoramento/`

Para evitar duvida, defina explicitamente:

```bash
python src/monitor_recursos.py --output-dir src/logs_monitoramento
```

## Arquivos gerados

No diretorio de saida:

- `monitoramento.csv`
- `monitoramento.jsonl`
- `alertas.log`
- `execucao.log`
- `relatorio.html`
- `parecer_substituicao.txt`

## Recursos do relatorio.html

- resumo executivo com recomendacao automatica:
  - substituicao recomendada
  - upgrade recomendado
  - manter com monitoramento
- indicadores e graficos
- recorrencia de estados criticos
- processos mais pesados da ultima coleta
- secao "Parecer para Envio":
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

Rodar com saida fixa em `src/logs_monitoramento`:

```bash
python src/monitor_recursos.py --output-dir src/logs_monitoramento
```

## Regras padrao de alerta

- CPU >= 85%
- Memoria >= 85%
- Swap >= 20%
- Disco >= 85%
- Memoria livre <= 2 GB
- Disco livre <= 10 GB

## Parametrizacao de alertas

Voce pode alterar os limites por linha de comando:

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
- Dependencias opcionais/recomendadas em `requirements.txt`
  - `psutil` (melhora coleta de processos e metricas)
