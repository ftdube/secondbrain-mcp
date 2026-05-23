# Next Steps

## Phases

| Phase | Stack | RAM | Trigger |
|---|---|---|---|
| **1a** ✅ deployed | FTS5 only | ~80 MB | — |
| 1b | + ONNX MiniLM + sqlite-vec + RRF | ~380 MB | FTS5 misses too many queries |
| 2a | sqlite-vec → Qdrant | ~280 MB + 80 MB | >300 notes or re-embed cost on restart |
| 2b | + Ollama reranker on external PC | ~100 MB + PC | Quality still insufficient |

## Phase 1b trigger monitoring

`mcp_search_misses_total` / `mcp_searches_total` — miss rate over a rolling window.
Alert threshold: >20% miss rate over 7 days → trigger Phase 1b.

Grafana PromQL: `rate(mcp_search_misses_total[7d]) / rate(mcp_searches_total[7d])`

## Phase 1b detail

Add `sqlite-vec`, ONNX `all-MiniLM-L6-v2`, RRF merge, wikilink adjacency table.

## Phase 1.5 — mobile write-back

Trigger: need to append to vault from Claude mobile.
`append_context(content)` tool, read-write SSH key, git commit/push.
