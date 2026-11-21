"""The HTTP API (FastAPI). Interactive docs at /docs and the OpenAPI schema at /openapi.json, so a client (another
Claude session, a script) can read exactly what each call takes.

Every route but /v1/health needs "Authorization: Bearer <token>". Every token reads everything; writes are limited
to its scopes ("doc/<collection>/<key>", "portfolio/<source>", "price/<instrument>", or "*"). Document writes take
"If-Match: <version>" and fail with 409 if the document has moved on.
"""
import logging
from datetime import date
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import finance, portfolio
from .db import DB, Conflict, Forbidden, NotFound, Principal

log = logging.getLogger("core.server")


class Status(BaseModel):
    status: str = Field(pattern="^(ok|paused)$")
    paused_reason: str | None = None


class Price(BaseModel):
    day: date
    price_gbp: float = Field(gt=0)
    source: str = "manual"
    name: str | None = None


def _version(if_match: str | None) -> int | None:
    if if_match is None:
        return None
    try:
        return int(if_match.strip('"'))
    except ValueError:
        raise HTTPException(400, "If-Match must be a version number") from None


def create_app(db: DB, admin_token: str, health=lambda: {}) -> FastAPI:
    app = FastAPI(title="Home core", version="1", description=__doc__)
    bearer = HTTPBearer(auto_error=False)

    def who(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
        p = db.authenticate(cred.credentials if cred else "", admin_token)
        if not p:
            raise HTTPException(401, "missing or unknown token")
        return p

    for exc, status in ((NotFound, 404), (Conflict, 409), (Forbidden, 403), (ValueError, 400)):
        def handler(request: Request, e: Exception, status=status):
            detail = f"not found: {e.args[0]}" if isinstance(e, NotFound) else str(e)
            return JSONResponse({"detail": detail}, status_code=status)
        app.add_exception_handler(exc, handler)

    @app.get("/v1/health", tags=["meta"])
    def get_health():
        return {"ok": True, "schema": db.schema_version, **health()}

    @app.get("/v1/me", tags=["meta"])
    def me(p: Principal = Depends(who)):
        return {"name": p.name, "writes": p.scopes}

    @app.get("/v1/changes", tags=["meta"], summary="The change feed; waits up to `wait` s for something new")
    def changes(since: int = 0, wait: float = Query(0, ge=0, le=60), p: Principal = Depends(who)):
        items = db.changes_since(since, wait=wait)
        return {"seq": items[-1]["seq"] if items else since, "changes": items}

    @app.get("/v1/audit", tags=["meta"], summary="Who changed what, newest first")
    def audit(entity: str | None = None, key: str | None = None, limit: int = Query(100, ge=1, le=1000),
              p: Principal = Depends(who)):
        return {"items": db.audit_trail(entity, key, limit)}

    # -- general app state ---------------------------------------------------------
    @app.get("/v1/state", tags=["state"])
    def collections(p: Principal = Depends(who)):
        return {"collections": db.collections()}

    @app.get("/v1/state/{collection}", tags=["state"])
    def list_docs(collection: str, p: Principal = Depends(who)):
        return {"items": db.list_docs(collection)}

    @app.get("/v1/state/{collection}/{key}", tags=["state"])
    def get_doc(collection: str, key: str, p: Principal = Depends(who)):
        return db.get_doc(collection, key)

    @app.get("/v1/state/{collection}/{key}/versions", tags=["state"])
    def doc_versions(collection: str, key: str, limit: int = Query(50, ge=1, le=500), p: Principal = Depends(who)):
        return {"items": db.doc_versions(collection, key, limit)}

    @app.put("/v1/state/{collection}/{key}", tags=["state"], summary="Replace a document (any JSON)")
    def put_doc(collection: str, key: str, body: Any = Body(...), if_match: str | None = Header(None),
                p: Principal = Depends(who)):
        p.check(f"doc/{collection}/{key}")
        return db.put_doc(collection, key, body, p.name, _version(if_match))

    @app.patch("/v1/state/{collection}/{key}", tags=["state"], summary="Merge top-level fields; null removes one")
    def patch_doc(collection: str, key: str, body: dict[str, Any] = Body(...), if_match: str | None = Header(None),
                  p: Principal = Depends(who)):
        p.check(f"doc/{collection}/{key}")
        try:
            cur = db.get_doc(collection, key)
        except NotFound:
            cur = {"data": {}, "version": 0}
        if not isinstance(cur["data"], dict):
            raise HTTPException(400, "PATCH only works on object documents")
        merged = {k: v for k, v in {**cur["data"], **body}.items() if v is not None}
        expected = _version(if_match)
        return db.put_doc(collection, key, merged, p.name, cur["version"] if expected is None else expected)

    @app.delete("/v1/state/{collection}/{key}", tags=["state"])
    def delete_doc(collection: str, key: str, if_match: str | None = Header(None), p: Principal = Depends(who)):
        p.check(f"doc/{collection}/{key}")
        db.delete_doc(collection, key, p.name, _version(if_match))
        return {"deleted": f"{collection}/{key}"}

    # -- portfolio -----------------------------------------------------------------
    @app.get("/v1/portfolio", tags=["portfolio"], summary="Every source now, plus the merged summary")
    def get_portfolio(p: Principal = Depends(who)):
        sources = finance.current(db)
        total, summary = (portfolio.merge(sources, finance.valuations(db), date.today().isoformat())
                          if sources else (0, {}))
        return {"total": total, "summary": summary, "sources": sources}

    @app.get("/v1/portfolio/priceable", tags=["portfolio"], summary="Manual holdings a price would revalue")
    def get_priceable(p: Principal = Depends(who)):
        return {"items": finance.priceable(db)}

    @app.get("/v1/portfolio/{source}", tags=["portfolio"])
    def get_source(source: str, p: Principal = Depends(who)):
        for s in finance.current(db):
            if s["id"] == source:
                return s
        raise NotFound(f"portfolio/{source}")

    @app.put("/v1/portfolio/{source}", tags=["portfolio"], summary="A source's full current state: a new snapshot")
    def put_source(source: str, body: portfolio.Source, p: Principal = Depends(who)):
        p.check(f"portfolio/{source}")
        return finance.write_snapshot(db, source, body, p.name)

    @app.patch("/v1/portfolio/{source}", tags=["portfolio"], summary="Pause or resume a source")
    def patch_source(source: str, body: Status, p: Principal = Depends(who)):
        p.check(f"portfolio/{source}")
        finance.set_status(db, source, body.status, body.paused_reason, p.name)
        return {"source": source, "status": body.status}

    @app.delete("/v1/portfolio/{source}", tags=["portfolio"], summary="Stop showing a source (snapshots are kept)")
    def delete_source(source: str, p: Principal = Depends(who)):
        p.check(f"portfolio/{source}")
        finance.delete_source(db, source, p.name)
        return {"deleted": f"portfolio/{source}"}

    @app.get("/v1/portfolio/{source}/snapshots", tags=["portfolio"])
    def list_snapshots(source: str, limit: int = Query(50, ge=1, le=1000), p: Principal = Depends(who)):
        return {"items": finance.snapshots(db, source, limit)}

    @app.get("/v1/portfolio/{source}/snapshots/{snapshot_id}", tags=["portfolio"])
    def get_snapshot(source: str, snapshot_id: int, p: Principal = Depends(who)):
        snap = finance.snapshot(db, snapshot_id)
        if snap["source_id"] != source:
            raise NotFound(f"snapshot {snapshot_id} of {source}")
        return snap

    @app.put("/v1/prices/{instrument}", tags=["portfolio"], summary="An instrument's price in GBP on a day")
    def put_price(instrument: str, body: Price, p: Principal = Depends(who)):
        key = instrument.lower()
        p.check(f"price/{key}")
        finance.record_price(db, key, body.name or key, body.day.isoformat(), body.price_gbp, body.source, p.name)
        return {"price": key, "day": body.day.isoformat()}

    @app.get("/v1/valuations", tags=["portfolio"], summary="Daily totals")
    def get_valuations(limit: int = Query(400, ge=1, le=5000), p: Principal = Depends(who)):
        return {"items": [[d, v] for d, v in finance.valuations(db, limit).items()]}

    return app
