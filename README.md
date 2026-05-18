# Datialog — Natural AI Data Explorer

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20075103.svg)](https://doi.org/10.5281/zenodo.20075103)
[![PyPI](https://img.shields.io/pypi/v/datialog)](https://pypi.org/project/datialog/)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)

Analyze datasets in plain language using AI. No code required. Your data never leaves your machine.

## Installation

```bash
pip install datialog
```

## Usage

```bash
# Launch (opens browser + system tray icon)
datialog

# Custom port
datialog --port 9090

# Terminal mode (no system tray)
datialog --no-tray
```

Or from Python:

```python
import datialog
datialog.launch()
```

## Features

- **Natural language** — ask questions in Spanish or English
- **100% local** — data never leaves your machine with Ollama
- **Multi-backend** — Ollama, Groq, OpenAI, Anthropic, LM Studio
- **Multiple formats** — CSV, Excel, Stata, SAS, Parquet, JSON
- **Auto EDA** — exploratory analysis with one click
- **Python console** — integrated code console
- **Checkpoint & Undo** — revert transformations
- **System tray** — background mode with tray icon

## Supported formats

| Format | Extension |
|--------|-----------|
| CSV | .csv |
| Excel | .xlsx, .xls |
| Stata | .dta |
| SAS | .sas7bdat |
| Parquet | .parquet |
| JSON | .json |

## Requirements

- Python 3.10+
- For local models: [Ollama](https://ollama.com)
- For cloud models: API key from Groq, OpenAI or Anthropic

## Author

**Ivan Pastor Sanz** — [datialog.app](https://datialog.app)

## Citation

```bibtex
@software{pastor_sanz_2026_datialog,
  author    = {Pastor Sanz, Iván},
  title     = {Datialog — Natural AI Data Explorer},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.20075103},
  url       = {https://doi.org/10.5281/zenodo.20075103}
}
```

## License

CC BY-NC 4.0 — free for personal, academic and research use.
Commercial use requires explicit permission from the author.
