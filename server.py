"""
SecondBrain MCP server — Phase 1a (FTS5 keyword search).

Five tools:
  get_overview()               — context.md + _map.md (session start)
  search(query)                — FTS5 keyword search, top 10 excerpts
  read_note(path, offset=0)     — note by vault-relative path, paginated past ~20,000 chars
  note(title, content)          — save a draft note to the vault inbox
  propose_edit(edits, rationale) — draft a reviewable diff against one or more notes (existing or new), atomically

Auth: Bearer JWT issued by Dex (OAuth 2.1 / PKCE).
Index: SQLite FTS5 with porter stemmer, rebuilt on startup and POST /reindex.
Vault: mounted at VAULT_PATH (populated by a git-sync sidecar).
Inbox: notes written to OUTBOX_PATH; push-sync sidecar commits and pushes them.
Proposals: propose_edit also writes to OUTBOX_PATH (as *.patch.md); push-sync
routes those to Proposals/ instead of Inbox/. Applied out of band via
scripts/apply_proposals.py — never by a model. See agents.md.
Blacklist: VAULT_BLACKLIST (comma-separated vault-relative directory prefixes)
excludes matching notes from indexing, read_note, and propose_edit.
"""

import asyncio
import difflib
import hashlib
import logging
import os
import re
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastmcp import FastMCP
from jwt import PyJWKClient, PyJWTError
from jwt import decode as jwt_decode
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

log = logging.getLogger(__name__)

VAULT_PATH    = Path(os.environ["VAULT_PATH"])
DB_PATH       = Path(os.environ.get("DB_PATH", "/data/index.db"))
DEX_ISSUER    = os.environ["DEX_ISSUER"]
DEX_JWKS_URI  = os.environ.get("DEX_JWKS_URI", f"{DEX_ISSUER}/keys")
MCP_CLIENT_ID = os.environ["MCP_CLIENT_ID"]
MCP_BASE_URL  = os.environ["MCP_BASE_URL"]
OUTBOX_PATH   = Path(os.environ.get("OUTBOX_PATH", "/outbox"))

def _parse_blacklist(raw: str) -> tuple[tuple[str, ...], ...]:
    """FR-BLK-1: comma-separated vault-relative directory prefixes excluded from
    indexing, read_note, and propose_edit — mirrors AUTH_PUBLIC_EXTRA's convention.
    Empty/unset is exactly today's behavior (NFR-BLK-2). Leading slashes are
    stripped: entries are relative by definition, and Path("/x").parts == ("/",
    "x") would otherwise never match a real relative path — a plausible typo
    (e.g. "/Private/Journal") would then silently blacklist nothing."""
    return tuple(
        Path(entry).parts
        for entry in (p.strip().lstrip("/") for p in raw.split(","))
        if entry
    )


VAULT_BLACKLIST: tuple[tuple[str, ...], ...] = _parse_blacklist(os.environ.get("VAULT_BLACKLIST", ""))


def _is_blacklisted(rel_path: Path) -> bool:
    """FR-BLK-4: path-segment prefix match, so 'Private/Journal' excludes
    'Private/Journal/*' but not the sibling file 'Private/JournalNotes.md'."""
    parts = rel_path.parts
    return any(parts[: len(prefix)] == prefix for prefix in VAULT_BLACKLIST)


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
    effective = vault_path / "vault"
    if not effective.exists():
        effective = vault_path
    rows: list[tuple[str, str, str]] = []
    for md in sorted(effective.rglob("*.md")):
        rel_path = md.relative_to(effective)
        rel = str(rel_path)
        if "Chat Archive" in rel:
            continue
        if _is_blacklisted(rel_path):
            continue
        rows.extend(_iter_chunks(rel, md.read_text(errors="replace")))
    conn.executemany("INSERT INTO chunks_fts VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    log.info("indexed %d chunks from %s", len(rows), vault_path)
    return len(rows)


# ── MCP tools ─────────────────────────────────────────────────────────────────

mcp = FastMCP("SecondBrain")

OVERVIEW_COUNTER = Counter("mcp_overviews_total", "Total get_overview tool calls")
SEARCH_COUNTER   = Counter("mcp_searches_total",  "Total search tool calls")
READ_COUNTER     = Counter("mcp_reads_total",      "Total read_note tool calls")

OVERVIEW_CHARS  = Counter("mcp_overview_chars_total",  "Characters returned by get_overview")
SEARCH_CHARS    = Counter("mcp_search_chars_total",    "Characters returned by search")
READ_CHARS      = Counter("mcp_read_chars_total",       "Characters returned by read_note")
SEARCH_MISSES   = Counter("mcp_search_misses_total",   "Search queries that returned no results")
NOTE_COUNTER    = Counter("mcp_notes_total",            "Total note tool calls")
PROPOSE_COUNTER = Counter("mcp_propose_edits_total",    "Total propose_edit tool calls")


def _effective_vault() -> Path:
    return VAULT_PATH / "vault" if (VAULT_PATH / "vault").exists() else VAULT_PATH


def _resolve_in_vault(path: str) -> Path | None:
    """Resolve a vault-relative path, rejecting traversal, symlink escape (FR-COM-1),
    and blacklisted prefixes (FR-BLK-3/5, NFR-BLK-3). None if inaccessible."""
    effective = _effective_vault().resolve()
    p = (effective / path).resolve()
    if not p.is_relative_to(effective):
        return None
    if _is_blacklisted(p.relative_to(effective)):
        return None
    return p


@mcp.tool()
def get_overview() -> str:
    """Return context.md and _map.md to orient Claude at session start."""
    try:
        OVERVIEW_COUNTER.inc()
        effective = _effective_vault()
        parts = []
        for name in ("context.md", "_map.md"):
            p = effective / name
            if p.exists():
                parts.append(f"## {name}\n\n{p.read_text()}")
        result = "\n\n---\n\n".join(parts) or "Vault unavailable."
        OVERVIEW_CHARS.inc(len(result))
        return result
    except Exception as e:  # noqa: BLE001 — FR-COM-6: tools return errors to the client, never raise
        return f"Error: {e}"


@mcp.tool()
def search(query: str) -> str:
    """Search the vault. Returns up to 10 excerpts (path, heading, 200-char snippet)."""
    try:
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
                LIMIT  10
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
                LIMIT  10
                """,
                (f'"{query}"',),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            SEARCH_MISSES.inc()
            return "No results."
        result = "\n\n".join(f"**{r[0]}** — {r[1]}\n{r[2]}" for r in rows)
        SEARCH_CHARS.inc(len(result))
        return result
    except Exception as e:  # noqa: BLE001 — FR-COM-6: tools return errors to the client, never raise
        return f"Error: {e}"


# NFR-READ-2 (BRD.md OI-2): caps a single response's token cost. Truncation is
# flagged in-band rather than silent so a caller can tell a note was cut short.
READ_MAX_CHARS = 20_000


@mcp.tool()
def read_note(path: str, offset: int = 0) -> str:
    """Read a vault note by relative path (e.g. 'Homelab/Ocean/Summary.md'). Notes longer than ~20,000 characters are truncated; pass the offset from a truncated response's marker to continue reading."""
    try:
        READ_COUNTER.inc()
        p = _resolve_in_vault(path)
        if p is None:
            return f"Access denied: {path}"
        if not p.exists():
            return f"Not found: {path}"
        content = p.read_text()
        offset = max(0, offset)
        chunk = content[offset : offset + READ_MAX_CHARS]
        next_offset = offset + len(chunk)
        if next_offset < len(content):
            total_bytes = len(content.encode())
            chunk += (
                f"\n\n...(truncated, {total_bytes} bytes total"
                f"; call read_note with offset={next_offset} to continue)"
            )
        result = chunk
        READ_CHARS.inc(len(result))
        return result
    except Exception as e:  # noqa: BLE001 — FR-COM-6: tools return errors to the client, never raise
        return f"Error: {e}"


def _note_filename(title: str) -> str:
    safe = re.sub(r"[^\w\s-]", "", title).strip()
    safe = re.sub(r"\s+", "-", safe)
    return (safe[:80] or "untitled") + ".md"


@mcp.tool()
def note(title: str, content: str) -> str:
    """Save a note to the vault inbox for later review. Use when you don't know, or don't need to commit to, the exact destination — content will be triaged and filed later. For a precise, structured change at a known path, use `propose_edit` instead."""
    try:
        NOTE_COUNTER.inc()
        OUTBOX_PATH.mkdir(parents=True, exist_ok=True)
        filename = _note_filename(title)
        dest = OUTBOX_PATH / filename
        if dest.exists():
            filename = f"{filename[:-3]}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
            dest = OUTBOX_PATH / filename
        dest.write_text(f"# {title}\n\n{content}\n")
        return f"Saved to inbox: {filename}"
    except Exception as e:  # noqa: BLE001 — FR-COM-6: tools return errors to the client, never raise
        return f"Error: {e}"


def _make_diff(rel_path: str, old: str, new: str, is_new: bool = False) -> str:
    # index line uses a dummy 0000000 blob pair, not a real git hash-object id.
    # A real id would let `git apply --3way` locate the historical blob and
    # attempt a genuine content merge — which can silently succeed with
    # conflict markers written into the note (and `--check` reports that as
    # clean). The dummy id forces apply to fall back to plain context
    # matching, so any drift is rejected cleanly instead of merged. See agents.md.
    hunk = "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile="/dev/null" if is_new else f"a/{rel_path}",
        tofile=f"b/{rel_path}",
    ))
    mode_line = "new file mode 100644\n" if is_new else ""
    return (
        f"diff --git a/{rel_path} b/{rel_path}\n"
        f"{mode_line}"
        f"index 0000000..0000000 100644\n"
        f"{hunk}"
    )


@mcp.tool()
def propose_edit(edits: list[dict[str, str]], rationale: str) -> str:
    """Propose find/replace edits to one or more vault notes, existing or new, as a single reviewable diff. Each edit is {path, old, new}; old is optional (defaults to ""). To create a new note, the first edit for that path must omit old. Edits sharing a path apply in order. Multiple paths in one call become one atomic proposal — applied all together or not at all. Never writes to the vault directly. Use only when you can name the exact target path(s) and write precise content without guessing — otherwise use `note`."""
    try:
        PROPOSE_COUNTER.inc()
        if not edits:
            return "No edits provided."

        paths: list[str] = []
        for edit in edits:
            if edit["path"] not in paths:
                paths.append(edit["path"])

        # path -> (rel_path, original, edited content, is_new)
        results: dict[str, tuple[str, str, str, bool]] = {}
        for path in paths:
            p = _resolve_in_vault(path)
            if p is None:
                return f"Access denied: {path}"

            is_new = not p.exists()
            path_edits = [edit for edit in edits if edit["path"] == path]
            if is_new and path_edits[0].get("old", ""):
                return f"No such note: {path}. To create it, the first edit for this path must omit `old` (or pass old=\"\")."

            rel_path = p.relative_to(_effective_vault().resolve()).as_posix()
            content = original = "" if is_new else p.read_text()
            i = 0
            for edit in edits:
                if edit["path"] != path:
                    continue
                i += 1
                old, new = edit.get("old", ""), edit["new"]
                count = content.count(old)
                if count == 0:
                    return f"Edit {i} for {path} failed: anchor not found."
                if count > 1:
                    return f"Edit {i} for {path} failed: anchor matches {count} times, must match exactly once."
                content = content.replace(old, new, 1)
            results[path] = (rel_path, original, content, is_new)

        changed_paths = [path for path in paths if results[path][1] != results[path][2]]
        if not changed_paths:
            return "No changes: edits produce identical content for all paths."

        diff_parts, digest_parts, rel_paths = [], [], []
        for path in changed_paths:
            rel_path, original, content, is_new = results[path]
            diff_parts.append(_make_diff(rel_path, original, content, is_new=is_new))
            digest_parts.append(rel_path + content)
            rel_paths.append(rel_path)
        diff = "".join(diff_parts)
        digest = hashlib.sha256("".join(digest_parts).encode()).hexdigest()[:8]

        slug = re.sub(r"[^\w-]", "-", Path(rel_paths[0]).stem)
        if len(rel_paths) > 1:
            slug += "-multi"
        filename = f"{slug}-{digest}.patch.md"

        OUTBOX_PATH.mkdir(parents=True, exist_ok=True)
        dest = OUTBOX_PATH / filename
        if dest.exists():
            return f"Already proposed (unchanged): {filename}"
        header = ", ".join(rel_paths)
        drafted = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        dest.write_text(f"# Proposed edit: {header}\n\nDrafted: {drafted}\n\n{rationale}\n\n```diff\n{diff}```\n")
        return f"Proposed: {filename}"
    except Exception as e:  # noqa: BLE001 — FR-COM-6: tools return errors to the client, never raise
        return f"Error: {e}"


# ── Auth ──────────────────────────────────────────────────────────────────────

_jwks_client: PyJWKClient | None = None


def _get_jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(DEX_JWKS_URI, cache_keys=True)
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
            log.warning("No Bearer token for %s (Authorization: %r)", request.url.path, auth[:30] if auth else None)
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": (
                    f'Bearer realm="{MCP_BASE_URL}",'
                    f' resource_metadata="{MCP_BASE_URL}/.well-known/oauth-protected-resource"'
                )},
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
        except PyJWTError as e:
            log.warning("JWT validation failed: %s", e)
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
                for f in _effective_vault().rglob("*.md")
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
async def _lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp_asgi.lifespan(app):
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
