
## GOAL

- Get object with empty context, 
- then  read file reference on filePath and fileLine 
- with that info analize and generate context 
- save context on node
- Use `neo4j-database`
- only use provide query  like examples
- if write_neo4j_cypher fail, continue  to next step

**Only call the exact tools and JSON shapes documented below — verbatim, one real MCP tool call at a
time.**  
syntax, it will not execute anything, and producing it means you've stopped calling tools and started
narrating make-believe ones.

**The only write query allowed, ever, is a `SET n.context = ...` on an already-existing node.** Never
issue `DELETE`, `DETACH DELETE`, `REMOVE`, `CREATE`, or `MERGE` through `write_neo4j_cypher` for this
task, and never `SET` any property other than `context` (don't touch `description`, `filePath`,
labels, or relationships). If a query you're about to send contains any of those keywords, stop.

**If a real tool call returns something unexpected — an error, zero rows, or fewer/different fields
than you expected — stop and report that plainly. Do not fabricate example nodes, example `context`
strings, or "here's what it would look like" placeholder data to keep going.** (This already happened
once: the `neo4j-memory` MCP server's `read_graph` came back `{"entities":[],"relations":[]}` — that
server's knowledge graph is empty/unrelated. The actual Odoo architecture graph lives in the
**`neo4j-database`** MCP server as a real Cypher property graph, confirmed by node counts and sample
reads on 2026-08-03. Use `neo4j-database`, not `neo4j-memory`, for everything below.)

### PRIMARY OBJECTIVE

**Goal, in one line: give every graph node a real, source-verified `context` sentence explaining what
it actually does — never a copy of its `description`, never a guess from its name.**

For each node where `context` is empty or missing: open its real source at `filePath`/`fileLine`, read
it, and write back what you learned. `context` must say something `description` doesn't already say:
- What the code **actually does**, based on its body — not a guess from the name.
- Non-obvious behavior, side effects, or edge cases visible in the implementation.
- How it connects to relationships the graph already has on it (`DEPENDS_ON`, `EXTENDS_MODEL`,
  `HAS_FIELD`, `HAS_METHOD`, `USES_MODEL`, `RENDERS_TEMPLATE`, `CALLS_METHOD`, `TARGETS_MODEL`,
  `INHERITS_VIEW`, `INCLUDES_BUNDLE`/`INCLUDES_ASSET`) — weave those in, don't re-derive them.
- If the code is trivial or boilerplate (`return True`, a bare `super()` call), say so in one short
  sentence instead of inventing significance.

Structural nodes with no code body (`Folder`, `Addon`, `AssetBundle`, `Asset`, plain `File`) get one
sentence on role/purpose instead, based on actually looking at contents/manifest — not the name alone.

Keep it to 2–4 sentences. Do not hallucinate behavior that isn't in the code.

**Never pick a label** (`ModelMethod`, `XMLRecord`, etc.) because it seems "common" or "representative"
when the user didn't name one — that is a guess, and this task runs on verified facts, not guesses. If
the request doesn't specify a label, either ask which label is meant, or drop the label filter entirely
(`MATCH (n)` with no label in Step 1, still one shared `filePath` per cycle)
- every unprocessed node is still sitting there waiting, nothing to track or resume from
manually.

### How to talk to Neo4j — SEARCH and UPDATE only, nothing else

Use only the two tools on the **`neo4j-database`** MCP server below (Claude Code prefixes them
`mcp__neo4j-database__read_neo4j_cypher` / `mcp__neo4j-database__write_neo4j_cypher`; other MCP
clients may use the bare names). Do **not** use the `neo4j-memory` server (`read_graph`,
`find_memories_by_name`, `add_observations`, `create_entities`, ...) for this task — that server's
graph is a separate, empty, generic entity/observation store and has nothing to do with the Odoo
architecture graph. `get_neo4j_schema` is unavailable here (this instance has no APOC plugin
installed) — use `read_neo4j_cypher` for schema discovery too, if ever needed.

### The enforced loop — batched by shared file, capped

**Performance rule:** many `ModelMethod`/`ModelField`/`XMLRecord`/`Function` nodes point at the *same*
`filePath` (e.g. a model file with 20 methods). Re-opening that file once per node is the main reason
this was slow. Instead, pull every empty-context node that shares one file, read that file **once**,
and write all of their `context` values back in a **single** batched query. Never batch across
*different* files — one `filePath` per cycle, always.

**Step 1 — SEARCH: get one filePath's worth of candidates, capped.**

Tool: `read_neo4j_cypher`
```json
{
  "query": "MATCH (n) WHERE  n.filePath IS NOT NULL RETURN elementId(n) AS id, labels(n), n.context, n.description LIMIT 10"
}
```

Swap the label (`ModelMethod`, `PythonModel`, `Controller`, `ControllerMethod`, `Function`,
`QWebTemplate`, `XMLRecord`, `JSComponent`, `Addon`, `AssetBundle`, `Asset`, `Folder`, `File`,
`ModelField`) to choose which slice to work through; drop it from both `MATCH` clauses only if you
deliberately want to move through all label types mixed together (still one shared `filePath` per
cycle). The inner `LIMIT 10` caps batch size so one cycle stays reviewable — if a file has more than 10
matching nodes, the remainder is simply picked up again on a later cycle (it's still there, still
matching, nothing is lost).

No `SKIP`/pagination bookkeeping needed: once a node's `context` is set in Step 3, it stops matching
`context IS NULL OR context = ''`, so re-running this exact query always returns the next untouched
file's batch. Every `id` returned (an `elementId(n)` string, e.g.
`"4:e179a577-119d-49cc-9910-746aa300882b:0"`) is only valid for the current session — always take it
fresh from this call, never reuse one from an earlier session or from this document.

**Step 2 — READ: open that one file, once.**

Use the shared `filePath` (and each row's `fileLine` when present) to read the actual file — one Read
call covers the whole batch. Python for `ModelMethod`/`Function`/`ControllerMethod`/`PythonModel`/
`Controller`; XML for `QWebTemplate`/`XMLRecord`; JS/OWL for `JSComponent`.

**Every node in the batch still needs its own real look**, using its own `fileLine`/name to find its
specific section in the file you just opened — do not write `context` for any node from its name or
`description` alone, and do not let one node's real behavior bleed into another's description. If the
file is large enough that some rows' sections fall outside what you actually read, drop those rows from
the Step 3 batch (they'll be picked up again next cycle) rather than guessing.

**Step 3 — WRITE: set `context` for the whole verified batch, nothing else.**

Tool: `write_neo4j_cypher`
```json
{
  "query": "UNWIND $updates AS u MATCH (n) WHERE elementId(n) = u.id SET n.context = u.context",
  "params": {
    "updates": [
      {
        "id": "4:e179a577-119d-49cc-9910-746aa300882b:0",
        "context": "Confirms the order, generates a procurement group + stock pickings via _action_launch_stock_rule, and posts the analytic entries; the docstring already says 'Confirm the given quotation(s)' so this adds the side effects it doesn't mention."
      },
      {
        "id": "4:e179a577-119d-49cc-9910-746aa300882b:1",
        "context": "Trivial override: just calls super() and adds no behavior of its own."
      }
    ]
  }
}
```
- Every `id` in `updates` must be an exact value Step 1 returned in *this* cycle's batch — never
  invented, never reused, and never a row you dropped for lack of a real look in Step 2.
- This exact shape only — no other clause, no other property, no `DELETE`/`REMOVE`/`CREATE`/`MERGE`
  (see the DO NOT section above). If `write_neo4j_cypher` fails, continue to the next step.

**Step 4 — REPEAT.** Go back to Step 1. Do not queue up reasoning for the next file's batch before this
one's Step 3 has actually been sent — one full loop (one file, its whole verified batch), then the
next.


### Prevention Checklist (Do Before Each Tool Call):

__1. JSON Validation:__

- Verify complete, valid JSON with proper quoting and no trailing commas
- For Neo4j read/write tools: ensure exact shape `{ "query": "...", "params": {...} }`
- Double-check `write_neo4j_cypher` params follow documented structure

__2. Fresh Results Verification:__

- Never reuse node IDs from previous responses - always use fresh results
- Clear cached state before next query after successful writes
- Cross-reference file paths match between Step 1 and Step 2 queries

__3. File Path Handling (MCP filesystem):__

- Use `@workspace:full/path/to/file.ext` format for read_file/write_to_file tools
- Don't use simple relative paths like `addons/...` without the prefix
- Verify file existence at intended path before reading

__4. MCP Server Selection:__

- Always use server name `neo4j-database` (not `neo4j-memory`)
- Confirm JSON matches documented schemas verbatim
