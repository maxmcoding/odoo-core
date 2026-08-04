# TASK: Build a Neo4j Knowledge Graph for Odoo Addons

You are an expert Odoo Architect and Graph Database Engineer.

### PRIMARY OBJECTIVE
Construct an explicit Entity-Relationship Graph directly inside Neo4j representing the architecture, components, and assets of **every** Odoo addon in the repository. Every file read must be immediately converted into Neo4j Nodes (Entities) and Edges (Relationships). The graph must support searching by a single semantic node type (e.g. `:Controller`, `:PythonModel`, `:View`) and immediately seeing which addon owns it and how it connects to the rest of the codebase — across all addons, not just within one.

Target Directory (scan root — each immediate subfolder with a `__manifest__.py` is one addon):
`/home/max/MisProyectos/odoo_plugins/odoo-core/addons/`

---

### STRICT RULES & CONSTRAINTS

0. **CONSTRAINTS BEFORE DATA (CRITICAL):** Before scanning a single file, issue the uniqueness constraints in the "IDENTITY & UNIQUENESS" section below. This is what makes it safe to scan 600+ addons that all touch the same core models (`res.partner`, `sale.order`, ...) without exploding them into duplicate nodes.

1. **ADDON-FIRST WORKFLOW RULE (CRITICAL):** For each addon folder, before reading any of its files:
   - Parse `__manifest__.py` and `MERGE` the `:Addon` node keyed on its technical name (the folder name, e.g. `web`, `web_editor`, `web_hierarchy` — NOT the human-readable `name` field inside the manifest, which goes in `displayName`).
   - For every entry in `depends`, `MERGE` a placeholder `:Addon` node for that dependency (it may not be scanned yet) and create `(:Addon)-[:DEPENDS_ON]->(:Addon)`.

2. **PYTHON FILE SYNCHRONOUS WORKFLOW RULE (CRITICAL):**
   When analyzing any `.py` file, you MUST immediately extract and generate all Cypher queries to create:
   - The `:File` node and its containing `:Folder` relationship.
   - All `:PythonModel` nodes defined inside it (`_name`, `_inherit`) — `MERGE` keyed on the technical model name (e.g. `res.partner`), never `CREATE`, since dozens of addons touch the same model.
   - All `:ModelField` and `:ModelMethod` nodes.
   - Any `http.Controller` (or bare `Controller`) subclass as a `:Controller` node, and **every** method defined on it as a `:ControllerMethod` node (route-decorated ones additionally get the `:Route` label — see nomenclature below).
   - All relationships to other models, controllers, and views where detectable.

   **DO NOT proceed to read or analyze the next file until all Neo4j Entity and Relationship creation queries for the current file are generated and executed.**

3. **Scope Restriction:** STRICTLY read and analyze files within `/home/max/MisProyectos/odoo_plugins/odoo-core/addons/`. DO NOT inspect, traverse, or query any files or folders outside this exact path.

4. **Read-Only Operation:** NEVER create, modify, move, or delete any local files or directories within the target filesystem.

5. **Large File Strategy (`.xml`):** Process record-by-record (`<record id="...">`) and template-by-template (`<template id="...">` / QWeb). Immediately write each entity and its links to Neo4j before continuing to the next record. A `<record>` whose `model` attribute is `ir.ui.view` gets the extra `:View` label on top of `:XMLRecord` (see nomenclature below).

---

### NODE & RELATIONSHIP NOMENCLATURE (Neo4j best practices)

Sources: [Cypher Manual — Naming rules and recommendations](https://neo4j.com/docs/cypher-manual/current/syntax/naming/), [Neo4j — Generic/vague relationship names](https://neo4j.com/blog/neo4j-genericvague-relationship-names/), [Neo4j Graph Data Modeling guidelines](https://neo4j.com/docs/getting-started/data-modeling/).

- **Node labels → `UpperCamelCase`, singular noun.** `:Addon`, `:Controller`, `:PythonModel` — never `:addons`, `:controllers`.
- **Relationship types → `UPPER_SNAKE_CASE`, verb phrase, and as specific as possible.** Prefer `DEPENDS_ON`, `DEFINES_MODEL`, `CALLS_METHOD` over vague catch-alls like `RELATES_TO` or `HAS`. Neo4j explicitly calls out generic relationship names as an anti-pattern: they force every query to filter after the fact instead of traversing only what's relevant. `RELATES_TO` is kept below only for the one case where the target type is genuinely unbounded (Many2one/Many2many field targets) — see note under Relationships.
- **Property keys → `lowerCamelCase`.** `technicalName`, `qualifiedName`, `authType` — not `technical_name`.
- **Multi-label nodes are how cross-addon search works.** A view record is `(:XMLRecord:View)`, a controller class is `(:File:Controller)`. `MATCH (c:Controller)` then returns controllers from all ~620 addons in one query, and each is still reachable to its owning `:Addon`, `:File`, and `:Folder` — this is what satisfies "search node `Controller` and see its relations."
- **`:Folder` is NOT the category system.** Don't invent a `:Folder` subtype per role. Odoo already gives you the role for free via the folder's `name` (`controllers`, `models`, `views`, `static`, `security`, `data`, `i18n`, `tests`). Keep `:Folder {name, path}` purely structural and put the query-relevant label on the entity the folder contains (previous bullet).

#### Identity & uniqueness (critical at 620-addon scale)
Every label needs one globally-unique, stable key property, and every write must use `MERGE` on that key — never `CREATE` — or a model touched by 50 addons (e.g. `res.partner`) becomes 50 duplicate nodes.

| Label | Unique key | Example |
|---|---|---|
| `:Addon` | `name` (technical/folder name) | `web`, `web_editor` |
| `:Folder` | `path` | `.../web/controllers` |
| `:File` | `path` | `.../web/controllers/main.py` |
| `:PythonModel` | `technicalName` | `res.partner` |
| `:ModelField` | `qualifiedName` = `{technicalName}.{fieldName}` | `res.partner.vat` |
| `:ModelMethod` | `qualifiedName` = `{technicalName}#{methodName}` | `res.partner#write` |
| `:Controller` | `qualifiedName` = `{addon}.{modulePath}.{ClassName}` | `web.controllers.main.Home` |
| `:ControllerMethod` (`:Route` is an extra label on the same node, not a separate key scheme) | `qualifiedName` = `{controllerQualifiedName}#{methodName}` | `web.controllers.main.Home#web_login` |
| `:XMLRecord` / `:View` | `xmlId` (fully qualified) | `web.login_layout` |
| `:QWebTemplate` | `xmlId` | `web.layout` |
| `:JSComponent` | `qualifiedName` = `{path}::{name}` | |
| `:Asset` | `path` | |
| `:AssetBundle` | `name` | `web.assets_backend` |

Run once, before scanning anything:
```cypher
CREATE CONSTRAINT addon_name      IF NOT EXISTS FOR (a:Addon)       REQUIRE a.name IS UNIQUE;
CREATE CONSTRAINT folder_path     IF NOT EXISTS FOR (f:Folder)      REQUIRE f.path IS UNIQUE;
CREATE CONSTRAINT file_path       IF NOT EXISTS FOR (f:File)        REQUIRE f.path IS UNIQUE;
CREATE CONSTRAINT model_name      IF NOT EXISTS FOR (m:PythonModel) REQUIRE m.technicalName IS UNIQUE;
CREATE CONSTRAINT field_qn        IF NOT EXISTS FOR (f:ModelField)  REQUIRE f.qualifiedName IS UNIQUE;
CREATE CONSTRAINT method_qn       IF NOT EXISTS FOR (m:ModelMethod) REQUIRE m.qualifiedName IS UNIQUE;
CREATE CONSTRAINT controller_qn   IF NOT EXISTS FOR (c:Controller)  REQUIRE c.qualifiedName IS UNIQUE;
CREATE CONSTRAINT ctrl_method_qn  IF NOT EXISTS FOR (m:ControllerMethod) REQUIRE m.qualifiedName IS UNIQUE;
CREATE CONSTRAINT xmlrecord_id    IF NOT EXISTS FOR (x:XMLRecord)   REQUIRE x.xmlId IS UNIQUE;
CREATE CONSTRAINT qweb_id         IF NOT EXISTS FOR (q:QWebTemplate) REQUIRE q.xmlId IS UNIQUE;
CREATE CONSTRAINT asset_path      IF NOT EXISTS FOR (a:Asset)       REQUIRE a.path IS UNIQUE;
CREATE CONSTRAINT bundle_name      IF NOT EXISTS FOR (b:AssetBundle) REQUIRE b.name IS UNIQUE;
```

---

### NEO4J GRAPH MODEL SPECIFICATION

#### Nodes (Entities)
- `:Addon` — `{name, displayName, path, version, category, autoInstall}`
- `:Folder` — `{path, name}`
- `:File` — `{path, filename, extension, size}`
- `:PythonModel` — `{technicalName, description}`
- `:ModelField` — `{qualifiedName, name, type, relationModel}`
- `:ModelMethod` — `{qualifiedName, name, apiDecorators}`
- `:Controller` — `{qualifiedName, className, parentController}`
- `:ControllerMethod` — `{qualifiedName, name}` — every method defined on a `:Controller` class, no exceptions. `@http.route`-decorated ones additionally carry the `:Route` label + `{httpPath, methods, authType, csrf}` on that *same* node — a route is a method with extra facts, not a second entity.
- `:XMLRecord` — `{xmlId, model, noupdate}`
- `:View` — extra label on `:XMLRecord` where `model = 'ir.ui.view'`; adds `{viewType}`
- `:QWebTemplate` — `{xmlId, inheritId, primary}`
- `:JSComponent` — `{qualifiedName, name, owlType, extends}`
- `:Asset` — `{path, type, name}` *(the "static" category — no separate `:Static` label needed)*
- `:AssetBundle` — `{name}` *(a manifest `assets` dict key, e.g. `web.assets_backend`; keyed on its own fully-qualified name)*

#### Relationships (Edges)
- `(:Addon)-[:DEPENDS_ON]->(:Addon)` — from `__manifest__.py` `depends`
- `(:Addon)-[:CONTAINS_FOLDER]->(:Folder)` — addon's root-level folders
- `(:Folder)-[:CONTAINS]->(:File|:Folder)`
- `(:File)-[:DEFINES]->(:PythonModel|:XMLRecord|:QWebTemplate|:JSComponent|:Asset|:Controller)`
- `(:PythonModel)-[:HAS_FIELD]->(:ModelField)`
- `(:PythonModel|:Controller)-[:HAS_METHOD]->(:ModelMethod|:ControllerMethod)` — every method is a sub-node of its container, always, regardless of file type. A route is a `:ControllerMethod` that also carries the `:Route` label — there is no separate edge for "this controller has this route," `HAS_METHOD` already says it.
- `(:Addon)-[:DEFINES_MODEL]->(:PythonModel)` — the addon that first declares `_name`
- `(:Addon)-[:EXTENDS_MODEL]->(:PythonModel)` — every addon that only declares `_inherit` on an existing technical name (the common case — no new node, same `:PythonModel`)
- `(:PythonModel)-[:INHERITS_MODEL]->(:PythonModel)` — classical inheritance into a genuinely new model (`_name` set AND different from `_inherit`)
- `(:PythonModel)-[:DELEGATES_TO]->(:PythonModel)` — delegation inheritance (`_inherits = {...}`)
- `(:PythonModel)-[:RELATES_TO {via: fieldName, kind: "many2one"|"many2many"|"one2many"}]->(:PythonModel)` — Many2one/Many2many/One2many field targets. Field names are unbounded across 620 addons, so this is the one deliberate exception to "no generic relationship types": keep ONE type and put the variable part (`via`, `kind`) as properties, per Neo4j's own guidance on not exploding the relationship-type vocabulary.
- `(:XMLRecord)-[:TARGETS_MODEL]->(:PythonModel)`
- `(:XMLRecord)-[:INHERITS_VIEW]->(:XMLRecord)`
- `(:QWebTemplate)-[:EXTENDS_TEMPLATE]->(:QWebTemplate)`
- `(:File)-[:IMPORTS]->(:File)`
- `(:ModelMethod|:ControllerMethod)-[:USES_MODEL]->(:PythonModel)` — `self.env[...]` / `request.env[...]` found inside *that specific method's* body — not a controller-level guess, the exact method that does it
- `(:ModelMethod|:ControllerMethod)-[:RENDERS_TEMPLATE]->(:QWebTemplate)` — `self._render(...)` / `request.render(...)` / `self.env['ir.qweb']._render(...)` found inside that method's body
- `(:ModelMethod|:ControllerMethod)-[:CALLS_METHOD]->(:ModelMethod|:ControllerMethod)` — a call into another known method, from either side (route calling a model method, or vice versa)
- `(:Controller)-[:EXTENDS_CONTROLLER]->(:Controller)` — Python class inheritance between controllers
- `(:Addon)-[:DEFINES_BUNDLE]->(:AssetBundle)` — each key of the manifest's `assets` dict
- `(:AssetBundle)-[:INCLUDES_BUNDLE]->(:AssetBundle)` — `('include', 'other.bundle')` entries; this is a real dependency graph in the manifest (e.g. `{addon}.assets_web` → `{addon}.assets_backend` → `{addon}._assets_helpers` → `{addon}._assets_primary_variables`) and is worth its own edge rather than being flattened away
- `(:AssetBundle)-[:INCLUDES_ASSET]->(:Asset)` — plain file entries inside a bundle
- `(:JSComponent)-[:RENDERS_TEMPLATE]->(:QWebTemplate)` — from `static template = "..."` on an OWL `Component`; same relationship type as the method-level rule above, just a different source label — a template render is a template render regardless of what's doing the rendering
- `(:JSComponent)-[:USES_COMPONENT]->(:JSComponent)` — from `static components = {...}`

> **Controller-detection gotcha found while scanning `{addon}`:** Odoo controllers subclass either `http.Controller` (`class Home(http.Controller)`) or a bare `Controller` imported directly (`from odoo.http import Controller` → `class Domain(Controller)`) — both are the same base class. A detector matching only `(http.Controller)` misses ~25% of controllers. Match both spellings.

---

### STEP-BY-STEP EXECUTION PROTOCOL

1. **Setup:** Run the uniqueness constraints from "IDENTITY & UNIQUENESS."
2. **Addon Discovery Loop:** For each immediate subfolder of the target directory containing a `__manifest__.py`:
   - Parse the manifest, `MERGE` the `:Addon` node with its properties.
   - `MERGE` a `:DEPENDS_ON` edge to every addon listed in `depends` (the target `:Addon` node may just be a placeholder until its own turn in this loop — that's expected).
3. **File Processing Loop (per addon, file-by-file):**
   - Read item → Extract Entities & Relations → Write Cypher to Neo4j → Confirm persistence → Load next item.
   - Apply the semantic label (`:Controller`, `:View`, ...) at write time, not as a later pass.
   - Exception for very large static folders (2,000+ files is common — see the extraction rulebook below): batch by subdirectory instead of one tool-call per file, but still write one `:File`/`:Asset`/`:JSComponent` node per actual file — batching is about read I/O, not about skipping entities.

---

### FILE-TYPE EXTRACTION RULEBOOK (generalized — apply to every addon)

This was derived by actually reading a real addon's `controllers/`, `models/`, `views/`, `security/`, `data/`, and manifest `assets` block file-by-file (`static/` was sampled, not read whole — 2,058 files in that case). It is written as a standing procedure — apply it identically to every addon you scan. Examples below use `{addon}` as a stand-in for whichever addon's technical name you're currently processing (e.g. `web`, `web_editor`, `sale`, ...). The worked Cypher below shows exactly what this produces on real files.

**Cross-cutting rule — methods are always sub-nodes, and their bodies always get scanned for references.**
Whatever the container — `:Controller` or `:PythonModel` — every method defined inside it becomes its own node connected by `HAS_METHOD`. It is never flattened into a property on the container. Once that method node exists, scan its *body* (not just its signature) for three things, every time, regardless of which kind of container it came from:
1. `self.env[...]` / `request.env[...]` → `-[:USES_MODEL]->(:PythonModel)`
2. `self._render(...)` / `request.render(...)` / `self.env['ir.qweb']._render(...)` → `-[:RENDERS_TEMPLATE]->(:QWebTemplate)`
3. a call into another known method on `self`/`super()` → `-[:CALLS_METHOD]->(:ModelMethod|:ControllerMethod)`

**1. Controller files (`controllers/*.py`)**
- A class subclassing `http.Controller` OR a bare `Controller` (`from odoo.http import Controller` — same base class, both spellings must be matched or ~25% of controllers get missed, as happened on the first pass over `{addon}`) → `(:File)-[:DEFINES]->(:Controller {qualifiedName, className})`.
- Every method on that class, no exceptions → `(:Controller)-[:HAS_METHOD]->(:ControllerMethod {qualifiedName, name})`, keyed `{controllerQualifiedName}#{methodName}`.
- If it carries `@http.route(...)`, stack the extra label `:Route` on that *same* node and set `{httpPath, methods, authType, csrf}` from the decorator args — don't create a second node for it.
- Run the cross-cutting body-scan rule on every `:ControllerMethod`/`:Route` node.
- Real example (from `{addon}` = `web`): `Home.web_login` (`controllers/home.py:97`) → `(:ControllerMethod:Route {qualifiedName:"{addon}.controllers.home.Home#web_login", httpPath:"/web/login"})`. Its body has both `request.env["ir.http"]` → `USES_MODEL` → `ir.http`, and `request.render('web.login', values)` → `RENDERS_TEMPLATE` → `{addon}.login`. A plain method like `Home._login_redirect` (no decorator) gets a `:ControllerMethod` node with no `:Route` label and no template/model edges — that's fine, not every method has to hit something.

**2. Model files (`models/*.py`)**
- Class with `_name`/`_inherit` → `:PythonModel`, `MERGE`d on `technicalName`, never `CREATE`. `_name == _inherit` (seen in `ir_qweb_fields.py`) is still `EXTENDS_MODEL`, not a new model — only a `_name` that *differs* from `_inherit` is `INHERITS_MODEL`.
- Fields → `(:PythonModel)-[:HAS_FIELD]->(:ModelField)`. Relational fields (Many2one/One2many/Many2many) additionally get `(:PythonModel)-[:RELATES_TO {via, kind}]->(:PythonModel)` on the container — a field relation is a fact about the model, not about one method.
- Methods → `(:PythonModel)-[:HAS_METHOD]->(:ModelMethod)`, same cross-cutting body-scan rule as controllers, no special-casing. Real example: `base_document_layout.py#_get_asset_style` calls `self.env['ir.qweb']._render('{addon}.styles_company_report', ...)` — one method, both a `USES_MODEL` edge (`ir.qweb`) and a `RENDERS_TEMPLATE` edge (`{addon}.styles_company_report`) fire off the same line.
- Expect `EXTENDS_MODEL` to dominate `DEFINES_MODEL` in most non-`base` addons — `{addon}` (`web`, in the real scan behind this rule) extends 9 core models (`res.partner`, `res.users`, `ir.ui.menu`, `ir.ui.view`, `ir.http`, `ir.model`, `res.company`, `base`, `res.config.settings`) and only truly defines one (`base.document.layout`, a `TransientModel`).

**3. View/template files (`views/*.xml`, `data/*.xml`)**
- `<record id="..." model="...">` → `:XMLRecord`, `xmlId = "{addon}.{id}"`. `model="ir.ui.view"` → add the extra `:View` label. The `model` attribute always → `-[:TARGETS_MODEL]->(:PythonModel)`; an `inherit_id` attribute → `-[:INHERITS_VIEW]->(:XMLRecord)`.
- `<template id="...">` → `:QWebTemplate` — a *different* node than `:XMLRecord:View`, even though both compile to `ir.ui.view` at runtime, because that's how the addon's own source separates them (`{addon}` keeps QWeb templates in `<template>` blocks and actual view records in `<record model="ir.ui.view">` blocks). `inherit_id` → `-[:EXTENDS_TEMPLATE]->(:QWebTemplate)`.
- Plain data records (`ir.attachment`, `report.layout`, `ir.actions.*`, ...) are still just `:XMLRecord` without the `:View` label — same rule, no extra case to write.

**4. Static/JS files (`static/src/**/*.js`)**
- `class X extends Component` → `:JSComponent`. `static template = "xml.id"` → `-[:RENDERS_TEMPLATE]->(:QWebTemplate)` (same relationship type as the method-level rule — a render is a render). `static components = {...}` → `-[:USES_COMPONENT]->(:JSComponent)` per entry. `import {...} from "..."` → `(:File)-[:IMPORTS]->(:File)`.
- Batch-read by subdirectory instead of one tool call per file — `{addon}/static/` can easily be 2,000+ files (it was 2,058 in the real scan behind this rule), and scanning it one file at a time the way `controllers/`/`models/` were scanned would dominate the whole run. Batching is about read I/O only: still emit one node per real file.

**5. Security (`security/*.csv`) and the manifest `assets` block**
- `ir.model.access.csv` rows describe access on an existing `:PythonModel`, not a new node type — skip unless a future query specifically needs per-group access rules.
- The manifest's `assets` dict is a real dependency graph, not a flat file list — e.g. `{addon}.assets_web` → includes → `{addon}.assets_backend` → includes → `{addon}._assets_helpers` → includes → `{addon}._assets_primary_variables` / `{addon}._assets_secondary_variables` (4 levels deep, ~40 named bundles total in the real manifest this was read from). Use `:AssetBundle` + `INCLUDES_BUNDLE`/`INCLUDES_ASSET`, per the model spec above, instead of flattening it into plain `:Asset` nodes.

---

### WORKED EXAMPLE — Cypher for a real addon's entities (shown as `{addon}`)

Grounded in files actually read from one real addon (`web`) — `{addon}` stands in for its technical name throughout so this reads as a reusable pattern, not a one-off report about a single module. Use it as the template for every addon you scan. `...` stands for the repo-absolute prefix `/home/max/MisProyectos/odoo_plugins/odoo-core/addons`.

```cypher
// --- Addon + dependency ---
MERGE (addon:Addon {name: "{addon}"})
  SET addon.displayName = "Example Module", addon.path = ".../{addon}",
      addon.version = "1.0", addon.category = "Hidden", addon.autoInstall = true;
MERGE (base:Addon {name: "base"});                             // every addon ultimately depends on base
MERGE (addon)-[:DEPENDS_ON]->(base);

// --- Folder + File: controllers/home.py ---
MERGE (fdControllers:Folder {path: ".../{addon}/controllers"}) SET fdControllers.name = "controllers";
MERGE (addon)-[:CONTAINS_FOLDER]->(fdControllers);
MERGE (fHome:File {path: ".../{addon}/controllers/home.py"})
  SET fHome.filename = "home.py", fHome.extension = "py";
MERGE (fdControllers)-[:CONTAINS]->(fHome);

// --- Controller + methods: Home.web_login (route) and Home._login_redirect (plain) ---
MERGE (cHome:Controller {qualifiedName: "{addon}.controllers.home.Home"}) SET cHome.className = "Home";
MERGE (fHome)-[:DEFINES]->(cHome);
MERGE (mLogin:ControllerMethod:Route {qualifiedName: "{addon}.controllers.home.Home#web_login"})
  SET mLogin.name = "web_login", mLogin.httpPath = "/web/login",
      mLogin.methods = ["GET","POST"], mLogin.authType = "none", mLogin.csrf = true;
MERGE (cHome)-[:HAS_METHOD]->(mLogin);
MERGE (mIrHttp:PythonModel {technicalName: "ir.http"});
MERGE (mLogin)-[:USES_MODEL]->(mIrHttp);                      // request.env["ir.http"]...
MERGE (tLoginPage:QWebTemplate {xmlId: "{addon}.login"});
MERGE (mLogin)-[:RENDERS_TEMPLATE]->(tLoginPage);              // request.render('{addon}.login', values)

MERGE (mRedirect:ControllerMethod {qualifiedName: "{addon}.controllers.home.Home#_login_redirect"})
  SET mRedirect.name = "_login_redirect";
MERGE (cHome)-[:HAS_METHOD]->(mRedirect);                      // plain helper method, no :Route label

// --- PythonModel: EXTENDS_MODEL example (models/res_partner.py) ---
MERGE (fPartner:File {path: ".../{addon}/models/res_partner.py"})
  SET fPartner.filename = "res_partner.py", fPartner.extension = "py";
MERGE (mPartner:PythonModel {technicalName: "res.partner"});
MERGE (addon)-[:EXTENDS_MODEL]->(mPartner);
MERGE (fPartner)-[:DEFINES]->(mPartner);
MERGE (meth:ModelMethod {qualifiedName: "res.partner#_build_vcard"}) SET meth.name = "_build_vcard";
MERGE (mPartner)-[:HAS_METHOD]->(meth);

// --- PythonModel: DEFINES_MODEL example (models/base_document_layout.py, TransientModel) ---
MERGE (fLayout:File {path: ".../{addon}/models/base_document_layout.py"});
MERGE (mLayout:PythonModel {technicalName: "base.document.layout"})
  SET mLayout.description = "Company Document Layout";
MERGE (addon)-[:DEFINES_MODEL]->(mLayout);
MERGE (fLayout)-[:DEFINES]->(mLayout);
MERGE (fldCompany:ModelField {qualifiedName: "base.document.layout.company_id"})
  SET fldCompany.name = "company_id", fldCompany.type = "many2one";
MERGE (mLayout)-[:HAS_FIELD]->(fldCompany);
MERGE (mCompany:PythonModel {technicalName: "res.company"});
MERGE (mLayout)-[:RELATES_TO {via: "company_id", kind: "many2one"}]->(mCompany);
// same cross-cutting method rule applies to :ModelMethod, not just :ControllerMethod:
MERGE (mAssetStyle:ModelMethod {qualifiedName: "base.document.layout#_get_asset_style"})
  SET mAssetStyle.name = "_get_asset_style";
MERGE (mLayout)-[:HAS_METHOD]->(mAssetStyle);
MERGE (mIrQweb:PythonModel {technicalName: "ir.qweb"});
MERGE (mAssetStyle)-[:USES_MODEL]->(mIrQweb);                  // self.env['ir.qweb']...
MERGE (tStyles:QWebTemplate {xmlId: "{addon}.styles_company_report"});
MERGE (mAssetStyle)-[:RENDERS_TEMPLATE]->(tStyles);            // ..._render('{addon}.styles_company_report', ...)

// --- XMLRecord + View: views/base_document_layout_views.xml ---
MERGE (fViewXml:File {path: ".../{addon}/views/base_document_layout_views.xml"});
MERGE (vLayout:XMLRecord:View {xmlId: "{addon}.view_base_document_layout"})
  SET vLayout.model = "base.document.layout", vLayout.viewType = "form";
MERGE (fViewXml)-[:DEFINES]->(vLayout);
MERGE (vLayout)-[:TARGETS_MODEL]->(mLayout);

// --- QWebTemplate + EXTENDS_TEMPLATE: views/webclient_templates.xml ---
MERGE (fTemplXml:File {path: ".../{addon}/views/webclient_templates.xml"});
MERGE (tLayout:QWebTemplate {xmlId: "{addon}.layout"}) SET tLayout.primary = true;
MERGE (tFrontend:QWebTemplate {xmlId: "{addon}.frontend_layout"}) SET tFrontend.primary = true;
MERGE (fTemplXml)-[:DEFINES]->(tLayout);
MERGE (fTemplXml)-[:DEFINES]->(tFrontend);
MERGE (tFrontend)-[:EXTENDS_TEMPLATE]->(tLayout);

// --- JSComponent: static/src/webclient/webclient.js ---
MERGE (fWebclientJs:File {path: ".../{addon}/static/src/webclient/webclient.js"});
MERGE (jsWebClient:JSComponent {qualifiedName: ".../{addon}/static/src/webclient/webclient.js::WebClient"})
  SET jsWebClient.name = "WebClient", jsWebClient.owlType = "Component", jsWebClient.extends = "Component";
MERGE (fWebclientJs)-[:DEFINES]->(jsWebClient);
MERGE (tWebClientTemplate:QWebTemplate {xmlId: "{addon}.WebClient"});
MERGE (jsWebClient)-[:RENDERS_TEMPLATE]->(tWebClientTemplate);

// --- AssetBundle graph (from __manifest__.py 'assets') ---
MERGE (bAssetsWeb:AssetBundle {name: "{addon}.assets_web"});
MERGE (bBackend:AssetBundle {name: "{addon}.assets_backend"});
MERGE (bHelpers:AssetBundle {name: "{addon}._assets_helpers"});
MERGE (bPrimaryVars:AssetBundle {name: "{addon}._assets_primary_variables"});
MERGE (bSecondaryVars:AssetBundle {name: "{addon}._assets_secondary_variables"});
MERGE (addon)-[:DEFINES_BUNDLE]->(bAssetsWeb);
MERGE (addon)-[:DEFINES_BUNDLE]->(bBackend);
MERGE (addon)-[:DEFINES_BUNDLE]->(bHelpers);
MERGE (bAssetsWeb)-[:INCLUDES_BUNDLE]->(bBackend);
MERGE (bBackend)-[:INCLUDES_BUNDLE]->(bHelpers);
MERGE (bHelpers)-[:INCLUDES_BUNDLE]->(bPrimaryVars);
MERGE (bHelpers)-[:INCLUDES_BUNDLE]->(bSecondaryVars);
```

**What this buys you:** `MATCH (r:Route {httpPath: "/web/login"})<-[:HAS_METHOD]-(c:Controller) RETURN c, r` finds the login route from a cold search on the label `Route` alone, without knowing it lives in `{addon}/controllers/home.py` — and one more hop, `MATCH (r:Route {httpPath: "/web/login"})-[:USES_MODEL|RENDERS_TEMPLATE]->(x) RETURN x`, shows exactly which model and which template that one route touches. That's the "search node `controller`, see its relations" behavior asked for, down to method granularity. The same label-first pattern is what makes `MATCH (m:PythonModel {technicalName: "res.partner"})<-[:EXTENDS_MODEL]-(a:Addon) RETURN a.name` a one-hop way to list every addon that touches `res.partner`, across all 620 addons once the full scan runs.
