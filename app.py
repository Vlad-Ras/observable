"""Independent upload receiver and viewer for Observable 5.4.4.

The stock mod POSTs a gzip JSON body and expects a plain-text report URL.
"""
import asyncio
import contextlib
import gzip
import hmac
import io
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://observable.roften.ru").rstrip("/")
UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN", "")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))
MAX_UPLOAD = 8 * 1024 * 1024
MAX_JSON = 32 * 1024 * 1024
ID = re.compile(r"^[a-f0-9]{32}$")
log = logging.getLogger("observable-roften")


def validate_config():
    if len(UPLOAD_TOKEN) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", UPLOAD_TOKEN):
        raise RuntimeError("Set UPLOAD_TOKEN to at least 32 URL-safe random characters")
    url = urlsplit(PUBLIC_URL)
    if url.scheme not in {"https", "http"} or not url.netloc or url.query or url.fragment or url.username:
        raise RuntimeError("PUBLIC_URL must be an absolute HTTP(S) base URL")
    if RETENTION_DAYS < 1:
        raise RuntimeError("RETENTION_DAYS must be positive")


def cleanup():
    cutoff = time.time() - RETENTION_DAYS * 86400
    for p in DATA.glob("*.json.gz"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except FileNotFoundError:
            pass


async def janitor():
    while True:
        try:
            await run_in_threadpool(cleanup)
        except OSError:
            log.exception("Report cleanup failed")
        await asyncio.sleep(21600)


@asynccontextmanager
async def lifespan(app):
    validate_config()
    DATA.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(janitor())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    return response


def decode_profile(raw):
    if raw.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(MAX_JSON + 1)
        except (OSError, EOFError) as e:
            raise HTTPException(400, "Invalid gzip") from e
    if len(raw) > MAX_JSON:
        raise HTTPException(413, "Decompressed report is too large")
    try:
        obj = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeDecodeError, RecursionError) as e:
        raise HTTPException(400, "Invalid JSON") from e
    if not isinstance(obj, dict):
        raise HTTPException(400, "Expected a JSON object")
    data = obj.get("data", obj)
    if not isinstance(data, dict) or not all(k in data for k in ("blocks", "entities", "ticks")):
        raise HTTPException(400, "Not an Observable profile")
    if type(data["ticks"]) is not int or data["ticks"] < 0:
        raise HTTPException(400, "Invalid tick count")
    for kind in ("blocks", "entities"):
        if not isinstance(data[kind], dict):
            raise HTTPException(400, "Expected dimension maps")
        for dimension, entries in data[kind].items():
            if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
                raise HTTPException(400, "Expected lists of entries")
    return raw


def store(raw):
    raw = decode_profile(raw)
    report_id = secrets.token_hex(16)
    target = DATA / f"{report_id}.json.gz"
    tmp = DATA / f"{report_id}.tmp"
    try:
        with tmp.open("xb") as f:
            f.write(gzip.compress(raw, compresslevel=5, mtime=0))
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return report_id


@app.post("/v1/add/{token}", response_class=PlainTextResponse)
async def upload(token: str, request: Request):
    if not hmac.compare_digest(token.encode(), UPLOAD_TOKEN.encode()):
        raise HTTPException(404, "Not found")
    declared = request.headers.get("content-length")
    if declared:
        try:
            size = int(declared)
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length")
        if size > MAX_UPLOAD:
            raise HTTPException(413, "Upload is too large")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(413, "Upload is too large")
    report_id = await run_in_threadpool(store, bytes(raw))
    return f"{PUBLIC_URL}/report/{report_id}"


def report_file(report_id):
    if not ID.fullmatch(report_id):
        raise HTTPException(404, "Report not found")
    path = DATA / f"{report_id}.json.gz"
    try:
        expired = time.time() - path.stat().st_mtime > RETENTION_DAYS * 86400
    except FileNotFoundError:
        raise HTTPException(404, "Report not found")
    if expired:
        raise HTTPException(410, "Report has expired")
    return path


@app.get("/api/report/{report_id}")
def report(report_id: str):
    return FileResponse(report_file(report_id), media_type="application/json", headers={"Content-Encoding": "gzip"})


@app.get("/download/{report_id}")
def download(report_id: str):
    return FileResponse(report_file(report_id), media_type="application/gzip", filename=f"observable-{report_id}.json.gz")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/robots.txt")
def robots():
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.get("/")
@app.get("/report/{report_id}")
def index(report_id: str | None = None):
    if report_id is not None:
        report_file(report_id)
    return FileResponse(ROOT / "static" / "index.html", media_type="text/html")


@app.get("/static/{filename}")
def asset(filename: str):
    if filename not in {"app.js", "style.css"}:
        raise HTTPException(404)
    return FileResponse(ROOT / "static" / filename)
