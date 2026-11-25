"""realm-java-code live battery. Run by tests/verify.sh, which states the environment.

L1  every view of this realm answers BY NAME, with the arguments a caller would pass.
L2  exact reconciliation of what the views say about the shipped jar against the jar itself,
    read by tests/classfile.py: checksum, types per package, a type's shape, a method's
    overloads and first lines, who calls Map.put, who touches a static field, subtypes.
L3  cost: not applicable. Every producer reads a local jar through the `jar` kind; no view
    makes a call to a remote source, so there is no source-call ceiling to hold.
"""
import base64, glob, hashlib, json, os, re, sys, urllib.error, urllib.request, zipfile

sys.path.insert(0, os.path.dirname(__file__))
from classfile import ClassFile, ACC_SYNTHETIC  # noqa: E402

BASE = os.environ.get("APPLIANCE", "http://127.0.0.1:8080").rstrip("/")
HDR = {"Authorization": "Basic " + base64.b64encode(os.environ["AUTH"].encode()).decode(),
       "Content-Type": "application/json"}
JAR = "data/jars/spring-core-6.2.18.jar"
fails = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok or not detail else f": {detail}"))
    if not ok:
        fails.append(name)


# A figure the engine marks short is not the realm's figure, and a battery that counts it reports
# drift that is the source's. short(d) reads an answer's own error, reason, warnings and outcome and
# is None when the answer is whole, else the line that stands in for the figure: "REFUSED: <why>"
# or "PARTIAL <n>: <the engine's reason>". It reads both wires: a query answer (`rows`, `warnings`
# as strings opening with the engine's code) and a view envelope (`status`, `outcome`, `warnings`
# as {code, message}).
# Raw warning codes that mean rows or values may be missing (the engine's incompleteness kinds).
# Cost notes (FILTERED_IN_GRAPH, AGGREGATE_NOT_PUSHED, EMPTY_NOT_KEPT, PUSHDOWN_VALUE_UNMATCHED),
# FILTER_STARVED (an honest empty), STALE_COPY, FIELDS_WITHHELD and UNKNOWN_VIA leave every row in place.
SHORT_CODES = (
    "PARTIAL_RESULT", "PRODUCER_ERROR", "NEEDS_FILTER", "NEEDS_PRODUCER", "FILTER_REJECTED",
    "UNPUSHED_FILTER", "AMBIGUOUS_LABEL", "INCOMPLETE_TRAVERSAL", "INCOMPLETE_RANKING",
    "INCOMPLETE_AGGREGATE", "INCOMPLETE_INPUT", "MATERIALIZATION_FAILED", "REDUCTION_FAILED",
    "UNPARSEABLE_ANSWER", "TERMS_UNAVAILABLE", "COMPUTE_FAILED", "PROPERTY_NOT_STORED",
    "FOLLOW_CAPPED", "UNLINKED_CHILDREN", "RESOLUTION_DROPPED", "AGENTIC_DEGRADED",
    "SOURCE_UNANSWERED",
)
# The typed `reason` a query result carries when it is not a clean answer and not an honest empty.
SHORT_REASONS = ("UNBOUNDED", "PARTIAL_NOT_MATCHED", "UNPUSHED_FILTER", "DISCONNECTED",
                 "INTERNAL_ERROR", "WRITE_IN_PROGRESS", "KILLED", "TOO_EXPENSIVE")
# Public warning codes on a view envelope that mean the same.
SHORT_PUBLIC = ("PARTIAL", "REDUCTION_FAILED", "COMPUTE_FAILED", "PROPERTY_NOT_STORED",
                "AGENTIC_DEGRADED", "RATE_LIMITED", "SOURCE_UNAVAILABLE", "SOURCE_REJECTED",
                "INVALID_FILTER", "UNPUSHED_FILTER", "TOO_BROAD", "FETCH_CAPPED",
                "INDEX_UNAVAILABLE", "ARGUMENT_REFUSED")


def short(d, figure=None):
    tag = "PARTIAL" if figure is None else "PARTIAL %s" % (figure,)
    if not isinstance(d, dict):
        return "REFUSED: not an engine answer: " + str(d)[:160]
    if "outcome" in d or "status" in d:  # a view envelope
        err = d.get("error") or {}
        if d.get("status") != "SUCCEEDED":
            return "REFUSED: %s %s" % (d.get("status"), (err.get("code", "") + " " + err.get("message", "")).strip()[:160] if isinstance(err, dict) else str(err)[:160])
        ws = [w for w in d.get("warnings") or [] if isinstance(w, dict) and w.get("code") in SHORT_PUBLIC]
        if d.get("outcome") not in ("OK", "EMPTY") or ws:
            why = ws[0]["code"] + ": " + ws[0].get("message", "") if ws else "outcome " + str(d.get("outcome"))
            return "%s: %s" % (tag, why[:200])
        return None
    if d.get("error"):
        return "REFUSED: " + str(d["error"])[:160]
    if d.get("run"):
        return "%s: the run had not finished (%s)" % (tag, d["run"])
    ws = [w for w in d.get("warnings") or [] if isinstance(w, str) and w.split(":", 1)[0].strip() in SHORT_CODES]
    if ws:
        return "%s: %s" % (tag, ws[0][:200])
    if d.get("reason") in SHORT_REASONS:
        return "%s: reason %s" % (tag, d["reason"])
    return None


def view(name, args):
    req = urllib.request.Request(f"{BASE}/api/v1/views/{name}/invoke", headers=HDR,
                                 data=json.dumps({"args": args}).encode())
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read(), strict=False)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} {e.read().decode()[:300]}"
    except (urllib.error.URLError, OSError) as e:
        return None, f"unreachable: {e}"
    # A partial or refused view is a failed check carrying the engine's reason, never rows to count.
    data = d.get("data") if isinstance(d.get("data"), list) else []
    s = short(d, len(data))
    return (None, s) if s else (data, None)


# ---- ground truth, from the jar -------------------------------------------------------------
z = zipfile.ZipFile(JAR)
classes = {}
for entry in z.namelist():
    if entry.endswith(".class") and not entry.endswith(("package-info.class", "module-info.class")):
        c = ClassFile(z.read(entry))
        classes[c.name] = c
SHA = hashlib.sha256(open(JAR, "rb").read()).hexdigest()
packages = {}
for n in classes:
    pkg = n.rsplit(".", 1)[0]
    packages[pkg] = packages.get(pkg, 0) + 1
print(f"== L0: {JAR}: {len(classes)} types in {len(packages)} packages, sha256 {SHA[:12]}…")

SU = "org.springframework.util.StringUtils"
CU_FIELD = "org.springframework.util.ClassUtils.commonClassCache"
SUPER = "org.springframework.core.io.AbstractResource"

# ---- L1: every view by name -----------------------------------------------------------------
ARGS = {
    "JarSummary": {"jar": JAR}, "JarPackages": {"jar": JAR},
    "JavaTypeProfile": {"jar": JAR, "type": SU}, "JavaSubtypes": {"jar": JAR, "type": SUPER},
    "JavaTypeFields": {"jar": JAR, "type": SU}, "JavaStaticContainers": {"jar": JAR},
    "JavaFieldAccesses": {"jar": JAR, "field": CU_FIELD}, "JavaFieldMutationSites": {"jar": JAR, "field": CU_FIELD},
    "JavaCallers": {"jar": JAR, "type": "java.util.Map", "method": "put", "limit": 5000},
    "JavaMethodsNamed": {"jar": JAR, "type": SU, "method": "hasText"},
    "JavaOutsideDependencies": {"jar": JAR}, "JavaHashedKeysWithoutHashCode": {"jar": JAR},
    "JavaFieldsHolding": {"jar": JAR, "type": "java.lang.Thread"}, "JavaCastTargets": {"jar": JAR},
    "JavaCastSites": {"jar": JAR, "type": "java.lang.String"}, "JavaMethodComplexity": {"jar": JAR},
    "SpringCoreRepackagedLibraries": {}, "SpringCoreReferenceCaches": {}, "SpringCoreStaticMaps": {},
}
# Views that may honestly be empty over this jar: the question has no instance in it.
MAY_BE_EMPTY = {"JavaHashedKeysWithoutHashCode", "JavaFieldsHolding"}
names = sorted({m.group(1) for f in glob.glob("views/*.yml")
                for m in re.finditer(r"^- name:\s*(\S+)", open(f).read(), re.M)})
print(f"== L1: {len(names)} views by name")
results = {}
for name in names:
    if name not in ARGS:
        check(f"view {name}", False, "no arguments in tests/verify.py: add them")
        continue
    rows, err = view(name, ARGS[name])
    results[name] = rows
    check(f"view {name}: {len(rows) if rows is not None else 0} row(s)",
          err is None and (rows or name in MAY_BE_EMPTY), err or "no rows")

# ---- L2: reconcile against the jar ----------------------------------------------------------
print("== L2: the views against the jar itself")
r = results.get("JarSummary") or [{}]
check("JarSummary sha256", r[0].get("sha256") == SHA, f"{r[0].get('sha256')} vs {SHA}")
check("JarSummary types", r[0].get("types") == len(classes), f"{r[0].get('types')} vs {len(classes)}")
check("JarSummary packages", r[0].get("packages") == len(packages), f"{r[0].get('packages')} vs {len(packages)}")

got = {row["package"]: row["types"] for row in results.get("JarPackages") or []}
diff = {k: (got.get(k), packages.get(k)) for k in set(got) | set(packages) if got.get(k) != packages.get(k)}
check(f"JarPackages: types per package, all {len(packages)}", not diff, str(dict(list(diff.items())[:5])))

su = classes[SU]
p = (results.get("JavaTypeProfile") or [{}])[0]
check("JavaTypeProfile superclass", p.get("superclass") == su.superclass, f"{p.get('superclass')}")
check("JavaTypeProfile fields", p.get("fields") == len(su.fields), f"{p.get('fields')} vs {len(su.fields)}")
# A lambda body is compiled to a synthetic `lambda$…` method but has no row of its own (its code
# belongs to the method it is written in), so the type's method count leaves it out.
declared = [m for m in su.methods if not (m["flags"] & ACC_SYNTHETIC and m["name"].startswith("lambda$"))]
check("JavaTypeProfile methods", p.get("methods") == len(declared), f"{p.get('methods')} vs {len(declared)}")

fields = {row["name"] for row in results.get("JavaTypeFields") or []}
truth = {f["name"] for f in su.fields}
check("JavaTypeFields names", fields == truth, f"{sorted(fields ^ truth)}")


def java_params(desc):
    """`(Ljava/lang/String;[I)Z` -> ['java.lang.String', 'int[]']."""
    prim = {"Z": "boolean", "B": "byte", "C": "char", "S": "short", "I": "int", "J": "long", "F": "float", "D": "double"}
    out, i, s = [], 0, desc[1:desc.index(")")]
    while i < len(s):
        dims = 0
        while s[i] == "[":
            dims += 1; i += 1
        if s[i] == "L":
            j = s.index(";", i); t = s[i + 1:j].replace("/", "."); i = j + 1
        else:
            t = prim[s[i]]; i += 1
        out.append(t + "[]" * dims)
    return out


truth = {f"{SU}.hasText({','.join(java_params(m['desc']))})": min(m["lines"])
         for m in su.methods if m["name"] == "hasText"}
got = {row["method"].replace(", ", ","): row["firstLine"] for row in results.get("JavaMethodsNamed") or []}
check("JavaMethodsNamed hasText: overloads and first lines", got == truth, f"{got} vs {truth}")

truth = {c.name for c in classes.values() for m in c.methods
         for op in m["ops"] if op[0] == "CALL" and op[1] == "java.util.Map" and op[2] == "put"}
got = {row["callerType"] for row in results.get("JavaCallers") or []}
check(f"JavaCallers Map.put: {len(truth)} calling types", got == truth, f"{sorted(got ^ truth)[:6]}")

owner, fname = CU_FIELD.rsplit(".", 1)
truth = {}
for c in classes.values():
    for m in c.methods:
        for op in m["ops"]:
            if op[0] in ("READ", "WRITE") and op[1] == owner and op[2] == fname and not m["flags"] & ACC_SYNTHETIC:
                truth.setdefault((c.name, m["name"], op[0]), set()).add(op[4])
got = {(row["type"], row["method"].split("(")[0].rsplit(".", 1)[1], row["access"]): set(row["lines"])
       for row in results.get("JavaFieldAccesses") or []}
check(f"JavaFieldAccesses commonClassCache: methods, access and lines", got == truth, f"{got} vs {truth}")

truth = {c.name for c in classes.values() if c.superclass == SUPER or SUPER in c.interfaces}
got = {row["type"] for row in results.get("JavaSubtypes") or []}
check(f"JavaSubtypes AbstractResource: {len(truth)} direct subtypes", got == truth, f"{sorted(got ^ truth)}")

print("== L3: not applicable — every producer reads a local jar; no source calls to bound")
if fails:
    print(f"FAILED: {len(fails)} check(s): {', '.join(fails)}")
    sys.exit(1)
print("ALL CHECKS PASS")
