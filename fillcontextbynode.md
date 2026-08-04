### DO NOT — read this before touching anything

**Never run a shell/Bash/`python -c` command, never open a `neo4j` Python driver connection, never
call `cypher-shell`, and never `curl`/HTTP the Bolt or browser endpoint directly.** There is no
approved way to reach this graph except the two MCP tool calls in the "How to talk to Neo4j" section
below: `read_neo4j_cypher` (search/read) and `write_neo4j_cypher` (update). Cypher itself is fine and
required — it's how those two tools work — but it must always go through one of those two tool calls,
never through a terminal command containing `GraphDatabase`, `bolt://`, or `session.run` (e.g.
`neo4j_odoo_ingest.py`, which is unrelated tooling used once to build the graph, not something to
imitate here).

**Never edit, create, rename, or delete any file in this repository — not even a comment, not even
one line.** This task reads source files (to understand what the code does) but the *only* write
operation that exists anywhere in the recurring node-processing loop is the `write_neo4j_cypher` call
that sets `context` on a graph node. If you are about to use an edit/write/replace-in-file tool for
*any* path — application code, CSVs, security rules, anything — stop. That action is not part of this
task, no matter how small or well-intentioned. Reading a file is fine and required; writing to one is
never fine here. (This file, `fillcontextbynode.md`, was itself corrected on 2026-08-03 by direct,
explicit user instruction in-chat after the tool references below were found to be wrong — that was a
one-off human-directed documentation fix, not part of the recurring loop, and it doesn't reopen the
door to editing repo files as part of running this task.)

**Only call the exact tools and JSON shapes documented below — verbatim, one real MCP tool call at a
time.** Do not invent pseudo-XML tags, and do not invent path-style addressing — none of that is real
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

Keep it to 2–8 sentences. Do not hallucinate behavior that isn't in the code.

**Scale:** ~105,000 nodes repo-wide need `context` as of 2026-08-04 — most of it is `File`,
`ModelMethod`, `ModelField`, and `XMLRecord`; everything else is smaller. This will never finish in
one sitting, so it isn't meant to: work **one node at a time** (below), stop whenever, resume later —
every unprocessed node is still sitting there waiting, nothing to track or resume from manually.

### How to talk to Neo4j — SEARCH and UPDATE only, nothing else

Use only the two tools on the **`neo4j-database`** MCP server below (Claude Code prefixes them
`mcp__neo4j-database__read_neo4j_cypher` / `mcp__neo4j-database__write_neo4j_cypher`; other MCP
clients may use the bare names). Do **not** use the `neo4j-memory` server (`read_graph`,
`find_memories_by_name`, `add_observations`, `create_entities`, ...) for this task — that server's
graph is a separate, empty, generic entity/observation store and has nothing to do with the Odoo
architecture graph. `get_neo4j_schema` is unavailable here (this instance has no APOC plugin
installed) — use `read_neo4j_cypher` for schema discovery too, if ever needed.

### The enforced loop — exactly one node at a time

**Never pull more than one node into play at once.** No batches, no lookahead, no "grab 10 and work
through the list." Repeat this four-step loop, in order, for one node per cycle:

**Step 1 — SEARCH: get exactly one candidate.**

Tool: `read_neo4j_cypher`
```json
{
  "query": "MATCH (n:ModelMethod) WHERE n.context IS NULL OR n.context = '' RETURN elementId(n) AS id, labels(n) AS labels, n LIMIT 1"
}
```

Swap the label (`ModelMethod`, `PythonModel`, `Controller`, `ControllerMethod`, `Function`,
`QWebTemplate`, `XMLRecord`, `JSComponent`, `Addon`, `AssetBundle`, `Asset`, `Folder`, `File`,
`ModelField`) to choose which slice to work through; drop it (`MATCH (n) WHERE ...`) only if you
deliberately want to move through all label types mixed together.

No `SKIP`/pagination bookkeeping needed: once a node's `context` is set in Step 3, it stops matching
`context IS NULL OR context = ''`, so re-running this exact query always returns the next untouched
node. The `id` it returns (an `elementId(n)` string, e.g. `"4:e179a577-119d-49cc-9910-746aa300882b:0"`)
is only valid for the current session — always take it fresh from this call, never reuse one from an
earlier session or from this document.

**Step 2 — READ: open the real source.**

Use the row's `filePath` (and `fileLine` when present) to read the actual file. Python for
`ModelMethod`/`Function`/`ControllerMethod`/`PythonModel`/`Controller`; XML for
`QWebTemplate`/`XMLRecord`; JS/OWL for `JSComponent`. Do not write `context` from the node's name or
`description` alone — the point of this step is to have actually looked.

**Step 3 — WRITE: set `context` on that one node, nothing else.**

Tool: `write_neo4j_cypher`
```json
{
  "query": "MATCH (n) WHERE elementId(n) = $id SET n.context = $context",
  "params": {
    "id": "4:e179a577-119d-49cc-9910-746aa300882b:0",
    "context": "Confirms the order, generates a procurement group + stock pickings via _action_launch_stock_rule, and posts the analytic entries; the docstring already says 'Confirm the given quotation(s)' so this adds the side effects it doesn't mention."
  }
}
```
- `id` must be the exact value Step 1 returned for *this* node — never invented, never reused.
- This exact shape only — no other clause, no other property, no `DELETE`/`REMOVE`/`CREATE`/`MERGE`
  (see the DO NOT section above).

**Step 4 — REPEAT.** Go back to Step 1. Do not queue up reasoning for a second node before this one's
Step 3 has actually been sent — one full loop, then the next.
