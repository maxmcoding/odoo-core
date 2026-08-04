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

For every node where `context = ""` (or the property is missing), go to its real source location,
actually read the code there, and write back a short, genuinely analytical `context` string — not a
restatement of what's already in `description` (which already holds the docstring / `help`/`string`
text, and may itself be empty).

`context` must add value `description` doesn't already give:
- What the code **actually does**, based on reading its body — not a guess from the name.
- Non-obvious behavior, side effects, or edge cases visible in the implementation.
- How it connects to what the graph already knows about it — pull the node's existing relationships
  (`DEPENDS_ON`, `EXTENDS_MODEL`/`DEFINES_MODEL`, `HAS_FIELD`, `HAS_METHOD`, `USES_MODEL`,
  `RENDERS_TEMPLATE`, `CALLS_METHOD`, `TARGETS_MODEL`, `INHERITS_VIEW`, `INCLUDES_BUNDLE`/
  `INCLUDES_ASSET`) and weave them in instead of re-deriving them from scratch.
- If the code is trivial or pure boilerplate (`return True`, a one-line `super()` passthrough), say
  that plainly in one short sentence rather than inventing significance.

For structural/non-code nodes (`Folder`, `Addon`, `AssetBundle`, `Asset`, plain `File`), there's no
method body to analyze — `context` should instead be one short sentence on the node's role/purpose in
the addon, derived from actually looking at its contents or manifest, not invented from the name
alone.

Keep it to 2–4 sentences. Do not hallucinate behavior that isn't in the code.

**Scale note (as of 2026-08-03):** ~104,551 nodes repo-wide currently have empty/missing `context`,
across these labels (counts from a real query, not an estimate):

| label | count | label | count |
|---|---|---|---|
| File | 40,719 | JSComponent | 1,166 |
| ModelMethod | 15,441 | PythonModel | 1,030 |
| ModelField | 12,817 | Function | 741 |
| XMLRecord | 11,920 | Addon | 620 |
| Folder | 6,720 | ControllerMethod+Route | 488 |
| Asset | 6,114 | ControllerMethod | 249 |
| XMLRecord+View | 3,401 | Controller | 155 |
| QWebTemplate | 2,876 | AssetBundle | 94 |

This is too large to finish in one sitting. Prefer working through one label at a time (see the query
below) so a session's worth of work is a coherent, resumable slice — check with whoever's driving this
before churning through the highest-volume, lowest-signal labels (`File`, `Folder`) if the goal is
depth on code behavior rather than raw coverage.

### How to talk to Neo4j — SEARCH and UPDATE only, nothing else

Use only the two tools on the **`neo4j-database`** MCP server below (Claude Code prefixes them
`mcp__neo4j-database__read_neo4j_cypher` / `mcp__neo4j-database__write_neo4j_cypher`; other MCP
clients may use the bare names). Do **not** use the `neo4j-memory` server (`read_graph`,
`find_memories_by_name`, `add_observations`, `create_entities`, ...) for this task — that server's
graph is a separate, empty, generic entity/observation store and has nothing to do with the Odoo
architecture graph. `get_neo4j_schema` is unavailable here (this instance has no APOC plugin
installed) — use `read_neo4j_cypher` for schema discovery too, if ever needed.

**SEARCH — find nodes still missing context, one label at a time:**

Tool: `read_neo4j_cypher`
```json
{
  "query": "MATCH (n:ModelMethod) WHERE n.context IS NULL OR n.context = '' RETURN elementId(n) AS id, labels(n) AS labels, n LIMIT 10"
}
```

Swap the label (`ModelMethod`, `PythonModel`, `Controller`, `ControllerMethod`, `Function`,
`QWebTemplate`, `XMLRecord`, `JSComponent`, `Addon`, `AssetBundle`, `Asset`, `Folder`, `File`,
`ModelField`) to choose which slice to work through. Drop the label entirely
(`MATCH (n) WHERE ...`) only if you deliberately want a mixed batch across all label types.

You do **not** need `SKIP`/pagination bookkeeping: once a node's `context` is set (via the UPDATE step
below), it stops matching `context IS NULL OR context = ''`, so simply re-running the exact same query
after each processed batch naturally returns the next 10 unprocessed nodes. Re-running with the same
`LIMIT 10` and no offset is correct and expected.

Each returned row's `id` (an `elementId(n)` string, e.g. `"4:e179a577-119d-49cc-9910-746aa300882b:0"`)
is only valid for the current database session — always get it fresh from a `read_neo4j_cypher` call
in this session, never reuse an `id` string left over from an earlier conversation or from this
document.

Use the returned `filePath` (and `fileLine` when present) property on `n` to go read the real source
before writing `context`. For code-bearing labels (`ModelMethod`, `Function`, `ControllerMethod`,
`PythonModel`, `Controller`) that's a Python file; for `QWebTemplate`/`XMLRecord` it's XML; for
`JSComponent` it's JS/OWL.

**UPDATE — batch-set `context` on those same nodes by `elementId`:**

Tool: `write_neo4j_cypher`
```json
{
  "query": "UNWIND $rows AS row MATCH (n) WHERE elementId(n) = row.id SET n.context = row.context",
  "params": {
    "rows": [
      {
        "id": "4:e179a577-119d-49cc-9910-746aa300882b:0",
        "context": "Confirms the order, generates a procurement group + stock pickings via _action_launch_stock_rule, and posts the analytic entries; the docstring already says 'Confirm the given quotation(s)' so this adds the side effects it doesn't mention."
      }
    ]
  }
}
```

Rules for the update call:
- `id` values must come verbatim from `elementId(n)` returned by the search step in this same session
  — never invent one.
- `params.rows` can cover the whole batch of up to 10 nodes in one call — no need to call
  `write_neo4j_cypher` once per node.
- The query must only ever be this `SET n.context = row.context` shape (see the DO NOT section above)
  — no other clauses, no other properties, no `DELETE`/`REMOVE`/`CREATE`/`MERGE`.

### Batch size — 10 rows per pass, then repeat

**Rule: never pull more than 10 candidate nodes into a single working batch.** Call
`read_neo4j_cypher` with `LIMIT 10` (optionally filtered to one label, see above), fully process that
batch — read each node's real source, write one `context` string per node — then send all 10 in a
single `write_neo4j_cypher` call. Only then re-run the same `read_neo4j_cypher` query for the next 10
(it will naturally skip everything already processed, since those nodes no longer match
`context IS NULL OR context = ''`). Do not try to write context for more than 10 nodes before calling
`write_neo4j_cypher`, and do not batch multiple `write_neo4j_cypher` calls' worth of reasoning before
sending the first one.
