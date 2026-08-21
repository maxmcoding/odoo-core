
## GOAL

- Get object with empty context, 
- then  read file reference on filePath and fileLine 
- with that info analize and generate context 
- save context on node
- Use `neo4j-database`
- only use provide query  like examples
- if write_neo4j_cypher fail, use validate_json

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

Keep it to 4–8 sentences. Be objetive to what you read in the code.

**Never pick a label** (`ModelMethod`, `XMLRecord`, etc.) because it seems "common" or "representative"
when the user didn't name one — that is a guess, and this task runs on verified facts, not guesses. If
the request doesn't specify a label, either ask which label is meant, or drop the label filter entirely
(`MATCH (n)` with no label in Step 1, still one shared `filePath` per cycle)
- every unprocessed node is still sitting there waiting, nothing to track or resume from
manually.

### How to talk to Neo4j — SEARCH and UPDATE only, nothing else

**SEARCH** = `read_neo4j_cypher`, for Step 1 only. It is strictly **MATCH-only**: the server does a
text-level check and hard-rejects any query containing a write clause (`SET`, `CREATE`, `MERGE`,
`DELETE`, `REMOVE`, `DROP`) — even one merely prefixed with `EXPLAIN` — with
`Only MATCH queries are allowed for read-query`. Never route Step 3's `SET` through it.

**UPDATE** = `write_neo4j_cypher`, for Step 3 only. It's the only tool allowed to execute the
`SET n.context = ...` query — never call it for anything but that (see the DO NOT section above). If
you're ever unsure which of the two a query belongs to, scan it for write keywords first: any hit means
`write_neo4j_cypher`, no exceptions.

Use only the two tools on the **`neo4j-database`** MCP server below (Claude Code prefixes them
`mcp__neo4j-database__read_neo4j_cypher` / `mcp__neo4j-database__write_neo4j_cypher`; other MCP
clients may use the bare names). Do **not** use the `neo4j-memory` server (`read_graph`,
`find_memories_by_name`, `add_observations`, `create_entities`, ...) for this task — that server's
graph is a separate, empty, generic entity/observation store and has nothing to do with the Odoo
architecture graph. `get_neo4j_schema` is unavailable here (this instance has no APOC plugin
installed) — use `read_neo4j_cypher` for schema discovery too, if ever needed.

### The enforced — batched by shared file, capped

**Performance rule:** many `ModelMethod`/`ModelField`/`XMLRecord`/`Function` nodes point at the *same*
`filePath` (e.g. a model file with 20 methods). Re-opening that file once per node is the main reason
this was slow. Instead, pull every empty-context node that shares one file, read that file **once**,
and write all of their `context` values back in a **single** batched query. Never batch across
*different* files — one `filePath` per cycle, always.

**Step 1 — SEARCH: get one filePath's worth of candidates, capped.**

Tool: `read_neo4j_cypher`
```json
{
  "query": "MATCH (n) WHERE NOT 'ModelField' IN labels(n) AND n.filePath IS NOT NULL AND (n.context = "" OR n.context IS NULL) AND ANY(ext IN [".py", ".js", ".xml"] WHERE n.filePath ENDS WITH ext) RETURN  elementId(n) AS id, labels(n), n.context, n.description LIMIT 10"
}
```

Swap the label (`ModelMethod`, `PythonModel`, `Controller`, `ControllerMethod`, `Function`,
`QWebTemplate`, `XMLRecord`, `JSComponent`, `Addon`, `AssetBundle`, `Asset`, `Folder`, `File`) to choose which slice to work through; drop it from both `MATCH` clauses only if you
deliberately want to move through all label types mixed together (still one shared `filePath` per
cycle). The inner `LIMIT 10` caps batch size so one cycle stays reviewable — if a file has more than 10
matching nodes.

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
the Step 3 batch rather than guessing.

**Step 3 — WRITE: set `context` for the whole verified batch, nothing else.**

Tool: `write_neo4j_cypher`
```json
{
  "query": "UNWIND $updates AS u MATCH (n) WHERE elementId(n) = u.id SET n.context = u.context",
  "params": {
    "updates": [
      {
        "id": "4:e179a577-119d-49cc-9910-746aa300882b:208",
        "context": "Holds the OWL Colorpicker component (colorpicker.js), its QWeb template (colorpicker.xml) and styles (colorpicker.scss): a draggable hue/saturation/opacity picker with hex/rgb/hsl inputs, used wherever the web client needs a color-selection widget."
      },
      {
        "id": "4:e179a577-119d-49cc-9910-746aa300882b:209",
        "context": "Implements the domain/condition-tree editor UI: condition_tree.js defines the internal tree/condition/connector data model, tree_editor.js is the main OWL component that renders and diffs trees using ModelFieldSelector, and the remaining files (operator/value editors, autocomplete, utils) supply per-field-type operator and value widgets used to build Odoo domain expressions visually."
      }
    ]
  }
}
```
- Every `id` in `updates` must be an exact value Step 1 returned in *this* cycle's batch — never
  invented, never reused, and never a row you dropped for lack of a real look in Step 2.
- This exact shape only — no other clause, no other property, no `DELETE`/`REMOVE`/`CREATE`/`MERGE`
  (see the DO NOT section above). If `write_neo4j_cypher` fails, continue to the next step.



### Prevention Checklist (Do Before Each Tool Call):

__1. JSON Validation:__

- Verify complete, valid JSON with proper quoting and no trailing commas
- For Neo4j read/write tools: ensure exact shape `{ "query": "...", "params": {...} }`
- Double-check `write_neo4j_cypher` params follow documented structure
- for json call, always ensure that atributes empty be clean, Example  atibute tu prevent ({"\"": null} , {"":""}, {"*":""})
- Whenever you need to validate a JSON string (e.g. the `query`/`params` payload before calling
  `read_neo4j_cypher` or `write_neo4j_cypher`), you must validate it using the `json-validate` MCP tool
  — never the `jq` CLI. Follow these rules:

  1. Call `mcp__json-validate__validate_json` with the full JSON string as `json_text`. Example:
     ```json
     {
       "json_text": "{\"query\": \"UNWIND $updates AS u MATCH (n) WHERE elementId(n) = u.id SET n.context = u.context\", \"params\": {\"updates\": [{\"id\": \"4:e179a577-119d-49cc-9910-746aa300882b:0\", \"context\": \"...\"}]}}"
     }
     ```
  2. It returns `{"valid": true, "error": null}` on success, or `{"valid": false, "error": "..."}` on
     failure.
  3. If `valid` is `false`, review `error`, fix the structural issue in the string, and re-validate.
  4. When utilize the JSON data enforce to use `validate_json` returns `"valid": true`.

__2. Fresh Results Verification:__

- Never reuse node IDs from previous responses - always use fresh results
- Clear cached state before next query after successful writes
- Cross-reference file paths match between Step 1 and Step 2 queries

__3. File Path Handling (MCP filesystem-MisProyectos):__

- Use  read_text_file tool to read file content
- when node is type folder path put as context "folder"
- Verify file existence at intended path before reading

__4. MCP Server Selection:__

- Always use server name `neo4j-database` (not `neo4j-memory`)
- Confirm JSON matches documented schemas verbatim



### Think method 

You are a precise assistant. Before answering, write a brief internal thought process inside <scratch> tags. Keep your thoughts under 30 words, using shorthand or fragments. Then, provide the final answer immediately.

Protocol

For each file, follow this loop:

Classify complexity (silent, no output)
SIMPLE: single-purpose script, config, data file, or short module with an obvious role.
COMPLEX: multi-responsibility module, entry point, orchestrator, or file with non-obvious control flow / dependencies.
Reason before writing — Chain-of-Draft style, not Chain-of-Thought
SIMPLE files: skip reasoning, write the description directly.
COMPLEX files: reason in compressed drafts only — ≤5 words per step, symbols/keywords over prose, no restating the file content, no narrating your own process. Budget: ≤80 reasoning tokens per file. Stop as soon as the file's purpose and key behavior are clear.
If you need exact details (function signatures, imports, line counts), read them directly — do not guess or hallucinate content you have not seen.
Write the description
Medium length: 3–6 sentences, ~60–120 words. Not a one-liner, not a full walkthrough.
Cover, in order of priority: (a) what the file's primary responsibility is, (b) how it fits into the broader sequence of files if that's inferable, (c) any notable dependencies, side effects, or risks (e.g. writes to disk, calls external APIs, mutates shared state) — only if present and relevant.
No restating the reasoning trace. No filler openers ("This file is responsible for..." → just state it: "Handles...").
Do not quote large code blocks. Paraphrase; cite specific function/class names only when they aid clarity.
Move to the next file. Do not carry unnecessary context forward — only carry facts that affect interpretation of later files (e.g. a shared config schema, a naming convention, an established data flow).
Output format (repeat per file)
### {filename}
{medium-length description, 3–6 sentences}

No preamble before the first file. No summary after the last file unless explicitly requested.

Rules
Never fabricate file contents you have not actually read.
Never explain your SIMPLE/COMPLEX classification to the user.
Favor correctness over hitting the token budget exactly — the 80-token reasoning cap is a target, not a hard wall for genuinely ambiguous files.
If a file is unreadable, empty, or binary with no inspectable content, say so in one sentence instead of guessing.
Keep tone neutral and technical — no evaluative language ("great", "poorly written") unless explicitly asked for a code review.
Tuning notes
{80 tokens} reasoning cap and {3–6 sentences} output length are the two knobs to adjust per use case. Increase the reasoning cap for large/complex codebases; decrease output length if you need a quick index rather than a description.
For very large batches (50+ files), consider adding a running "context digest" (1–2 sentences) after every 10 files, so later descriptions can reference established patterns without re-deriving them from scratch.