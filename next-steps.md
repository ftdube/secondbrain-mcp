# Next Steps

## Phases

| Phase | Stack | RAM | Trigger |
|---|---|---|---|
| **1a** (current) | FTS5 only | ~80 MB | — |
| 1b | + ONNX MiniLM + sqlite-vec + RRF | ~380 MB | FTS5 misses too many queries |
| 2a | sqlite-vec → Qdrant | ~280 MB + 80 MB | >300 notes or re-embed cost on restart |
| 2b | + Ollama reranker on external PC | ~100 MB + PC | Quality still insufficient |

## Phase 1b detail

Add `sqlite-vec`, ONNX `all-MiniLM-L6-v2`, RRF merge, wikilink adjacency table.

## Phase 1.5 — mobile write-back

Trigger: need to append to vault from Claude mobile.
`append_context(content)` tool, read-write SSH key, git commit/push.
