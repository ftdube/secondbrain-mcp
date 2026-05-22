"""
SecondBrain MCP server — Phase 1a (FTS5 keyword search).

Three tools:
  get_overview()       — context.md + _map.md (session start)
  search(query)        — FTS5 keyword search, top 5 excerpts
  read_note(path)      — full note by vault-relative path

Auth: Bearer JWT issued by Dex (OAuth 2.1 / PKCE).
Index: SQLite FTS5 with porter stemmer, rebuilt on startup and POST /reindex.
Vault: mounted at VAULT_PATH (populated by a git-sync sidecar).
"""

import asyncio
import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
import uvicorn
from fastmcp import FastMCP
from jwt import PyJWKClient, decode as jwt_decode, PyJWTError
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

log = logging.getLogger(__name__)

VAULT_PATH    = Path(os.environ["VAULT_PATH"])
DB_PATH       = Path(os.environ.get("DB_PATH", "/data/index.db"))
DEX_ISSUER    = os.environ["DEX_ISSUER"]
MCP_CLIENT_ID = os.environ["MCP_CLIENT_ID"]
MCP_BASE_URL  = os.environ["MCP_BASE_URL"]


# ── Indexer ───────────────────────────────────────────────────────────────────

def _iter_chunks(path: str, text: str):
    """Yield (path, heading, body) tuples split at H1–H3 heading boundaries."""
    heading_re = re.compile(r"^#{1,3} .+$", re.MULTILINE)
    prev_pos, prev_heading = 0, ""
    for m in heading_re.finditer(text):
        chunk = text[prev_pos : m.start()].strip()
        if chunk:
            yield path, prev_heading, chunk
        prev_pos = m.start()
        prev_heading = m.group(0).lstrip("#").strip()
    tail = text[prev_pos:].strip()
    if tail:
        yield path, prev_heading, tail


def build_index(vault_path: Path, db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        DROP TABLE IF EXISTS chunks_fts;
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            path     UNINDEXED,
            heading,
            body,
            tokenize = 'porter unicode61'
        );
    """)
    rows: list[tuple[str, str, str]] = []
    for md in sorted(vault_path.rglob("*.md")):
        rel = str(md.relative_to(vault_path))
        if "Chat Archive" in rel:
            continue
        for chunk in _iter_chunks(rel, md.read_text(errors="replace")):
            rows.append(chunk)
    conn.executemany("INSERT INTO chunks_fts VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    log.info("indexed %d chunks from %s", len(rows), vault_path)
    return len(rows)


# ── MCP tools ─────────────────────────────────────────────────────────────────

mcp = FastMCP("SecondBrain")

SEARCH_COUNTER = Counter("mcp_searches_total", "Total search tool calls")


@mcp.tool()
def get_overview() -> str:
    """Return context.md and _map.md to orient Claude at session start."""
    parts = []
    for name in ("context.md", "_map.md"):
        p = VAULT_PATH / name
        if p.exists():
            parts.append(f"## {name}\n\n{p.read_text()}")
    return "\n\n---\n\n".join(parts) or "Vault unavailable."


@mcp.tool()
def search(query: str) -> str:
    """Search the vault. Returns up to 5 excerpts (path, heading, 200-char snippet)."""
    SEARCH_COUNTER.inc()
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT path,
                   heading,
                   snippet(chunks_fts, 2, '', '', '…', 30) AS excerpt
            FROM   chunks_fts
            WHERE  chunks_fts MATCH ?
            ORDER  BY rank
            LIMIT  5
            """,
            (query,),
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS5 syntax error — retry as a quoted phrase
        rows = conn.execute(
            """
            SELECT path,
                   heading,
                   snippet(chunks_fts, 2, '', '', '…', 30) AS excerpt
            FROM   chunks_fts
            WHERE  chunks_fts MATCH ?
            ORDER  BY rank
            LIMIT  5
            """,
            (f'"{query}"',),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return "No results."
    return "\n\n".join(f"**{r[0]}** — {r[1]}\n{r[2]}" for r in rows)


@mcp.tool()
def read_note(path: str) -> str:
    """Read a full vault note by relative path (e.g. 'Homelab/Ocean/Summary.md')."""
    p = (VAULT_PATH / path).resolve()
    if not p.is_relative_to(VAULT_PATH.resolve()):
        return f"Access denied: {path}"
    return p.read_text() if p.exists() else f"Not found: {path}"


# ── Auth ──────────────────────────────────────────────────────────────────────

_jwks_client: PyJWKClient | None = None


def _get_jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        cfg = httpx.get(
            f"{DEX_ISSUER}/.well-known/openid-configuration", timeout=10
        ).json()
        _jwks_client = PyJWKClient(cfg["jwks_uri"], cache_keys=True)
    return _jwks_client


# Paths that do not require a Bearer token.
# AUTH_PUBLIC_EXTRA: optional comma-separated list of additional public paths.
_extra = os.environ.get("AUTH_PUBLIC_EXTRA", "")
AUTH_PUBLIC = frozenset({
    "/health",
    "/metrics",
    "/reindex",
    "/.well-known/oauth-protected-resource",
    *(_extra.split(",") if _extra else []),
})


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in AUTH_PUBLIC:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": f'Bearer realm="{MCP_BASE_URL}"'},
            )
        token = auth.removeprefix("Bearer ")
        try:
            key = _get_jwks().get_signing_key_from_jwt(token).key
            jwt_decode(
                token, key,
                algorithms=["RS256"],
                audience=MCP_CLIENT_ID,
                issuer=DEX_ISSUER,
            )
        except PyJWTError:
            return JSONResponse({"error": "invalid token"}, status_code=401)
        return await call_next(request)


# ── Vault watcher ─────────────────────────────────────────────────────────────

async def _vault_watcher() -> None:
    """Poll vault mtime every 30s; reindex when git-sync delivers new content."""
    last: float = 0.0
    while True:
        await asyncio.sleep(30)
        try:
            mtime = max(
                f.stat().st_mtime
                for f in VAULT_PATH.rglob("*.md")
                if "Chat Archive" not in str(f)
            )
            if mtime > last:
                log.info("vault updated, reindexing")
                await asyncio.to_thread(build_index, VAULT_PATH, DB_PATH)
                last = mtime
        except (ValueError, FileNotFoundError):
            pass


# ── HTTP app ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(_: Starlette) -> AsyncIterator[None]:
    if VAULT_PATH.exists():
        build_index(VAULT_PATH, DB_PATH)
    else:
        log.warning("vault not mounted at startup; index empty until first sync")
    asyncio.create_task(_vault_watcher())
    yield


async def _metrics(_: Request) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def _health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _reindex(_: Request) -> JSONResponse:
    n = await asyncio.to_thread(build_index, VAULT_PATH, DB_PATH)
    return JSONResponse({"status": "indexed", "chunks": n})


async def _oauth_metadata(_: Request) -> JSONResponse:
    return JSONResponse({
        "resource": MCP_BASE_URL,
        "authorization_servers": [DEX_ISSUER],
        "bearer_methods_supported": ["header"],
    })


# fastmcp ≥ 2.0: http_app() returns a Starlette ASGI app for the MCP endpoint.
# If this method is missing in your fastmcp version, try:
#   mcp.streamable_http_app()  or  mcp.sse_app()
mcp_asgi = mcp.http_app()

app = Starlette(
    lifespan=_lifespan,
    routes=[
        Route("/health",                                _health),
        Route("/metrics",                               _metrics),
        Route("/reindex",                               _reindex,        methods=["POST"]),
        Route("/.well-known/oauth-protected-resource",  _oauth_metadata),
        Mount("/",                                      mcp_asgi),
    ],
)
app.add_middleware(BearerAuthMiddleware)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8000)
