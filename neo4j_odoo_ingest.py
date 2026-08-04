#!/usr/bin/env python3
"""Ingest one Odoo addon into Neo4j per the Odoo-addons knowledge graph spec."""
import ast
import os
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
from neo4j import GraphDatabase
from neo4j.exceptions import ConstraintError
import time


def with_retry(fn, *args, retries=6, **kwargs):
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except ConstraintError:
            if attempt == retries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "wnUcwWGRZa67fZH")
ROOT = Path("/home/max/MisProyectos/odoo_plugins/odoo-core/addons")

MODEL_BASES = {"Model", "TransientModel", "AbstractModel"}
SKIP_DEEP_JS_DIRS = {"lib"}  # vendored, not addon-authored

driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

CONSTRAINTS = [
    "CREATE CONSTRAINT addon_name IF NOT EXISTS FOR (a:Addon) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT folder_path IF NOT EXISTS FOR (f:Folder) REQUIRE f.path IS UNIQUE",
    "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
    "CREATE CONSTRAINT model_name IF NOT EXISTS FOR (m:PythonModel) REQUIRE m.technicalName IS UNIQUE",
    "CREATE CONSTRAINT field_qn IF NOT EXISTS FOR (f:ModelField) REQUIRE f.qualifiedName IS UNIQUE",
    "CREATE CONSTRAINT method_qn IF NOT EXISTS FOR (m:ModelMethod) REQUIRE m.qualifiedName IS UNIQUE",
    "CREATE CONSTRAINT controller_qn IF NOT EXISTS FOR (c:Controller) REQUIRE c.qualifiedName IS UNIQUE",
    "CREATE CONSTRAINT ctrl_method_qn IF NOT EXISTS FOR (m:ControllerMethod) REQUIRE m.qualifiedName IS UNIQUE",
    "CREATE CONSTRAINT xmlrecord_id IF NOT EXISTS FOR (x:XMLRecord) REQUIRE x.xmlId IS UNIQUE",
    "CREATE CONSTRAINT qweb_id IF NOT EXISTS FOR (q:QWebTemplate) REQUIRE q.xmlId IS UNIQUE",
    "CREATE CONSTRAINT asset_path IF NOT EXISTS FOR (a:Asset) REQUIRE a.path IS UNIQUE",
    "CREATE CONSTRAINT bundle_name IF NOT EXISTS FOR (b:AssetBundle) REQUIRE b.name IS UNIQUE",
    "CREATE CONSTRAINT jscomp_qn IF NOT EXISTS FOR (j:JSComponent) REQUIRE j.qualifiedName IS UNIQUE",
    "CREATE CONSTRAINT function_qn IF NOT EXISTS FOR (fn:Function) REQUIRE fn.qualifiedName IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX model_method_name IF NOT EXISTS FOR (m:ModelMethod) ON (m.name)",
    "CREATE INDEX ctrl_method_name IF NOT EXISTS FOR (m:ControllerMethod) ON (m.name)",
    "CREATE INDEX model_field_name IF NOT EXISTS FOR (f:ModelField) ON (f.name)",
    "CREATE INDEX function_name IF NOT EXISTS FOR (fn:Function) ON (fn.name)",
    "CREATE FULLTEXT INDEX code_descriptions IF NOT EXISTS "
    "FOR (n:ModelMethod|ControllerMethod|ModelField|Function|PythonModel|Controller) ON EACH [n.description]",
]


def setup_constraints():
    with driver.session() as s:
        for c in CONSTRAINTS:
            s.run(c)
        for i in INDEXES:
            s.run(i)
    print("Constraints + indexes ensured.")


# ---------------------------------------------------------------- manifest --
def parse_manifest(addon_path):
    src = (addon_path / "__manifest__.py").read_text(encoding="utf-8")
    tree = ast.parse(src, mode="eval")
    return ast.literal_eval(tree)


def ingest_addon_and_deps(addon, manifest, addon_path):
    with driver.session() as s:
        s.run(
            """
            MERGE (a:Addon {name:$name})
            SET a.displayName=$displayName, a.path=$path, a.version=$version,
                a.category=$category, a.autoInstall=$autoInstall, a.filePath=$filePath
            """,
            name=addon,
            displayName=manifest.get("name", addon),
            path=str(addon_path),
            version=str(manifest.get("version", "")),
            category=manifest.get("category", ""),
            autoInstall=bool(manifest.get("auto_install", False)),
            filePath=str(addon_path / "__manifest__.py"),
        )
        for dep in manifest.get("depends", []):
            s.run(
                """
                MERGE (d:Addon {name:$dep})
                WITH d
                MATCH (a:Addon {name:$name})
                MERGE (a)-[:DEPENDS_ON]->(d)
                """,
                dep=dep,
                name=addon,
            )
    print(f"Addon node + {len(manifest.get('depends', []))} DEPENDS_ON edges written.")


# --------------------------------------------------------------- structural --
def structural_walk(addon, addon_path):
    folders, files = [], []
    folder_folder, folder_file, root_folders = [], [], []

    for dirpath, dirnames, filenames in os.walk(addon_path):
        dirpath_p = Path(dirpath)
        if dirpath_p != addon_path:
            folders.append({"path": str(dirpath_p), "name": dirpath_p.name})
            parent = dirpath_p.parent
            if parent == addon_path:
                root_folders.append(str(dirpath_p))
            else:
                folder_folder.append([str(parent), str(dirpath_p)])
        for fn in filenames:
            fpath = dirpath_p / fn
            try:
                size = fpath.stat().st_size
            except OSError:
                size = 0
            files.append(
                {
                    "path": str(fpath),
                    "filename": fn,
                    "extension": fpath.suffix.lstrip("."),
                    "size": size,
                }
            )
            folder_file.append([str(dirpath_p), str(fpath)])

    with driver.session() as s:
        s.run(
            "UNWIND $rows AS row MERGE (f:Folder {path: row.path}) SET f.name = row.name, f.filePath = row.path",
            rows=folders,
        )
        s.run(
            "UNWIND $rows AS row MERGE (f:File {path: row.path}) "
            "SET f.filename=row.filename, f.extension=row.extension, f.size=row.size, f.filePath = row.path",
            rows=files,
        )
        s.run(
            """
            UNWIND $rows AS row
            MATCH (a:Addon {name:$addon})
            MERGE (fo:Folder {path: row})
            MERGE (a)-[:CONTAINS_FOLDER]->(fo)
            """,
            rows=root_folders,
            addon=addon,
        )
        s.run(
            """
            UNWIND $rows AS row
            MATCH (p:Folder {path: row[0]})
            MATCH (c:Folder {path: row[1]})
            MERGE (p)-[:CONTAINS]->(c)
            """,
            rows=folder_folder,
        )
        s.run(
            """
            UNWIND $rows AS row
            MATCH (fo:Folder {path: row[0]})
            MATCH (fi:File {path: row[1]})
            MERGE (fo)-[:CONTAINS]->(fi)
            """,
            rows=folder_file,
        )
    print(f"Structural: {len(folders)} folders, {len(files)} files written.")
    return files


# --------------------------------------------------------------- py helpers --
def base_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def get_const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def get_str_list(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        out = []
        for el in node.elts:
            s = get_const_str(el)
            if s:
                out.append(s)
        return out
    return []


def decorator_info(dec):
    if isinstance(dec, ast.Call):
        return base_name(dec.func), dec
    return base_name(dec), None


def extract_comodel(call_node):
    if call_node.args:
        s = get_const_str(call_node.args[0])
        if s:
            return s
    for kw in call_node.keywords:
        if kw.arg == "comodel_name":
            return get_const_str(kw.value)
    return None


def _shorten(text, limit=240):
    text = " ".join(text.strip().split())
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text or None


def get_docstring(node):
    doc = ast.get_docstring(node, clean=True)
    if not doc:
        return None
    first_line = doc.strip().split("\n\n")[0].split("\n")[0]
    return _shorten(first_line)


def extract_field_desc(call_node):
    help_val = string_val = None
    for kw in call_node.keywords:
        if kw.arg == "help":
            help_val = get_const_str(kw.value)
        elif kw.arg == "string":
            string_val = get_const_str(kw.value)
    desc = help_val or string_val
    return _shorten(desc) if desc else None


def scan_method_body(func_node):
    uses_model, renders, calls = set(), set(), set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Subscript):
            val = node.value
            if isinstance(val, ast.Attribute) and val.attr == "env":
                sl = node.slice
                if hasattr(ast, "Index") and isinstance(sl, ast.Index):
                    sl = sl.value
                s = get_const_str(sl)
                if s:
                    uses_model.add(s)
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in ("_render", "render"):
                if node.args:
                    s = get_const_str(node.args[0])
                    if s:
                        renders.add(s)
            if isinstance(func, ast.Attribute):
                is_self = isinstance(func.value, ast.Name) and func.value.id == "self"
                is_super = (
                    isinstance(func.value, ast.Call)
                    and isinstance(func.value.func, ast.Name)
                    and func.value.func.id == "super"
                )
                if is_self or is_super:
                    calls.add(func.attr)
            elif isinstance(func, ast.Name):
                # bare-name call, e.g. a module-level helper function
                calls.add(func.id)
    return uses_model, renders, calls


def python_module_dotted(addon, addon_path, filepath):
    rel = filepath.relative_to(addon_path)
    parts = list(rel.with_suffix("").parts)
    return addon + "." + ".".join(parts)


def classify_model(_name, _inherit_list):
    if _name and _inherit_list and _inherit_list == [_name]:
        return _name, "EXTENDS_MODEL", []
    if _name and _inherit_list and _inherit_list != [_name]:
        return _name, "INHERITS_MODEL", _inherit_list
    if _name:
        return _name, "DEFINES_MODEL", []
    if _inherit_list:
        return _inherit_list[0], "EXTENDS_MODEL", _inherit_list[1:]
    return None, None, []


def empty_rows():
    return {
        "models": [], "model_parent": [], "model_extends_extra": [], "model_delegates": [],
        "fields": [], "relates": [], "model_methods": [],
        "controllers": [], "controller_extends_pending": [], "controller_methods": [],
        "uses_model": [], "renders": [], "calls_model": [], "calls_ctrl": [],
        "file_defines_model": [], "file_defines_controller": [],
        "functions": [], "file_defines_function": [], "calls_function": [],
    }


def process_model_class(addon, file_path_str, node, rows):
    _name, _inherit_list, _inherits, description = None, [], {}, None
    field_items, method_items = [], []
    for item in node.body:
        if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
            tgt = item.targets[0].id
            if tgt == "_name":
                _name = get_const_str(item.value)
            elif tgt == "_inherit":
                _inherit_list = get_str_list(item.value)
            elif tgt == "_description":
                description = get_const_str(item.value)
            elif tgt == "_inherits" and isinstance(item.value, ast.Dict):
                for k in item.value.keys:
                    s = get_const_str(k)
                    if s:
                        _inherits[s] = True
            elif isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Attribute):
                if isinstance(item.value.func.value, ast.Name) and item.value.func.value.id == "fields":
                    field_items.append((tgt, item.value.func.attr, item.value, item.lineno))
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method_items.append(item)

    technical_name, kind, extra = classify_model(_name, _inherit_list)
    if technical_name is None:
        return

    if not description:
        description = get_docstring(node)

    addon_rel = "DEFINES_MODEL" if kind in ("DEFINES_MODEL", "INHERITS_MODEL") else "EXTENDS_MODEL"
    defines_own_name = kind in ("DEFINES_MODEL", "INHERITS_MODEL")
    rows["models"].append({
        "tn": technical_name, "description": description, "addonRel": addon_rel,
        "filePath": file_path_str if defines_own_name else None,
    })
    rows["file_defines_model"].append({"file": file_path_str, "tn": technical_name})

    if kind == "INHERITS_MODEL":
        for parent in extra:
            rows["model_parent"].append({"tn": technical_name, "parent": parent})
    elif kind == "EXTENDS_MODEL" and extra:
        for em in extra:
            rows["model_extends_extra"].append({"em": em})

    for dm in _inherits:
        rows["model_delegates"].append({"tn": technical_name, "dm": dm})

    for fname, ftype, call_node, lineno in field_items:
        qn = f"{technical_name}.{fname}"
        fdesc = extract_field_desc(call_node)
        rows["fields"].append({
            "tn": technical_name, "qn": qn, "name": fname, "type": ftype, "description": fdesc,
            "filePath": file_path_str, "fileLine": lineno,
        })
        if ftype in ("Many2one", "One2many", "Many2many"):
            comodel = extract_comodel(call_node)
            if comodel:
                rows["relates"].append({"tn": technical_name, "comodel": comodel, "via": fname, "kind": ftype.lower()})

    method_names = {m.name for m in method_items}
    for m in method_items:
        qn = f"{technical_name}#{m.name}"
        decs = [decorator_info(d)[0] for d in m.decorator_list if decorator_info(d)[0]]
        mdesc = get_docstring(m)
        rows["model_methods"].append({
            "tn": technical_name, "qn": qn, "name": m.name, "decs": decs, "description": mdesc,
            "filePath": file_path_str, "fileLine": m.lineno,
        })
        uses_model, renders, calls = scan_method_body(m)
        for um in uses_model:
            rows["uses_model"].append({"qn": qn, "label": "ModelMethod", "model": um})
        for tmpl in renders:
            rows["renders"].append({"qn": qn, "label": "ModelMethod", "template": tmpl})
        for callee in calls:
            if callee in method_names and callee != m.name:
                rows["calls_model"].append({"from_qn": qn, "to_qn": f"{technical_name}#{callee}"})


def process_controller_class(addon, file_path_str, module_dotted, node, rows):
    class_name = node.name
    qn = f"{module_dotted}.{class_name}"
    parent_names = [b for b in (base_name(x) for x in node.bases) if b and b != "Controller"]
    rows["controllers"].append({"qn": qn, "className": class_name, "description": get_docstring(node), "filePath": file_path_str})
    rows["file_defines_controller"].append({"file": file_path_str, "qn": qn})
    for parent in parent_names:
        rows["controller_extends_pending"].append({"child_qn": qn, "parent_name": parent})

    method_items = [it for it in node.body if isinstance(it, (ast.FunctionDef, ast.AsyncFunctionDef))]
    method_names = {m.name for m in method_items}
    for m in method_items:
        mqn = f"{qn}#{m.name}"
        is_route, http_path, http_methods, auth_type, csrf = False, None, None, None, None
        for dec in m.decorator_list:
            dname, call = decorator_info(dec)
            if dname == "route":
                is_route = True
                if call:
                    if call.args:
                        paths = get_str_list(call.args[0])
                        http_path = paths[0] if paths else None
                    for kw in call.keywords:
                        if kw.arg == "methods":
                            http_methods = get_str_list(kw.value)
                        elif kw.arg == "auth":
                            auth_type = get_const_str(kw.value)
                        elif kw.arg == "csrf" and isinstance(kw.value, ast.Constant):
                            csrf = kw.value.value
        rows["controller_methods"].append(
            {
                "cqn": qn, "qn": mqn, "name": m.name, "isRoute": is_route,
                "httpPath": http_path, "methods": http_methods, "authType": auth_type, "csrf": csrf,
                "description": get_docstring(m), "filePath": file_path_str, "fileLine": m.lineno,
            }
        )
        uses_model, renders, calls = scan_method_body(m)
        for um in uses_model:
            rows["uses_model"].append({"qn": mqn, "label": "ControllerMethod", "model": um})
        for tmpl in renders:
            rows["renders"].append({"qn": mqn, "label": "ControllerMethod", "template": tmpl})
        for callee in calls:
            if callee in method_names and callee != m.name:
                rows["calls_ctrl"].append({"from_qn": mqn, "to_qn": f"{qn}#{callee}"})


def write_python_rows(addon, rows):
    with driver.session() as s:
        def w(query, key):
            if rows.get(key):
                s.run(query, rows=rows[key])

        if rows["models"]:
            s.run(
                """UNWIND $rows AS row
                   MERGE (m:PythonModel {technicalName: row.tn})
                   SET m.description = coalesce(row.description, m.description),
                       m.filePath = coalesce(row.filePath, m.filePath)""",
                rows=rows["models"],
            )
            for relname in ("DEFINES_MODEL", "EXTENDS_MODEL"):
                subset = [r for r in rows["models"] if r["addonRel"] == relname]
                if subset:
                    s.run(
                        f"""UNWIND $rows AS row
                            MATCH (a:Addon {{name:$addon}})
                            MATCH (m:PythonModel {{technicalName: row.tn}})
                            MERGE (a)-[:{relname}]->(m)""",
                        rows=subset,
                        addon=addon,
                    )
        w(
            """UNWIND $rows AS row
               MATCH (f:File {path: row.file})
               MATCH (m:PythonModel {technicalName: row.tn})
               MERGE (f)-[:DEFINES]->(m)""",
            "file_defines_model",
        )
        w(
            """UNWIND $rows AS row
               MATCH (m:PythonModel {technicalName: row.tn})
               MERGE (p:PythonModel {technicalName: row.parent})
               MERGE (m)-[:INHERITS_MODEL]->(p)""",
            "model_parent",
        )
        if rows["model_extends_extra"]:
            s.run(
                """UNWIND $rows AS row
                   MATCH (a:Addon {name:$addon})
                   MERGE (m:PythonModel {technicalName: row.em})
                   MERGE (a)-[:EXTENDS_MODEL]->(m)""",
                rows=rows["model_extends_extra"],
                addon=addon,
            )
        w(
            """UNWIND $rows AS row
               MATCH (m:PythonModel {technicalName: row.tn})
               MERGE (d:PythonModel {technicalName: row.dm})
               MERGE (m)-[:DELEGATES_TO]->(d)""",
            "model_delegates",
        )
        w(
            """UNWIND $rows AS row
               MATCH (m:PythonModel {technicalName: row.tn})
               MERGE (fld:ModelField {qualifiedName: row.qn})
               SET fld.name = row.name, fld.type = row.type,
                   fld.description = coalesce(row.description, fld.description),
                   fld.filePath = row.filePath, fld.fileLine = row.fileLine
               MERGE (m)-[:HAS_FIELD]->(fld)""",
            "fields",
        )
        w(
            """UNWIND $rows AS row
               MATCH (m:PythonModel {technicalName: row.tn})
               MERGE (t:PythonModel {technicalName: row.comodel})
               MERGE (m)-[:RELATES_TO {via: row.via, kind: row.kind}]->(t)""",
            "relates",
        )
        w(
            """UNWIND $rows AS row
               MATCH (m:PythonModel {technicalName: row.tn})
               MERGE (me:ModelMethod {qualifiedName: row.qn})
               SET me.name = row.name, me.apiDecorators = row.decs,
                   me.description = coalesce(row.description, me.description),
                   me.filePath = row.filePath, me.fileLine = row.fileLine
               MERGE (m)-[:HAS_METHOD]->(me)""",
            "model_methods",
        )
        if rows["controllers"]:
            s.run(
                """UNWIND $rows AS row
                   MERGE (c:Controller {qualifiedName: row.qn})
                   SET c.className = row.className,
                       c.description = coalesce(row.description, c.description),
                       c.filePath = row.filePath""",
                rows=rows["controllers"],
            )
        w(
            """UNWIND $rows AS row
               MATCH (f:File {path: row.file})
               MATCH (c:Controller {qualifiedName: row.qn})
               MERGE (f)-[:DEFINES]->(c)""",
            "file_defines_controller",
        )
        w(
            """UNWIND $rows AS row
               MATCH (c:Controller {qualifiedName: row.cqn})
               MERGE (me:ControllerMethod {qualifiedName: row.qn})
               SET me.name = row.name, me.description = coalesce(row.description, me.description),
                   me.filePath = row.filePath, me.fileLine = row.fileLine
               WITH c, me, row
               FOREACH (_ IN CASE WHEN row.isRoute THEN [1] ELSE [] END |
                   SET me:Route, me.httpPath = row.httpPath, me.methods = row.methods,
                       me.authType = row.authType, me.csrf = row.csrf)
               MERGE (c)-[:HAS_METHOD]->(me)""",
            "controller_methods",
        )
        if rows["functions"]:
            s.run(
                """UNWIND $rows AS row
                   MERGE (fn:Function {qualifiedName: row.qn})
                   SET fn.name = row.name, fn.description = coalesce(row.description, fn.description),
                       fn.filePath = row.filePath, fn.fileLine = row.fileLine""",
                rows=rows["functions"],
            )
        w(
            """UNWIND $rows AS row
               MATCH (f:File {path: row.file})
               MATCH (fn:Function {qualifiedName: row.qn})
               MERGE (f)-[:DEFINES]->(fn)""",
            "file_defines_function",
        )
        w(
            """UNWIND $rows AS row
               MATCH (a:Function {qualifiedName: row.from_qn})
               MATCH (b:Function {qualifiedName: row.to_qn})
               MERGE (a)-[:CALLS_METHOD]->(b)""",
            "calls_function",
        )
        # uses_model / renders / calls: label may be ModelMethod, ControllerMethod, or Function
        for label in ("ModelMethod", "ControllerMethod", "Function"):
            subset = [r for r in rows["uses_model"] if r["label"] == label]
            if subset:
                s.run(
                    f"""UNWIND $rows AS row
                        MATCH (me:{label} {{qualifiedName: row.qn}})
                        MERGE (t:PythonModel {{technicalName: row.model}})
                        MERGE (me)-[:USES_MODEL]->(t)""",
                    rows=subset,
                )
            subset2 = [r for r in rows["renders"] if r["label"] == label]
            if subset2:
                s.run(
                    f"""UNWIND $rows AS row
                        MATCH (me:{label} {{qualifiedName: row.qn}})
                        MERGE (t:QWebTemplate {{xmlId: row.template}})
                        MERGE (me)-[:RENDERS_TEMPLATE]->(t)""",
                    rows=subset2,
                )
        w(
            """UNWIND $rows AS row
               MATCH (a:ModelMethod {qualifiedName: row.from_qn})
               MATCH (b:ModelMethod {qualifiedName: row.to_qn})
               MERGE (a)-[:CALLS_METHOD]->(b)""",
            "calls_model",
        )
        w(
            """UNWIND $rows AS row
               MATCH (a:ControllerMethod {qualifiedName: row.from_qn})
               MATCH (b:ControllerMethod {qualifiedName: row.to_qn})
               MERGE (a)-[:CALLS_METHOD]->(b)""",
            "calls_ctrl",
        )


def process_module_functions(file_path_str, module_dotted, tree, rows):
    func_nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    func_names = {n.name for n in func_nodes}
    for fn in func_nodes:
        qn = f"{module_dotted}::{fn.name}"
        rows["functions"].append({
            "qn": qn, "name": fn.name, "description": get_docstring(fn),
            "filePath": file_path_str, "fileLine": fn.lineno,
        })
        rows["file_defines_function"].append({"file": file_path_str, "qn": qn})
        uses_model, renders, calls = scan_method_body(fn)
        for um in uses_model:
            rows["uses_model"].append({"qn": qn, "label": "Function", "model": um})
        for tmpl in renders:
            rows["renders"].append({"qn": qn, "label": "Function", "template": tmpl})
        for callee in calls:
            if callee in func_names and callee != fn.name:
                rows["calls_function"].append({"from_qn": qn, "to_qn": f"{module_dotted}::{callee}"})
    return len(func_nodes)


def process_python_files(addon, addon_path, py_files):
    controller_name_map = {}  # className -> qualifiedName (within this addon, best-effort)
    pending_extends = []
    total_models = total_controllers = total_functions = 0

    for f in py_files:
        filepath = Path(f["path"])
        try:
            src = filepath.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except SyntaxError as e:
            print(f"  SKIP (syntax error) {filepath.name}: {e}")
            continue

        rows = empty_rows()
        module_dotted = python_module_dotted(addon, addon_path, filepath)
        found_any = False
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [base_name(b) for b in node.bases]
            if any(b in MODEL_BASES for b in bases):
                process_model_class(addon, str(filepath), node, rows)
                found_any = True
                total_models += 1
            elif "Controller" in bases:
                process_controller_class(addon, str(filepath), module_dotted, node, rows)
                controller_name_map[node.name] = f"{module_dotted}.{node.name}"
                pending_extends.extend(rows["controller_extends_pending"])
                found_any = True
                total_controllers += 1

        n_funcs = process_module_functions(str(filepath), module_dotted, tree, rows)
        total_functions += n_funcs
        found_any = found_any or n_funcs > 0

        if found_any:
            with_retry(write_python_rows, addon, rows)

    if pending_extends:
        resolved = [
            {"child": e["child_qn"], "parent": controller_name_map[e["parent_name"]]}
            for e in pending_extends
            if e["parent_name"] in controller_name_map
        ]
        if resolved:
            def _write_extends():
                with driver.session() as s:
                    s.run(
                        """UNWIND $rows AS row
                           MATCH (c:Controller {qualifiedName: row.child})
                           MATCH (p:Controller {qualifiedName: row.parent})
                           MERGE (c)-[:EXTENDS_CONTROLLER]->(p)""",
                        rows=resolved,
                    )
            with_retry(_write_extends)
    unresolved = [e for e in pending_extends if e["parent_name"] not in controller_name_map]
    resolved_count = len(pending_extends) - len(unresolved)
    print(f"Python: {total_models} model classes, {total_controllers} controller classes, "
          f"{total_functions} standalone functions processed "
          f"({len(pending_extends)} EXTENDS_CONTROLLER candidates, {resolved_count} resolved in-addon).")
    return unresolved


# --------------------------------------------------------------------- xml --
def local_xml_id(addon, raw_id):
    return raw_id if "." in raw_id else f"{addon}.{raw_id}"


def process_xml_file(addon, filepath):
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(filepath)
    except ET.ParseError as e:
        print(f"  SKIP (xml parse error) {filepath.name}: {e}")
        return 0
    root = tree.getroot()
    file_path_str = str(filepath)

    records, templates = [], []

    def walk(elem, noupdate_ctx):
        nu = noupdate_ctx
        if elem.tag in ("odoo", "openerp", "data"):
            nu_attr = elem.get("noupdate")
            if nu_attr is not None:
                nu = nu_attr in ("1", "True", "true")
        for child in elem:
            if child.tag == "record":
                rid = child.get("id")
                model_attr = child.get("model")
                if rid and model_attr:
                    fields = {}
                    for f in child.findall("field"):
                        fname = f.get("name")
                        if fname and f.text:
                            fields[fname] = f.text.strip()
                        if fname == "inherit_id" and f.get("ref"):
                            fields["_inherit_ref"] = f.get("ref")
                    view_type = None
                    effective_model = model_attr
                    if model_attr == "ir.ui.view":
                        effective_model = fields.get("model", model_attr)
                        arch = child.find("field[@name='arch']")
                        if arch is not None:
                            kids = list(arch)
                            if kids:
                                view_type = kids[0].tag
                    records.append(
                        {
                            "xmlId": local_xml_id(addon, rid),
                            "model": effective_model,
                            "targetModel": effective_model,
                            "isView": model_attr == "ir.ui.view",
                            "viewType": view_type,
                            "noupdate": nu,
                            "inheritRef": local_xml_id(addon, fields["_inherit_ref"]) if fields.get("_inherit_ref") else None,
                        }
                    )
            elif child.tag == "template":
                tid = child.get("id")
                if tid:
                    inherit_id = child.get("inherit_id")
                    templates.append(
                        {
                            "xmlId": local_xml_id(addon, tid),
                            "inheritId": local_xml_id(addon, inherit_id) if inherit_id else None,
                            "primary": child.get("primary", "").lower() == "true",
                        }
                    )
                walk(child, nu)
            else:
                walk(child, nu)

    walk(root, False)

    def _write():
        with driver.session() as s:
            if records:
                s.run(
                    """UNWIND $rows AS row
                       MERGE (x:XMLRecord {xmlId: row.xmlId})
                       SET x.model = row.model, x.noupdate = row.noupdate, x.filePath = $fpath
                       WITH x, row
                       FOREACH (_ IN CASE WHEN row.isView THEN [1] ELSE [] END |
                           SET x:View, x.viewType = row.viewType)
                       WITH x, row
                       MATCH (f:File {path: $fpath})
                       MERGE (f)-[:DEFINES]->(x)
                       WITH x, row
                       MERGE (t:PythonModel {technicalName: row.targetModel})
                       MERGE (x)-[:TARGETS_MODEL]->(t)""",
                    rows=records,
                    fpath=file_path_str,
                )
                inh = [r for r in records if r["inheritRef"]]
                if inh:
                    s.run(
                        """UNWIND $rows AS row
                           MATCH (x:XMLRecord {xmlId: row.xmlId})
                           MERGE (p:XMLRecord {xmlId: row.inheritRef})
                           MERGE (x)-[:INHERITS_VIEW]->(p)""",
                        rows=inh,
                    )
            if templates:
                s.run(
                    """UNWIND $rows AS row
                       MERGE (q:QWebTemplate {xmlId: row.xmlId})
                       SET q.primary = row.primary, q.filePath = $fpath
                       WITH q, row
                       MATCH (f:File {path: $fpath})
                       MERGE (f)-[:DEFINES]->(q)""",
                    rows=templates,
                    fpath=file_path_str,
                )
                inh = [r for r in templates if r["inheritId"]]
                if inh:
                    s.run(
                        """UNWIND $rows AS row
                           MATCH (q:QWebTemplate {xmlId: row.xmlId})
                           MERGE (p:QWebTemplate {xmlId: row.inheritId})
                           MERGE (q)-[:EXTENDS_TEMPLATE]->(p)""",
                        rows=inh,
                    )

    with_retry(_write)
    return len(records) + len(templates)


def process_xml_files(addon, xml_files):
    total = 0
    for f in xml_files:
        total += process_xml_file(addon, Path(f["path"]))
    print(f"XML: {total} XMLRecord/QWebTemplate entities processed across {len(xml_files)} files.")


# ---------------------------------------------------------------------- js --
CLASS_RE = re.compile(r"class\s+(\w+)\s+extends\s+(\w+)")
TEMPLATE_RE = re.compile(r"static\s+template\s*=\s*[\"']([\w.]+)[\"']")
COMPONENTS_RE = re.compile(r"static\s+components\s*=\s*\{([^}]*)\}", re.S)
COMPONENT_NAME_RE = re.compile(r"(\w+)\s*,?")
IMPORT_RE = re.compile(r"""import\s+.*?from\s+["']([^"']+)["']""")


def process_js_file(addon, addon_path, filepath):
    file_path_str = str(filepath)
    try:
        src = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    if len(src) > 3_000_000:
        return 0

    comps = []
    for m in CLASS_RE.finditer(src):
        cname, ext = m.group(1), m.group(2)
        if ext not in ("Component",):
            continue
        qn = f"{file_path_str}::{cname}"
        tmpl_m = TEMPLATE_RE.search(src, m.end())
        template = tmpl_m.group(1) if tmpl_m and tmpl_m.start() - m.end() < 2000 else None
        comps.append({"qn": qn, "name": cname, "owlType": "Component", "extends": ext, "template": template})

    used_components = []
    for cm in COMPONENTS_RE.finditer(src):
        body = cm.group(1)
        names = [n for n in re.findall(r"(\w+)", body) if n and n[0].isupper()]
        for comp in comps:
            for n in names:
                used_components.append({"from_qn": comp["qn"], "name": n})

    imports = []
    for im in IMPORT_RE.finditer(src):
        imports.append(im.group(1))

    if not comps and not imports:
        return 0

    def _write():
        with driver.session() as s:
            if comps:
                s.run(
                    """UNWIND $rows AS row
                       MERGE (j:JSComponent {qualifiedName: row.qn})
                       SET j.name = row.name, j.owlType = row.owlType, j.extends = row.extends,
                           j.filePath = $fpath
                       WITH j, row
                       MATCH (f:File {path: $fpath})
                       MERGE (f)-[:DEFINES]->(j)
                       WITH j, row
                       FOREACH (_ IN CASE WHEN row.template IS NOT NULL THEN [1] ELSE [] END |
                           MERGE (t:QWebTemplate {xmlId: row.template})
                           MERGE (j)-[:RENDERS_TEMPLATE]->(t))""",
                    rows=comps,
                    fpath=file_path_str,
                )

    with_retry(_write)
    return len(comps)


def process_js_files(addon, addon_path, js_files):
    total = 0
    for f in js_files:
        p = Path(f["path"])
        rel = p.relative_to(addon_path)
        if rel.parts and rel.parts[0] == "static" and len(rel.parts) > 1 and rel.parts[1] in SKIP_DEEP_JS_DIRS:
            continue
        total += process_js_file(addon, addon_path, p)
    print(f"JS: {total} JSComponent entities processed (static/lib skipped as vendored).")


# ------------------------------------------------------------- asset bundles
def resolve_glob(addon_path, pattern):
    pattern = pattern.lstrip("/")
    if pattern.startswith(f"{addon_path.name}/"):
        rel_pattern = pattern[len(addon_path.name) + 1 :]
        base = addon_path
    else:
        return []
    try:
        return [str(p) for p in base.glob(rel_pattern) if p.is_file()]
    except Exception:
        return []


def process_assets(addon, addon_path, manifest):
    assets = manifest.get("assets", {})
    bundles = list(assets.keys())
    includes_bundle, includes_asset = [], []

    for bundle_name, entries in assets.items():
        for entry in entries:
            if isinstance(entry, tuple) and len(entry) >= 2:
                directive = entry[0]
                if directive == "include":
                    includes_bundle.append({"from": bundle_name, "to": entry[1]})
                elif directive in ("remove",):
                    for p in resolve_glob(addon_path, entry[1]):
                        includes_asset.append({"bundle": bundle_name, "path": p, "remove": True})
                elif directive == "after":
                    for p in resolve_glob(addon_path, entry[2] if len(entry) > 2 else entry[1]):
                        includes_asset.append({"bundle": bundle_name, "path": p, "remove": False})
            elif isinstance(entry, str):
                for p in resolve_glob(addon_path, entry):
                    includes_asset.append({"bundle": bundle_name, "path": p, "remove": False})

    adds = [r for r in includes_asset if not r["remove"]]
    removes = [r for r in includes_asset if r["remove"]]

    def _write():
        with driver.session() as s:
            if bundles:
                s.run(
                    """UNWIND $rows AS row
                       MERGE (b:AssetBundle {name: row})
                       SET b.filePath = $manifestPath
                       WITH b
                       MATCH (a:Addon {name:$addon})
                       MERGE (a)-[:DEFINES_BUNDLE]->(b)""",
                    rows=bundles,
                    addon=addon,
                    manifestPath=str(addon_path / "__manifest__.py"),
                )
            if includes_bundle:
                s.run(
                    """UNWIND $rows AS row
                       MERGE (b1:AssetBundle {name: row.from})
                       MERGE (b2:AssetBundle {name: row.to})
                       MERGE (b1)-[:INCLUDES_BUNDLE]->(b2)""",
                    rows=includes_bundle,
                )
            if adds:
                s.run(
                    """UNWIND $rows AS row
                       MATCH (b:AssetBundle {name: row.bundle})
                       MERGE (asset:Asset {path: row.path})
                       SET asset.type = 'static', asset.name = row.path, asset.filePath = row.path
                       MERGE (b)-[:INCLUDES_ASSET]->(asset)
                       WITH asset, row
                       MATCH (f:File {path: row.path})
                       MERGE (f)-[:DEFINES]->(asset)""",
                    rows=adds,
                )
            if removes:
                s.run(
                    """UNWIND $rows AS row
                       MATCH (b:AssetBundle {name: row.bundle})-[rel:INCLUDES_ASSET]->(asset:Asset {path: row.path})
                       DELETE rel""",
                    rows=removes,
                )

    with_retry(_write)
    print(f"Assets: {len(bundles)} bundles, {len(includes_bundle)} INCLUDES_BUNDLE, "
          f"{len(adds)} INCLUDES_ASSET (after {len(removes)} removes applied) written.")


# ---------------------------------------------------------------------- run --
def ingest_addon(addon):
    addon_path = ROOT / addon
    manifest = parse_manifest(addon_path)
    print(f"=== {addon}: {manifest.get('name')} ===")
    ingest_addon_and_deps(addon, manifest, addon_path)
    files = structural_walk(addon, addon_path)

    py_files = [f for f in files if f["extension"] == "py" and f["filename"] not in ("__manifest__.py",)]
    xml_files = [f for f in files if f["extension"] == "xml"]
    js_files = [f for f in files if f["extension"] == "js"]

    unresolved = process_python_files(addon, addon_path, py_files)
    process_xml_files(addon, xml_files)
    process_js_files(addon, addon_path, js_files)
    process_assets(addon, addon_path, manifest)
    print(f"=== {addon}: done ===")
    return unresolved


def resolve_global_controller_extends(all_pending):
    """Best-effort cross-addon EXTENDS_CONTROLLER resolution: only link when the
    parent class name is unambiguous (exactly one Controller with that className)
    across the whole graph scanned so far."""
    if not all_pending:
        return 0
    with driver.session() as s:
        rows = s.run(
            "MATCH (c:Controller) RETURN c.className AS className, collect(c.qualifiedName) AS qns"
        ).data()
    unique_by_name = {r["className"]: r["qns"][0] for r in rows if len(r["qns"]) == 1}
    resolved = [
        {"child": e["child_qn"], "parent": unique_by_name[e["parent_name"]]}
        for e in all_pending
        if e["parent_name"] in unique_by_name
    ]
    if resolved:
        def _write():
            with driver.session() as s2:
                s2.run(
                    """UNWIND $rows AS row
                       MATCH (c:Controller {qualifiedName: row.child})
                       MATCH (p:Controller {qualifiedName: row.parent})
                       MERGE (c)-[:EXTENDS_CONTROLLER]->(p)""",
                    rows=resolved,
                )
        with_retry(_write)
    return len(resolved)


def discover_addons():
    names = []
    for d in sorted(ROOT.iterdir()):
        if d.is_dir() and (d / "__manifest__.py").exists():
            names.append(d.name)
    return names


def run_all():
    addons = discover_addons()
    print(f"Discovered {len(addons)} addons with __manifest__.py")
    setup_constraints()
    all_pending = []
    failures = []
    for i, addon in enumerate(addons, 1):
        print(f"\n[{i}/{len(addons)}] {addon}")
        try:
            unresolved = ingest_addon(addon)
            all_pending.extend(unresolved)
        except Exception as e:
            print(f"!!! FAILED {addon}: {type(e).__name__}: {e}")
            failures.append(addon)
    resolved_count = resolve_global_controller_extends(all_pending)
    print(f"\n=== ALL DONE: {len(addons)} addons, {len(failures)} failures, "
          f"{resolved_count}/{len(all_pending)} cross-addon EXTENDS_CONTROLLER resolved ===")
    if failures:
        print("Failed addons:", ", ".join(failures))


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "web"
    if target == "all":
        run_all()
    else:
        setup_constraints()
        ingest_addon(target)
    driver.close()
