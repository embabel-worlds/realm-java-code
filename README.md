# realm-java-code

Any Java jar as a graph, read on demand. Pin a jar by path and traverse its packages, types,
fields, methods, field accesses and calls. The jar is read by the appliance's `jar` producer kind
(ArchUnit over the class files) when a query reaches it; the nodes are virtual and gone when the
query ends. Nothing is ingested, seeded or stored, and no source code is needed.

```cypher
MATCH (j:Jar {path: 'data/jars/spring-core-6.2.18.jar'})-[:HAS_FIELD]->(f:JavaField {isStatic: true, container: 'map'})
OPTIONAL MATCH (f)-[:ACCESSED_BY]->(a:FieldAccess)-[:SAME_METHOD_CALL]->(c:MethodCall {calleeName: 'put'})
RETURN f.key, count(DISTINCT a.method) AS addingMethods
```

## Where a jar can be

A jar path resolves against, in order:

1. the world's `data/` tree (relative paths);
2. a trusted root the operator set for the world (absolute paths);
3. this realm's own directory (relative paths), which is how the example jar is found.

Anything else is refused with a `PRODUCER_ERROR` warning naming the path.

## The graph

See `types/java.yml` for every type, property and hop. Every node's `id` is `<jar path>!<member>`
and every reference to another member has an `…Id` twin, which is what the next hop keys on.
Class names are binary names (`pkg.Outer$Inner`), as heap dumps and stack traces print them.

## Views

`views/java.yml` works on any jar: every view takes `jar`. `views/demo-spring-core.yml` holds three
demo views pinned to the example jar; nothing else depends on them.

## Example jar

`data/jars/spring-core-6.2.18.jar` is Spring Framework's spring-core, unmodified, from Maven Central,
under the Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0). Copyright the Spring
Framework authors.

## Licence

The realm's own files are under the Apache License 2.0 (`LICENSE`). The example jar keeps its own
licence, above.
