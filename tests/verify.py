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


# Whether an answer is the whole truth is the engine's to say, beside the rows: short() from the
# battery library (tests/lib, pinned from embabel-worlds/realm-spec) is None when it is, else the
# line to print in place of the figure, `REFUSED: <why>` or `PARTIAL <figure>: <the engine's reason>`.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from short import short  # noqa: E402


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
