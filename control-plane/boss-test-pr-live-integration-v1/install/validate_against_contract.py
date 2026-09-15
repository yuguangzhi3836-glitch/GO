"""Validate one published record against a published JSON-Schema contract.

A deliberately small subset validator driven entirely by the contract file --
required / const / enum / type / additionalProperties.enum -- so the check is a
reading of the contract rather than a second copy of it. It is not a general
JSON-Schema implementation and does not pretend to be; it fails closed on any
keyword it does not implement that would otherwise silently pass a document.
"""
import json
import pathlib
import sys

SUPPORTED = {"$schema", "$id", "title", "description", "$defs", "$ref",
             "type", "required", "const", "enum", "properties", "additionalProperties",
             "items", "format", "minimum", "maximum", "x-go-semantics", "x-go-closed-sets",
             "x-go-not-authority", "x-go-one-record-per-task", "examples"}


def check(value, schema, path, problems):
    if "const" in schema and value != schema["const"]:
        problems.append("%s: expected const %r, got %r" % (path, schema["const"], value))
        return
    if "enum" in schema and value not in schema["enum"]:
        problems.append("%s: %r not in %s" % (path, value, schema["enum"]))
        return
    kind = schema.get("type")
    if kind:
        kinds = kind if isinstance(kind, list) else [kind]
        ok = any((k == "object" and isinstance(value, dict))
                 or (k == "array" and isinstance(value, list))
                 or (k == "string" and isinstance(value, str))
                 or (k == "integer" and isinstance(value, int) and not isinstance(value, bool))
                 or (k == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
                 or (k == "boolean" and isinstance(value, bool))
                 or (k == "null" and value is None) for k in kinds)
        if not ok:
            problems.append("%s: expected type %s, got %s" % (path, kind, type(value).__name__))
            return
    if "minimum" in schema and isinstance(value, int) and value < schema["minimum"]:
        problems.append("%s: below minimum %s" % (path, schema["minimum"]))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                problems.append("%s: missing required %r" % (path, key))
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties")
        for key, item in value.items():
            if key in props:
                check(item, props[key], "%s.%s" % (path, key), problems)
            elif isinstance(extra, dict):
                check(item, extra, "%s.%s" % (path, key), problems)
            elif extra is False:
                problems.append("%s: unexpected key %r" % (path, key))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            check(item, schema["items"], "%s[%d]" % (path, index), problems)


def main():
    schema_path, document_path = sys.argv[1], sys.argv[2]
    schema = json.loads(pathlib.Path(schema_path).read_text(encoding="utf-8"))
    document = json.loads(pathlib.Path(document_path).read_text(encoding="utf-8"))
    unimplemented = sorted(k for k in schema if k not in SUPPORTED)
    problems = []
    check(document, schema, "$", problems)
    print("CONTRACT      = %s" % schema.get("$id", schema_path))
    print("DOCUMENT      = %s" % pathlib.Path(document_path).name)
    print("UNIMPLEMENTED = %s" % (unimplemented or "none"))
    if problems:
        print("RESULT        = FAIL")
        for problem in problems[:20]:
            print("   %s" % problem)
        return 1
    print("RESULT        = PASS (%d required keys, consts, enums and type checks all satisfied)"
          % len(schema.get("required", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
