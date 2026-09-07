"""
The API + UI server. One process: FastAPI serves both the JSON endpoints and
the single static HTML page (app/static/index.html) that the grader clicks
through. Run with: uvicorn app.main:app --reload
"""
from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import get_connection, init_db, loads
from app.ingest import ingest_pdf
from app.llm.factory import get_adapter

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Fact Knowledge Layer")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

init_db()

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _row_to_claim(row) -> dict:
    return {
        "id": row["id"], "document_id": row["document_id"], "kind": row["kind"],
        "subject": row["subject"], "metric": row["metric_raw"],
        "value_raw": row["value_raw"], "value_number": row["value_number"],
        "value_unit": row["value_unit"], "value_scale": row["value_scale"],
        "value_normalized": row["value_normalized"], "state_value": row["state_value"],
        "period_label": row["period_label"], "period_type": row["period_type"],
        "period_start": row["period_start"], "period_end": row["period_end"],
        "qualifiers": loads(row["qualifiers_json"]), "quote": row["quote"],
        "page_num": row["page_num"], "confidence": row["confidence"], "notes": row["notes"],
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "provider": settings.active_provider}


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    dest = settings.upload_dir / f"{uuid.uuid4().hex}_{file.filename}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "filename": file.filename, "log": []}

    def _run():
        conn = get_connection()
        adapter = get_adapter()
        try:
            with _jobs_lock:
                _jobs[job_id]["status"] = "processing"

            def _log(msg):
                with _jobs_lock:
                    _jobs[job_id]["log"].append(msg)

            result = ingest_pdf(str(dest), conn=conn, adapter=adapter, verbose=False)
            conn.commit()
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result"] = result
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)
        finally:
            conn.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job id")
    return job


@app.get("/api/documents")
def list_documents():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, filename, title, doc_type, page_count, uploaded_at, meta_json FROM documents "
            "ORDER BY uploaded_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            n_claims = conn.execute(
                "SELECT COUNT(*) c FROM claims WHERE document_id = ?", (r["id"],)
            ).fetchone()["c"]
            out.append({
                "id": r["id"], "filename": r["filename"], "title": r["title"],
                "doc_type": r["doc_type"], "page_count": r["page_count"],
                "uploaded_at": r["uploaded_at"], "meta": loads(r["meta_json"]), "claim_count": n_claims,
            })
        return out
    finally:
        conn.close()


@app.get("/api/facts")
def list_facts(entity: str | None = None, metric: str | None = None, document_id: str | None = None,
                kind: str | None = None, q: str | None = None, limit: int = 200):
    conn = get_connection()
    try:
        sql = "SELECT * FROM claims WHERE 1=1"
        params: list = []
        if entity:
            sql += " AND subject LIKE ?"
            params.append(f"%{entity}%")
        if metric:
            sql += " AND metric_raw LIKE ?"
            params.append(f"%{metric}%")
        if document_id:
            sql += " AND document_id = ?"
            params.append(document_id)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if q:
            sql += " AND (subject LIKE ? OR metric_raw LIKE ? OR quote LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_claim(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/facts/{claim_id}")
def get_fact(claim_id: str):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown claim id")
        claim = _row_to_claim(row)
        doc = conn.execute("SELECT filename, title FROM documents WHERE id = ?", (row["document_id"],)).fetchone()
        claim["document_filename"] = doc["filename"] if doc else None
        claim["document_title"] = doc["title"] if doc else None
        return claim
    finally:
        conn.close()


@app.get("/api/relations")
def list_relations(verdict: str | None = None, axis: str | None = None, limit: int = 200):
    conn = get_connection()
    try:
        sql = "SELECT * FROM relations WHERE 1=1"
        params: list = []
        if verdict:
            sql += " AND verdict = ?"
            params.append(verdict)
        if axis:
            sql += " AND axis = ?"
            params.append(axis)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            a = conn.execute("SELECT * FROM claims WHERE id = ?", (r["claim_id_a"],)).fetchone()
            b = conn.execute("SELECT * FROM claims WHERE id = ?", (r["claim_id_b"],)).fetchone()
            doc_a = conn.execute("SELECT filename, title FROM documents WHERE id = ?", (a["document_id"],)).fetchone() if a else None
            doc_b = conn.execute("SELECT filename, title FROM documents WHERE id = ?", (b["document_id"],)).fetchone() if b else None
            out.append({
                "id": r["id"], "verdict": r["verdict"], "axis": r["axis"],
                "dimension_diff": loads(r["dimension_diff_json"]),
                "rule_trace": loads(r["rule_trace_json"]),
                "explanation": r["explanation"], "explained_by": r["explained_by"],
                "claim_a": {**_row_to_claim(a), "document_filename": doc_a["filename"] if doc_a else None} if a else None,
                "claim_b": {**_row_to_claim(b), "document_filename": doc_b["filename"] if doc_b else None} if b else None,
            })
        return out
    finally:
        conn.close()


@app.get("/api/schema")
def get_schema():
    conn = get_connection()
    try:
        metrics = conn.execute(
            "SELECT id, canonical_name, kind, aliases_json, created_at FROM metrics ORDER BY created_at"
        ).fetchall()
        entities = conn.execute(
            "SELECT id, canonical_name, aliases_json FROM entities"
        ).fetchall()
        return {
            "metrics": [
                {"id": m["id"], "name": m["canonical_name"], "kind": m["kind"],
                 "aliases": loads(m["aliases_json"]), "created_at": m["created_at"]}
                for m in metrics
            ],
            "entities": [
                {"id": e["id"], "name": e["canonical_name"], "aliases": loads(e["aliases_json"])}
                for e in entities
            ],
        }
    finally:
        conn.close()


@app.get("/api/issues")
def list_issues(issue_type: str | None = None, limit: int = 200):
    conn = get_connection()
    try:
        sql = "SELECT * FROM issues WHERE 1=1"
        params: list = []
        if issue_type:
            sql += " AND issue_type = ?"
            params.append(issue_type)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            doc = conn.execute("SELECT filename FROM documents WHERE id = ?", (r["document_id"],)).fetchone() if r["document_id"] else None
            out.append({
                "id": r["id"], "issue_type": r["issue_type"], "detail": r["detail"],
                "raw_payload": loads(r["raw_payload"]) if r["raw_payload"] else None,
                "document_filename": doc["filename"] if doc else None, "created_at": r["created_at"],
            })
        return out
    finally:
        conn.close()


@app.get("/api/stats")
def get_stats():
    conn = get_connection()
    try:
        def count(sql, *params):
            return conn.execute(sql, params).fetchone()["c"]
        return {
            "documents": count("SELECT COUNT(*) c FROM documents"),
            "claims": count("SELECT COUNT(*) c FROM claims"),
            "relations": count("SELECT COUNT(*) c FROM relations"),
            "issues": count("SELECT COUNT(*) c FROM issues"),
            "relations_by_verdict": {
                row["verdict"]: row["n"] for row in conn.execute(
                    "SELECT verdict, COUNT(*) n FROM relations GROUP BY verdict"
                ).fetchall()
            },
            "provider": settings.active_provider,
        }
    finally:
        conn.close()


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
