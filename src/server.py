"""
Datialog - Natural AI Data Explorer
© Iván Pastor · 2026
"""

import io
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import traceback
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import uvicorn
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Static dir: works both installed (pip) and local
STATIC_DIR = Path(__file__).parent / "static"


try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

import requests as _requests

# ── Online backend config ──────────────────────────────────────────────────────
# BACKEND: "ollama" | "lmstudio" | "groq" | "openai" | "anthropic"
BACKEND = os.environ.get("DATIALOG_BACKEND", "ollama").lower()
LM_STUDIO_URL = os.environ.get("DATIALOG_LMSTUDIO_URL", "http://localhost:1234/v1")

ONLINE_KEYS = {
    "groq":      os.environ.get("GROQ_API_KEY", ""),
    "openai":    os.environ.get("OPENAI_API_KEY", ""),
    "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
}

ONLINE_URLS = {
    "groq":   "https://api.groq.com/openai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}

DEFAULT_ONLINE_MODELS = {
    "groq":      ["llama-3.3-70b-versatile", "qwen-qwq-32b", "llama-3.1-8b-instant"],
    "openai":    ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
    "anthropic": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-6"],
}

try:
    import whisper as _whisper
    import tempfile, os
    WHISPER_AVAILABLE = True
    _whisper_model = None  # cargado lazy en primer uso
except ImportError:
    WHISPER_AVAILABLE = False

CHAT_PROMPTS = {
    "es": "Eres un asistente experto en estadistica, ciencia de datos, finanzas y Python. Responde de forma clara y pedagogica en espanol. Usa HTML simple si es util (<p>,<b>,<ul>,<li>,<code>). Sin html/head/body.",
    "en": "You are an expert assistant in statistics, data science, finance and Python. Respond clearly in English. Use simple HTML if useful (<p>,<b>,<ul>,<li>,<code>). No html/head/body.",
    "fr": "Vous etes un assistant expert en statistiques, data science, finance et Python. Repondez clairement en francais. Utilisez du HTML simple si utile (<p>,<b>,<ul>,<li>,<code>). Sans html/head/body.",
}

try:
    import pyreadstat
    PYREADSTAT_AVAILABLE = True
except ImportError:
    PYREADSTAT_AVAILABLE = False

app = FastAPI(title="Datialog", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Debug: print static dir on startup
import logging
logger = logging.getLogger("datialog")

# ── Estado global ─────────────────────────────────────────────────────────────
STATE: dict = {
    "datasets": {},
    "active_id": None,
    "filename": None,
    "history": [],
    "ds_counter": 0,
    "exec_scope": {},
    "undo_stack": {},
}

MAX_UNDO = 5
AUTO_UNDO_MB = 50

# ── System prompts ────────────────────────────────────────────────────────────
SYSTEM_PROMPTS = {
    "es": """Eres un asistente experto en analisis de datos con Python y pandas.
El usuario tiene un DataFrame llamado df ya cargado en memoria.
Tu tarea es responder GENERANDO EXCLUSIVAMENTE codigo Python ejecutable.

REGLAS ABSOLUTAS:
1. Responde SOLO con codigo Python puro. CERO texto adicional antes o despues.
2. PROHIBIDO usar bloques markdown. NUNCA escribas triple backtick.
3. El DataFrame ya existe como variable df. No lo cargues ni redefinas.
4. Para mostrar resultados usa SIEMPRE print(...).
5. Si filtras o transformas datos, asigna siempre el resultado a df (reemplaza el activo):
   df = df[df['col'] > 0]
6. Si quieres crear una variable auxiliar sin modificar df, usa otro nombre:
   aux = df[df['col'] > 0]   <- aux persiste y puedes usarla en siguientes preguntas
7. Confirma siempre con print al final.
7. Si algo no es posible, usa: print("No es posible: <razon>")
8. Puedes usar cualquier libreria Python instalada. Ejemplos habituales:
   - pandas, numpy para datos
   - sklearn para machine learning (train_test_split, modelos, metricas...)
   - scipy para estadistica
   - matplotlib.pyplot as plt  (no llames plt.show(), el sistema lo captura)
   - seaborn as sns             (igual, sin plt.show())
   - plotly.express as px / plotly.graph_objects as go  (el sistema captura la figura)
   Si una libreria no esta instalada, el sistema mostrara el error de importacion.

CORRECTO:
df = df[df['Price'] > 1000]
print(f"Filtrado: {len(df)} filas")

INCORRECTO:
```python
resultado = df[df['Price'] > 1000]
```
""",
    "en": """You are an expert data analysis assistant using Python and pandas.
The user has a DataFrame called df already loaded in memory.
Your task is to respond by generating EXCLUSIVELY executable Python code. Do NOT include any explanations, comments outside the code, or natural language text. ONLY output valid Python code that can be executed directly with exec(). If you need to explain something, use Python comments (#) inside the code.

ABSOLUTE RULES:
1. Respond ONLY with pure Python code. ZERO additional text before or after.
2. NEVER use markdown blocks. NEVER write triple backticks.
3. The DataFrame already exists as variable df. Do not load or redefine it.
4. To display results ALWAYS use print(...).
5. If you filter or transform data, always assign the result to df (replaces active):
   df = df[df['col'] > 0]
6. If you want an auxiliary variable without modifying df, use another name:
   aux = df[df['col'] > 0]   <- aux persists and can be used in next questions
7. Always confirm with print at the end.
7. If something is not possible, use: print("Not possible: <reason>")
8. You can use any installed Python library. Common examples:
   - pandas, numpy for data
   - sklearn for machine learning (train_test_split, models, metrics...)
   - scipy for statistics
   - matplotlib.pyplot as plt  (do NOT call plt.show(), the system captures it)
   - seaborn as sns             (same, no plt.show())
   - plotly.express as px / plotly.graph_objects as go  (the system captures the figure)
   If a library is not installed, the system will show the import error.

CORRECT:
df = df[df['Price'] > 1000]
print(f"Filtered: {len(df)} rows")

INCORRECT:
```python
result = df[df['Price'] > 1000]
```
""",
    "fr": """Vous etes un assistant expert en analyse de donnees avec Python et pandas.
L'utilisateur a un DataFrame appele df deja charge en memoire.
Votre tache est de repondre en generant EXCLUSIVEMENT du code Python executable.

REGLES ABSOLUES:
1. Repondez UNIQUEMENT avec du code Python pur. ZERO texte supplementaire.
2. INTERDIT d'utiliser des blocs markdown. N'ecrivez JAMAIS de triple backtick.
3. Le DataFrame existe deja comme variable df. Ne le chargez pas ni ne le redefinissez.
4. Pour afficher les resultats utilisez TOUJOURS print(...).
5. Si vous filtrez ou transformez des donnees, assignez toujours le resultat a df:
   df = df[df['col'] > 0]
6. Pour une variable auxiliaire sans modifier df, utilisez un autre nom:
   aux = df[df['col'] > 0]   <- aux persiste et peut etre utilisee dans les prochaines questions
7. Confirmez toujours avec un print a la fin.
7. Si quelque chose n'est pas possible, utilisez: print("Impossible: <raison>")
8. Vous pouvez utiliser n'importe quelle bibliothèque Python installée. Exemples courants:
   - pandas, numpy pour les données
   - sklearn pour le machine learning (train_test_split, modèles, métriques...)
   - scipy pour les statistiques
   - matplotlib.pyplot as plt  (ne PAS appeler plt.show(), le système le capture)
   - seaborn as sns             (pareil, sans plt.show())
   - plotly.express as px / plotly.graph_objects as go  (le système capture la figure)
   Si une bibliothèque n'est pas installée, le système affichera l'erreur d'importation.

CORRECT:
df = df[df['Prix'] > 1000]
print(f"Filtre: {len(df)} lignes")

INCORRECT:
```python
resultat = df[df['Prix'] > 1000]
```
""",
}

ERROR_PROMPTS = {
    "es": "El siguiente codigo fallo sobre un DataFrame pandas. Genera UNA sola linea print() con mensaje amigable en español, sin tecnicismos. Solo el print(), nada mas.\nCodigo: {code}\nError: {error}\nDataFrame: {ctx}",
    "en": "The following code failed on a pandas DataFrame. Generate ONE single print() line with a friendly message in English, no technical jargon. Only the print(), nothing else.\nCode: {code}\nError: {error}\nDataFrame: {ctx}",
    "fr": "Le code suivant a echoue sur un DataFrame pandas. Generez UNE seule ligne print() avec un message amical en francais, sans jargon technique. Seulement le print(), rien d'autre.\nCode: {code}\nError: {error}\nDataFrame: {ctx}",
}

FALLBACK_ERRORS = {
    "es": "No fue posible realizar esa operacion con los datos disponibles.",
    "en": "That operation could not be performed with the available data.",
    "fr": "Cette operation n'a pas pu etre effectuee avec les donnees disponibles.",
}

# ── Pydantic models ───────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    model: str = "llama3.2"
    lang: str = "es"

class SaveRequest(BaseModel):
    filename: Optional[str] = None
    format: str = "csv"
    dataset_id: Optional[str] = None

class SelectDatasetRequest(BaseModel):
    dataset_id: str

class RenameDatasetRequest(BaseModel):
    dataset_id: str
    name: str

# ── Helpers ───────────────────────────────────────────────────────────────────

def _register_dataset(df: pd.DataFrame, name: str, parent_id: str = None) -> str:
    STATE["ds_counter"] += 1
    ds_id = f"ds_{STATE['ds_counter']}"
    STATE["datasets"][ds_id] = {
        "df": df.copy(),
        "name": name,
        "rows": len(df),
        "cols": len(df.columns),
        "created": datetime.now().strftime("%H:%M:%S"),
        "parent_id": parent_id,
    }
    STATE["active_id"] = ds_id
    return ds_id

def _ds_list():
    return [
        {"id": k, "name": v["name"], "rows": v["rows"], "cols": v["cols"],
         "created": v["created"], "is_active": k == STATE["active_id"]}
        for k, v in STATE["datasets"].items()
    ]

def _df_snapshot(df: pd.DataFrame, n_preview: int = 5) -> dict:
    """Devuelve todo lo necesario para actualizar el frontend de un df."""
    preview = _serialize(df.head(n_preview).to_dict(orient="records"))
    dtypes = {c: str(t) for c, t in df.dtypes.items()}
    return {
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": df.columns.tolist(),
        "dtypes": dtypes,
        "preview": preview,
    }

def _chat_with_model(model: str, messages: list) -> str:
    """Unified chat — Ollama, LM Studio, Groq, OpenAI or Anthropic."""
    if BACKEND == "ollama":
        response = ollama.chat(model=model, messages=messages)
        return response.message.content or ""

    elif BACKEND == "lmstudio":
        url = f"{LM_STUDIO_URL}/chat/completions"
        resp = _requests.post(url, json={
            "model": model, "messages": messages,
            "temperature": 0.1, "max_tokens": 2048, "stream": False
        }, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0].get("message", {})
        return (msg.get("content") or msg.get("text") or "").strip()

    elif BACKEND in ("groq", "openai"):
        key = ONLINE_KEYS[BACKEND]
        if not key:
            raise RuntimeError(f"Missing API key for {BACKEND}. Set {BACKEND.upper()}_API_KEY env var.")
        resp = _requests.post(ONLINE_URLS[BACKEND], headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }, json={
            "model": model, "messages": messages,
            "temperature": 0.1, "max_tokens": 2048
        }, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""

    elif BACKEND == "anthropic":
        key = ONLINE_KEYS["anthropic"]
        if not key:
            raise RuntimeError("Missing API key for Anthropic. Set ANTHROPIC_API_KEY env var.")
        # Convert messages — Anthropic uses system separately
        system_msg = ""
        anthro_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                anthro_msgs.append({"role": m["role"], "content": m["content"]})
        payload = {
            "model": model,
            "max_tokens": 2048,
            "messages": anthro_msgs,
        }
        if system_msg:
            payload["system"] = system_msg
        resp = _requests.post("https://api.anthropic.com/v1/messages", headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"] or ""

    else:
        raise RuntimeError(f"Unknown backend: {BACKEND}")


def _df_context(df: pd.DataFrame) -> str:
    # Minimal context — only what the model needs to generate correct pandas code
    col_types = ", ".join(f"{c}:{str(t)[:3]}" for c, t in df.dtypes.items())
    return (
        f"df has {len(df)} rows and {len(df.columns)} columns.\n"
        f"Columns (name:type): {col_types}"
    )

def _clean_code(code: str) -> str:
    code = code.strip()
    # 1. Extract from markdown code block if present
    m = re.search(r"```(?:python|py|Python)?\s*\n([\s\S]*?)```", code)
    if m: return m.group(1).strip()
    if code.startswith("```"):
        lines = code.split("\n")[1:]
        if lines and lines[-1].strip() == "```": lines = lines[:-1]
        code = "\n".join(lines)
    code = re.sub(r"^```\w*\s*$", "", code, flags=re.MULTILINE)
    code = re.sub(r"^```\s*$", "", code, flags=re.MULTILINE)
    code = code.strip()
    # 2. Strip natural language lines mixed with code
    lines = code.split("\n")
    python_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if python_lines:
                python_lines.append(line)
            continue
        # Skip lines that look like natural language sentences
        # (start with uppercase word, contain spaces, end with period/comma)
        is_prose = (
            re.match(r'^[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s,\.\-\(\)\']+[\.:]?\s*$', stripped) and
            not stripped.startswith(("#", "    ")) and
            " " in stripped and
            not re.match(r'^[A-Za-z_][A-Za-z0-9_]*\s*[=\(\[\{]', stripped) and
            not any(stripped.startswith(kw) for kw in [
                "import ", "from ", "def ", "class ", "if ", "for ", "while ",
                "try:", "except", "with ", "return ", "yield ", "print(",
                "raise ", "assert ", "else:", "elif ", "finally:"
            ])
        )
        if not is_prose:
            python_lines.append(line)
    if python_lines:
        while python_lines and not python_lines[-1].strip():
            python_lines.pop()
        return "\n".join(python_lines).strip()
    return code.strip()
def _dataset_mb(df) -> float:
    try:
        return float(df.memory_usage(deep=True).sum() / 1024 / 1024)
    except Exception:
        return 999.0

def _save_checkpoint(ds_id: str, df, label: str = "auto") -> None:
    if ds_id not in STATE["undo_stack"]:
        STATE["undo_stack"][ds_id] = []
    stack = STATE["undo_stack"][ds_id]
    stack.append({"df": df.copy(), "label": label, "rows": len(df), "cols": len(df.columns)})
    if len(stack) > MAX_UNDO:
        stack.pop(0)

def _execute_code(code: str) -> dict:
    import numpy as np
    import base64

    prev_active_id = STATE["active_id"]
    active = STATE["datasets"][prev_active_id]
    df_before = active["df"]

    stdout_cap = io.StringIO()

    scope = STATE["exec_scope"]
    scope["df"] = df_before.copy()
    scope["pd"] = pd
    scope["np"] = np

    # Inject visualization libs if available
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.close("all")
        scope["plt"] = plt
    except ImportError:
        plt = None

    try:
        import seaborn as sns
        scope["sns"] = sns
    except ImportError:
        pass

    try:
        import plotly.express as px
        import plotly.graph_objects as go
        scope["px"] = px
        scope["go"] = go
    except ImportError:
        pass

    chart_data = None

    try:
        with redirect_stdout(stdout_cap):
            exec(code, scope)  # noqa: S102

        # Capture matplotlib/seaborn figure
        if plt is not None:
            figs = [plt.figure(i) for i in plt.get_fignums()]
            if figs:
                buf = io.BytesIO()
                figs[-1].savefig(buf, format="png", bbox_inches="tight", dpi=120)
                buf.seek(0)
                img_b64 = base64.b64encode(buf.read()).decode("utf-8")
                plt.close("all")
                chart_data = {"type": "image", "data": img_b64}

        # Capture plotly figure from scope
        if chart_data is None:
            try:
                import plotly.graph_objects as _go
                for var_val in scope.values():
                    if isinstance(var_val, _go.Figure):
                        chart_data = {
                            "type": "plotly",
                            "data": var_val.to_html(
                                full_html=False,
                                include_plotlyjs="cdn",
                                config={"responsive": True},
                            ),
                        }
                        break
            except Exception:
                pass

        # Persist scope
        STATE["exec_scope"] = {
            k: v for k, v in scope.items()
            if k not in ("pd", "np", "plt", "sns", "px", "go", "__builtins__")
        }

        result_df = scope.get("df")

        if result_df is not None and isinstance(result_df, pd.DataFrame):
            rows_changed = len(result_df) != len(df_before)
            cols_changed = list(result_df.columns) != list(df_before.columns)
            try:
                values_changed = not result_df.reset_index(drop=True).equals(df_before.reset_index(drop=True))
            except Exception:
                values_changed = True

            if rows_changed or cols_changed or values_changed:
                active["df"] = result_df
                active["rows"] = len(result_df)
                active["cols"] = len(result_df.columns)

        return {
            "output": stdout_cap.getvalue(),
            "error": None,
            "new_dataset": None,
            "chart": chart_data,
        }

    except Exception:
        if plt is not None:
            plt.close("all")
        return {
            "output": stdout_cap.getvalue(),
            "error": traceback.format_exc(),
            "new_dataset": None,
            "chart": None,
        }

def _friendly_error(code: str, error: str, df_info: str, model: str, lang: str) -> str:
    if not OLLAMA_AVAILABLE:
        return FALLBACK_ERRORS[lang]
    short_err = "\n".join(error.strip().splitlines()[-4:])
    prompt = ERROR_PROMPTS[lang].format(code=code[:250], error=short_err, ctx=df_info[:300])
    try:
        friendly_raw = _chat_with_model(model, [{"role": "user", "content": prompt}])
        friendly = _clean_code(friendly_raw.strip())
        out = io.StringIO()
        with redirect_stdout(out):
            exec(friendly, {})  # noqa: S102
        result = out.getvalue().strip()
        return result if result else friendly.replace("print(", "").strip().rstrip(")")
    except Exception:
        return FALLBACK_ERRORS[lang]

def _serialize(data):
    import numpy as np
    def cv(obj):
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.bool_): return bool(obj)
        if isinstance(obj, pd.Timestamp): return obj.isoformat()
        try:
            if pd.isna(obj): return None
        except Exception: pass
        return obj
    return [{k: cv(v) for k, v in row.items()} for row in data] if isinstance(data, list) else data

# ── Endpoints ─────────────────────────────────────────────────────────────────

# ── License check on startup ─────────────────────────────────────────────────
SKIP_LICENSE = os.environ.get("DATIALOG_SKIP_LICENSE", "0") == "1"
LICENSE_INFO = {"valid": True, "plan": "dev", "message": "Dev mode"}

if not SKIP_LICENSE:
    try:
        from datialog.license_manager import validate_license, get_license_info
        _result = validate_license()
        LICENSE_INFO = _result
        if not _result["valid"]:
            print(f"\n⚠️  Licencia inválida: {_result['message']}")
            print("   Activa tu licencia en: https://datialog.com/activate")
            print("   O ejecuta: python -m datialog.license_manager TU-CLAVE\n")
    except ImportError:
        pass  # License module not available — dev mode


@app.on_event("startup")
async def startup_event():
    index = STATIC_DIR / "index.html"
    logger.info(f"Datialog starting — static dir: {STATIC_DIR}")
    logger.info(f"index.html exists: {index.exists()}")
    if not index.exists():
        logger.error(f"ERROR: index.html not found at {index}")
        logger.error(f"Make sure you run uvicorn from inside datialog_pkg/")


@app.get("/")
def root():
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return JSONResponse(
            status_code=500,
            content={
                "error": f"index.html not found at {index}. "
                         f"Run uvicorn from inside datialog_pkg/ folder."
            }
        )
    return FileResponse(str(index))

@app.get("/health")
def health():
    return {
        "status": "ok",
        "ollama": OLLAMA_AVAILABLE,
        "whisper": WHISPER_AVAILABLE,
        "backend": BACKEND,
        "active_dataset": STATE["active_id"],
        "dataset_count": len(STATE["datasets"]),
    }

@app.get("/models")
def list_models():
    if BACKEND in ("groq", "openai", "anthropic"):
        return {"models": DEFAULT_ONLINE_MODELS.get(BACKEND, []), "backend": BACKEND}
    if BACKEND == "lmstudio":
        try:
            resp = _requests.get(f"{LM_STUDIO_URL}/models", timeout=5)
            models = [m["id"] for m in resp.json().get("data", [])]
            return {"models": models, "backend": "lmstudio"}
        except Exception as e:
            return {"models": [], "error": str(e)}
    # Ollama
    if not OLLAMA_AVAILABLE:
        return {"models": [], "error": "ollama not installed"}
    try:
        models = [m.model for m in ollama.list().models]
        return {"models": models, "backend": "ollama"}
    except Exception as e:
        return {"models": [], "error": str(e)}

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    if not WHISPER_AVAILABLE:
        raise HTTPException(400, "Whisper not installed: pip install openai-whisper")
    global _whisper_model
    audio_bytes = await file.read()
    # Guardar temporalmente
    suffix = Path(file.filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        if _whisper_model is None:
            _whisper_model = _whisper.load_model("small")
        result = _whisper_model.transcribe(tmp_path, fp16=False)
        text = result.get("text", "").strip()
        return {"text": text, "success": True}
    except Exception as e:
        raise HTTPException(500, f"Transcription error: {str(e)}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# Max upload size in bytes — change to suit your RAM (default 500 MB)
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"File too large ({size_mb:.1f} MB). Maximum allowed: {MAX_UPLOAD_BYTES // (1024*1024)} MB. "
            f"Increase MAX_UPLOAD_BYTES in server.py if needed."
        )
    fname = file.filename.lower()
    try:
        if fname.endswith(".csv"):
            sample = content[:2048].decode("utf-8", errors="replace")
            sep = ";" if sample.count(";") > sample.count(",") else ","
            df = pd.read_csv(io.BytesIO(content), sep=sep)
        elif fname.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        elif fname.endswith(".parquet"):
            df = pd.read_parquet(io.BytesIO(content))
        elif fname.endswith(".json"):
            df = pd.read_json(io.BytesIO(content))
        elif fname.endswith(".dta"):
            df = pd.read_stata(io.BytesIO(content))
        elif fname.endswith(".sas7bdat"):
            df = pd.read_sas(io.BytesIO(content), format="sas7bdat", encoding="utf-8")
        else:
            raise HTTPException(400, "Unsupported format. Use: CSV, Excel, Parquet, JSON, Stata (.dta) or SAS (.sas7bdat)")

        ds_id = _register_dataset(df, Path(file.filename).stem)
        STATE["filename"] = file.filename
        STATE["history"] = []
        STATE["exec_scope"] = {}

        snap = _df_snapshot(df)
        return {
            "success": True,
            "filename": file.filename,
            "dataset_id": ds_id,
            **snap,
            "datasets": _ds_list(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/datasets")
def list_datasets():
    return {"datasets": _ds_list(), "active_id": STATE["active_id"]}

@app.post("/datasets/select")
def select_dataset(req: SelectDatasetRequest):
    if req.dataset_id not in STATE["datasets"]:
        raise HTTPException(404, "Dataset not found")
    STATE["active_id"] = req.dataset_id
    STATE["history"] = []
    STATE["exec_scope"] = {}  # clear aux vars when switching dataset
    df = STATE["datasets"][req.dataset_id]["df"]
    snap = _df_snapshot(df)
    return {"success": True, "dataset_id": req.dataset_id, **snap, "datasets": _ds_list()}

@app.post("/datasets/rename")
def rename_dataset(req: RenameDatasetRequest):
    if req.dataset_id not in STATE["datasets"]:
        raise HTTPException(404, "Not found")
    STATE["datasets"][req.dataset_id]["name"] = req.name
    return {"success": True, "datasets": _ds_list()}


class SaveAsRequest(BaseModel):
    name: str
    variable: Optional[str] = None  # if set, save a scope variable instead of df


@app.post("/datasets/save_as")
def save_as_dataset(req: SaveAsRequest):
    """Save current df or a scope variable (aux, temp...) as a new named dataset."""
    if STATE["active_id"] is None:
        raise HTTPException(400, "No active dataset")

    scope = STATE["exec_scope"]
    if req.variable and req.variable in scope:
        candidate = scope[req.variable]
        if not isinstance(candidate, pd.DataFrame):
            raise HTTPException(400, f"Variable '{req.variable}' is not a DataFrame")
        df_to_save = candidate
    else:
        df_to_save = STATE["datasets"][STATE["active_id"]]["df"]

    new_id = _register_dataset(df_to_save, req.name)
    return {
        "success": True,
        "dataset_id": new_id,
        "datasets": _ds_list(),
        **_df_snapshot(df_to_save),
    }

@app.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    if dataset_id not in STATE["datasets"]:
        raise HTTPException(404, "Not found")
    del STATE["datasets"][dataset_id]
    if STATE["active_id"] == dataset_id:
        remaining = list(STATE["datasets"].keys())
        STATE["active_id"] = remaining[-1] if remaining else None
        STATE["history"] = []
    result = {"success": True, "datasets": _ds_list(), "active_id": STATE["active_id"]}
    if STATE["active_id"]:
        df = STATE["datasets"][STATE["active_id"]]["df"]
        result.update(_df_snapshot(df))
    return result

@app.post("/chat")
async def chat(req: ChatRequest):
    lang = req.lang if req.lang in SYSTEM_PROMPTS else "es"
    msg = req.message.strip()

    mode = "code"
    user_msg = msg
    if msg.lower().startswith("chat:"):
        mode = "chat"
        user_msg = msg[5:].strip()

    # Check license
    if not SKIP_LICENSE and not LICENSE_INFO.get("valid", True):
        return {"error": "Licencia inválida. Activa tu licencia en https://datialog.com/activate",
                "code": "", "output": "", "datasets": _ds_list()}

    if mode == "code" and STATE["active_id"] is None:
        no_data = {
            "es": "No hay datos cargados. Sube un archivo primero, o usa el modo Chat para preguntas generales.",
            "en": "No data loaded. Upload a file first, or switch to Chat mode for general questions.",
            "fr": "Aucune donnee chargee. Importez un fichier, ou passez en mode Chat.",
        }
        return {"error": no_data.get(lang, no_data["es"]), "code": "", "output": "", "datasets": _ds_list()}

    if mode == "chat":
        system = CHAT_PROMPTS.get(lang, CHAT_PROMPTS["es"])
    else:
        df = STATE["datasets"][STATE["active_id"]]["df"]
        system = SYSTEM_PROMPTS[lang] + "\n\n" + _df_context(df)

    messages = [{"role": "system", "content": system}]
    for h in STATE["history"][-6:]:
        messages.append(h)
    messages.append({"role": "user", "content": user_msg})

    try:
        raw = _chat_with_model(req.model, messages).strip()

        if mode == "chat":
            STATE["history"].append({"role": "user", "content": user_msg})
            STATE["history"].append({"role": "assistant", "content": raw})
            return {"code": raw, "output": "", "error": None, "mode": mode,
                    "datasets": _ds_list(), "active_id": STATE["active_id"],
                    "new_dataset": None, "chart": None}

        code = _clean_code(raw)
        CODE_KW = ("print(", "df[", "df.", "import ", " = ", "for ", "if ", "from ", "return ")
        if code and not any(k in code for k in CODE_KW):
            retry = messages + [{"role": "assistant", "content": raw},
                {"role": "user", "content": "Write ONLY Python code. No text. Just code."}]
            try:
                raw2 = _chat_with_model(req.model, retry).strip()
                code2 = _clean_code(raw2)
                if any(k in code2 for k in CODE_KW):
                    code = code2
            except Exception:
                pass

        # Auto-checkpoint before execution
        if STATE["active_id"] and STATE["active_id"] in STATE["datasets"]:
            _df_pre = STATE["datasets"][STATE["active_id"]]["df"]
            if _dataset_mb(_df_pre) < AUTO_UNDO_MB:
                _save_checkpoint(STATE["active_id"], _df_pre, "auto")

        exec_result = _execute_code(code)
        friendly_error = None
        if exec_result.get("error"):
            # Auto-retry up to 3 times — pass error back to model to fix
            MAX_RETRIES = 3
            retry_messages = messages.copy()
            current_code = code
            for attempt in range(MAX_RETRIES):
                err_text = exec_result["error"]
                retry_messages = retry_messages + [
                    {"role": "assistant", "content": current_code},
                    {"role": "user", "content": (
                        f"The code produced this error (attempt {attempt+1}/{MAX_RETRIES}):\n{err_text}\n\n"
                        f"Fix the error and return ONLY the corrected Python code. No explanations, no text, just code."
                    )}
                ]
                try:
                    raw_fix = _chat_with_model(req.model, retry_messages).strip()
                    code_fix = _clean_code(raw_fix)
                    if code_fix and code_fix != current_code:
                        exec_result2 = _execute_code(code_fix)
                        if not exec_result2.get("error"):
                            code = code_fix
                            exec_result = exec_result2
                            break  # success
                        else:
                            current_code = code_fix
                            exec_result = exec_result2
                    else:
                        break  # model returned same code, stop retrying
                except Exception:
                    break
            if exec_result.get("error"):
                df_ctx = _df_context(STATE["datasets"][STATE["active_id"]]["df"]) if STATE["active_id"] else ""
                fm = _friendly_error(code, exec_result["error"], df_ctx, req.model, lang)
                last = "\n".join(exec_result["error"].strip().splitlines()[-4:])
                friendly_error = f"{fm}\n\n🔍 Detalle: {last}"

        STATE["history"].append({"role": "user", "content": user_msg})
        STATE["history"].append({"role": "assistant", "content": code})

        snap = _df_snapshot(STATE["datasets"][STATE["active_id"]]["df"]) if STATE["active_id"] else {}
        return {"code": code, "output": exec_result["output"], "error": friendly_error,
                "mode": mode, **snap, "datasets": _ds_list(), "active_id": STATE["active_id"],
                "new_dataset": exec_result.get("new_dataset"), "chart": exec_result.get("chart")}

    except Exception as e:
        return {"code": "", "output": "",
                "error": f"Error de conexion con el modelo: {e}\n\nAsegurate de que Ollama esta corriendo.",
                "datasets": _ds_list()}


@app.get("/variables")
def get_variables():
    """Return all DataFrames in exec_scope plus loaded datasets."""
    import pandas as pd
    scope = STATE.get("exec_scope", {})
    SKIP = {"__builtins__", "__warningregistry__", "pd", "np", "plt", "sns", "px", "go"}
    dataframes = []
    seen_names = set()

    # 1. DataFrames from exec_scope (dynamically created)
    for name, val in scope.items():
        if name.startswith("_") or name in SKIP:
            continue
        if isinstance(val, pd.DataFrame):
            is_active = (name == "df" and STATE.get("active_id") is not None)
            label = ""
            if name == "df" and STATE.get("active_id"):
                ds = STATE["datasets"].get(STATE["active_id"], {})
                label = ds.get("name", name)
            dataframes.append({
                "name": name,
                "label": label or name,
                "rows": val.shape[0],
                "cols": val.shape[1],
                "columns": list(val.columns[:8]),
                "is_active": is_active,
                "source": "scope"
            })
            seen_names.add(name)

    # 2. Other non-df variables
    variables = []
    for name, val in scope.items():
        if name.startswith("_") or name in SKIP or name in seen_names:
            continue
        if isinstance(val, pd.DataFrame):
            continue  # already handled above
        try:
            if isinstance(val, pd.Series):
                vtype, shape = "Series", str(len(val))
            elif hasattr(val, "shape"):
                vtype, shape = type(val).__name__, str(val.shape)
            elif isinstance(val, (list, tuple)):
                vtype, shape = type(val).__name__, str(len(val))
            elif isinstance(val, dict):
                vtype, shape = "dict", f"{len(val)} keys"
            elif isinstance(val, (int, float, bool)):
                vtype, shape = type(val).__name__, str(val)[:20]
            elif isinstance(val, str):
                vtype, shape = "str", f"len={len(val)}"
            else:
                vtype, shape = type(val).__name__, ""
            variables.append({"name": name, "type": vtype, "shape": shape})
        except Exception:
            pass

    return {"dataframes": dataframes, "variables": variables}


@app.get("/dataframe")
def get_dataframe():
    if STATE["active_id"] is None:
        return {"error": "No dataset loaded"}
    df = STATE["datasets"][STATE["active_id"]]["df"]
    return _df_snapshot(df, n_preview=20)

@app.post("/save")
def save_dataframe(req: SaveRequest):
    ds_id = req.dataset_id or STATE["active_id"]
    if not ds_id or ds_id not in STATE["datasets"]:
        return {"error": "No dataset to save"}
    df = STATE["datasets"][ds_id]["df"]
    name = STATE["datasets"][ds_id]["name"]
    out_name = req.filename or f"{name}.{req.format}"

    # Build file in memory — no disk writes, works on any OS
    buf = io.BytesIO()
    try:
        if req.format == "csv":
            buf.write(df.to_csv(index=False).encode("utf-8"))
            media_type = "text/csv"
        elif req.format == "xlsx":
            df.to_excel(buf, index=False, engine="openpyxl")
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif req.format == "parquet":
            df.to_parquet(buf, index=False)
            media_type = "application/octet-stream"
        else:
            return {"error": "Unsupported format"}
    except Exception as e:
        return {"error": str(e)}

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )

class CheckpointRequest(BaseModel):
    ds_id: str = ""
    label: str = "manual"

@app.post("/checkpoint")
def save_checkpoint(req: CheckpointRequest):
    ds_id = req.ds_id or STATE["active_id"]
    if not ds_id or ds_id not in STATE["datasets"]:
        return {"success": False, "error": "No dataset active"}
    df = STATE["datasets"][ds_id]["df"]
    _save_checkpoint(ds_id, df, req.label or "manual")
    stack = STATE["undo_stack"].get(ds_id, [])
    return {"success": True, "checkpoints": int(len(stack)), "size_mb": round(_dataset_mb(df), 1)}

@app.post("/undo")
def undo(req: CheckpointRequest):
    ds_id = req.ds_id or STATE["active_id"]
    if not ds_id or ds_id not in STATE["datasets"]:
        return {"success": False, "error": "No dataset active"}
    stack = STATE["undo_stack"].get(ds_id, [])
    if not stack:
        return {"success": False, "error": "No hay checkpoints disponibles"}
    cp = stack.pop()
    df_r = cp["df"]
    STATE["datasets"][ds_id]["df"] = df_r
    STATE["datasets"][ds_id]["rows"] = len(df_r)
    STATE["datasets"][ds_id]["cols"] = len(df_r.columns)
    STATE["exec_scope"] = {}
    snap = _df_snapshot(df_r)
    return {"success": True, "label": cp["label"], "checkpoints_remaining": int(len(stack)), **snap, "datasets": _ds_list(), "active_id": STATE["active_id"]}

@app.get("/checkpoints")
def list_checkpoints():
    ds_id = STATE["active_id"]
    if not ds_id:
        return {"checkpoints": [], "count": 0, "auto_mode": True, "size_mb": 0.0}
    stack = STATE["undo_stack"].get(ds_id, [])
    df = STATE["datasets"].get(ds_id, {}).get("df")
    mb = _dataset_mb(df) if df is not None else 0.0
    return {
        "checkpoints": [{"label": c["label"], "rows": int(c["rows"]), "cols": int(c["cols"])} for c in stack],
        "count": int(len(stack)),
        "auto_mode": bool(mb < AUTO_UNDO_MB),
        "size_mb": round(float(mb), 1),
    }


# ── EDA background state ──────────────────────────────────────────────────────
EDA_STATE = {"status": "idle", "html": None, "error": None, "name": ""}

@app.post("/eda/start")
async def eda_start(background_tasks: BackgroundTasks):
    """Start EDA report generation in background."""
    if STATE["active_id"] is None:
        return {"error": "No dataset loaded"}
    if EDA_STATE["status"] == "running":
        return {"status": "running", "message": "Ya hay un informe generándose"}
    df = STATE["datasets"][STATE["active_id"]]["df"].copy()
    name = STATE["datasets"][STATE["active_id"]]["name"]
    EDA_STATE.update({"status": "running", "html": None, "error": None, "name": name})
    background_tasks.add_task(_generate_eda, df, name)
    return {"status": "running", "name": name}

def _generate_eda(df, name: str):
    try:
        from ydata_profiling import ProfileReport
        profile = ProfileReport(
            df,
            title=f"EDA — {name}",
            explorative=True,
            minimal=len(df) > 10000,
            progress_bar=False,
        )
        EDA_STATE["html"] = profile.to_html()
        EDA_STATE["status"] = "done"
    except ImportError:
        EDA_STATE["error"] = "ydata-profiling no instalado. Ejecuta: pip install ydata-profiling"
        EDA_STATE["status"] = "error"
    except Exception as e:
        EDA_STATE["error"] = str(e)
        EDA_STATE["status"] = "error"

@app.get("/eda/status")
def eda_status():
    """Check EDA generation status."""
    return {"status": EDA_STATE["status"], "name": EDA_STATE["name"], "error": EDA_STATE.get("error")}

@app.get("/eda/download")
def eda_download():
    """Download the generated EDA report."""
    if EDA_STATE["status"] != "done" or not EDA_STATE["html"]:
        return JSONResponse({"error": "Informe no disponible"}, status_code=404)
    name = EDA_STATE["name"]
    html = EDA_STATE["html"]
    EDA_STATE.update({"status": "idle", "html": None})  # reset after download
    return Response(content=html, media_type="text/html",
                    headers={"Content-Disposition": f'attachment; filename="eda_{name}.html"'})


@app.get("/eda_summary")
async def eda_summary():
    """Generate a quick EDA summary using pandas — no extra libraries needed."""
    if STATE["active_id"] is None:
        return {"error": "No dataset loaded"}
    df = STATE["datasets"][STATE["active_id"]]["df"]
    name = STATE["datasets"][STATE["active_id"]]["name"]
    try:
        import numpy as np
        n_rows, n_cols = df.shape
        nulls = df.isnull().sum()
        null_cols = nulls[nulls > 0].to_dict()
        num_cols = df.select_dtypes(include="number").columns.tolist()
        cat_cols = df.select_dtypes(include=["object","category"]).columns.tolist()
        date_cols = df.select_dtypes(include=["datetime"]).columns.tolist()
        duplicates = int(df.duplicated().sum())

        # Outliers via IQR
        outlier_cols = []
        for c in num_cols[:20]:
            q1, q3 = df[c].quantile(0.25), df[c].quantile(0.75)
            iqr = q3 - q1
            n_out = int(((df[c] < q1 - 1.5*iqr) | (df[c] > q3 + 1.5*iqr)).sum())
            if n_out > 0:
                outlier_cols.append({"col": c, "outliers": n_out, "pct": round(n_out/n_rows*100, 1)})

        # High correlations
        high_corr = []
        if len(num_cols) >= 2:
            corr = df[num_cols].corr().abs()
            for i in range(len(corr.columns)):
                for j in range(i+1, len(corr.columns)):
                    v = corr.iloc[i,j]
                    if v > 0.8 and not np.isnan(v):
                        high_corr.append({"col1": corr.columns[i], "col2": corr.columns[j], "corr": round(float(v), 3)})

        return {
            "name": name,
            "rows": n_rows,
            "cols": n_cols,
            "numeric_cols": len(num_cols),
            "categorical_cols": len(cat_cols),
            "date_cols": len(date_cols),
            "duplicates": duplicates,
            "null_cols": null_cols,
            "outlier_cols": outlier_cols[:10],
            "high_corr": high_corr[:10],
            "num_col_names": num_cols[:30],
            "cat_col_names": cat_cols[:20],
        }
    except Exception as e:
        return {"error": str(e)}


class ExecuteRequest(BaseModel):
    code: str
    lang: str = "es"

@app.post("/execute")
def execute_direct(req: ExecuteRequest):
    """Execute Python code directly without LLM — for the console panel."""
    code = req.code.strip()
    if not code:
        return {"output": "", "error": None}
    exec_result = _execute_code(code)
    friendly_error = None
    if exec_result.get("error"):
        friendly_error = exec_result["error"]
    # Auto-checkpoint if data changed
    if STATE["active_id"] and STATE["active_id"] in STATE["datasets"]:
        snap = _df_snapshot(STATE["datasets"][STATE["active_id"]]["df"])
    else:
        snap = {}
    return {
        "output": exec_result["output"],
        "error": friendly_error,
        "chart": exec_result.get("chart"),
        **snap,
        "datasets": _ds_list(),
        "active_id": STATE["active_id"],
    }


class LicenseRequest(BaseModel):
    key: str

@app.get("/license")
def license_info():
    """Get current license status."""
    if SKIP_LICENSE:
        return {"activated": True, "plan": "dev", "message": "Dev mode — no license required"}
    try:
        from datialog.license_manager import get_license_info, validate_license
        info = get_license_info()
        return {**info, "valid": LICENSE_INFO.get("valid", False),
                "message": LICENSE_INFO.get("message", "")}
    except ImportError:
        return {"activated": True, "plan": "dev", "message": "Dev mode"}

@app.post("/license/activate")
def activate_license_endpoint(req: LicenseRequest):
    """Activate a license key."""
    global LICENSE_INFO
    try:
        from datialog.license_manager import activate_license
        result = activate_license(req.key)
        if result["valid"]:
            LICENSE_INFO = result
        return result
    except ImportError:
        return {"valid": True, "message": "Dev mode — license not required"}


class BackendRequest(BaseModel):
    backend: str
    api_key: str = ""
    model: str = ""

@app.post("/set_backend")
def set_backend(req: BackendRequest):
    global BACKEND
    allowed = ("ollama", "lmstudio", "groq", "openai", "anthropic")
    if req.backend not in allowed:
        return {"success": False, "error": f"Unknown backend: {req.backend}"}
    BACKEND = req.backend
    if req.api_key:
        ONLINE_KEYS[req.backend] = req.api_key
    return {"success": True, "backend": BACKEND}


@app.post("/reset")
def reset():
    STATE.update({"datasets": {}, "active_id": None, "filename": None, "history": [], "ds_counter": 0, "exec_scope": {}, "undo_stack": {}})
    return {"success": True}


@app.post("/shutdown")
def shutdown():
    """Shuts down the Datialog server and optionally Ollama."""
    import threading

    def _kill():
        import time
        time.sleep(0.5)
        # Kill Ollama
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                               capture_output=True)
            else:
                subprocess.run(["pkill", "-f", "ollama"], capture_output=True)
        except Exception:
            pass
        # Kill self
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_kill, daemon=True).start()
    return {"success": True, "message": "Shutting down..."}

@app.post("/shutdown")
def shutdown():
    import threading, signal, sys, subprocess, platform
    def _stop():
        import time; time.sleep(0.5)
        # Intentar cerrar Ollama
        try:
            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/f", "/im", "ollama.exe"], capture_output=True)
            else:
                subprocess.run(["pkill", "-f", "ollama"], capture_output=True)
        except Exception:
            pass
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_stop, daemon=True).start()
    return {"success": True, "message": "Servidor apagando..."}

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
