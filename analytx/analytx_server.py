# -*- coding: utf-8 -*-
"""
AnalytiX — web UI for the VMware inventory export → Word report pipeline.
Run: python analytx_server.py  → http://127.0.0.1:8765
"""

import base64
import io
import re
import threading
from pathlib import Path
from typing import Optional

import mammoth
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import analytx_report

_lock = threading.Lock()
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _norm_lang(lang: Optional[str]) -> str:
    return "de" if (lang or "").lower().startswith("de") else "en"


def _docx_to_preview_html(docx_bytes: bytes) -> str:
    """Convert DOCX to an HTML fragment for in-browser preview (best-effort)."""
    try:
        with io.BytesIO(docx_bytes) as bio:
            result = mammoth.convert_to_html(bio)
        return (result.value or "").strip()
    except Exception:
        return ""


def _api_msg(lang: str, key: str, **kwargs) -> str:
    L = _norm_lang(lang)
    catalog = {
        "no_file": {
            "en": "No file was selected.",
            "de": "Keine Datei ausgewählt.",
        },
        "empty_file": {
            "en": "The uploaded file is empty.",
            "de": "Die Datei ist leer.",
        },
        "missing_index": {
            "en": "index.html is missing from the static directory.",
            "de": "index.html fehlt im static-Verzeichnis.",
        },
        "build_fail": {
            "en": "Could not generate the report: {detail}",
            "de": "Bericht konnte nicht erzeugt werden: {detail}",
        },
    }
    msg = catalog[key][L]
    return msg.format(**kwargs) if kwargs else msg


app = FastAPI(title="AnalytiX", version=analytx_report.version)


@app.get("/api/version")
def api_version():
    return {"version": analytx_report.version, "app": "AnalytiX"}


@app.get("/")
def index_page(request: Request):
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        lang = request.headers.get("accept-language", "en")
        raise HTTPException(
            status_code=500, detail=_api_msg(lang, "missing_index")
        )
    return FileResponse(index)


@app.post("/api/convert")
async def convert_rvtools(
    file: UploadFile = File(...),
    lang: str = Form("en"),
):
    L = _norm_lang(lang)
    if not file.filename:
        raise HTTPException(status_code=400, detail=_api_msg(L, "no_file"))
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail=_api_msg(L, "empty_file"))

    with _lock:
        try:
            buf = analytx_report.run_pipeline_from_bytes(
                raw, file.filename, anonymize=False, lang=L
            )
        except ValueError as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex
        except Exception as ex:
            raise HTTPException(
                status_code=500,
                detail=_api_msg(L, "build_fail", detail=str(ex)),
            ) from ex

    stem = Path(file.filename).stem
    safe = re.sub(r"[^\w\-.]+", "_", stem, flags=re.UNICODE).strip("._") or "analytx_report"
    safe = safe[:120]
    out_name = safe + ".docx"
    payload = buf.getvalue()
    preview_html = _docx_to_preview_html(payload)

    return JSONResponse(
        {
            "filename": out_name,
            "size_bytes": len(payload),
            "document_base64": base64.b64encode(payload).decode("ascii"),
            "preview_html": preview_html,
        }
    )


def main():
    uvicorn.run(
        "analytx_server:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":
    main()
