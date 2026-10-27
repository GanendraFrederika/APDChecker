"""Refuse to load a PyTorch .pt whose pickle imports anything outside an allowlist.

A .pt file is a zip with a pickle inside; unpickling can import ANY Python callable
(os.system, subprocess, eval...). Downloaded models are scanned before torch.load.
Usage: python scan_pt.py model.pt [...]   -> exit 0 = clean, 1 = suspicious.
"""
import pickletools
import sys
import zipfile

ALLOWED_MODULES = ("torch", "ultralytics", "collections", "numpy", "_codecs", "copyreg",
                   "pathlib", "datetime", "argparse", "types", "functools", "enum", "typing")
ALLOWED_BUILTINS = {"set", "frozenset", "dict", "list", "tuple", "slice", "range", "complex",
                    "bytearray", "bytes", "float", "int", "bool", "str", "object"}
STRING_OPS = {"SHORT_BINUNICODE", "BINUNICODE", "UNICODE", "BINUNICODE8", "SHORT_BINSTRING",
              "BINSTRING", "STRING"}


def imports_of(data):
    found, strings = set(), []
    for op, arg, _ in pickletools.genops(data):
        if op.name in STRING_OPS:
            strings.append(arg)
        elif op.name == "GLOBAL":
            module, name = arg.split(" ", 1)
            found.add((module, name))
        elif op.name == "STACK_GLOBAL" and len(strings) >= 2:
            found.add((strings[-2], strings[-1]))
    return found


def suspicious(found):
    bad = []
    for module, name in sorted(found):
        if module == "builtins" or module == "__builtin__":
            if name not in ALLOWED_BUILTINS:
                bad.append(f"{module}.{name}")
        elif not module.split(".")[0] in ALLOWED_MODULES:
            bad.append(f"{module}.{name}")
    return bad


def scan(path):
    with zipfile.ZipFile(path) as z:
        pkls = [n for n in z.namelist() if n.endswith(".pkl")]
        if not pkls:
            return ["no pickle inside (unexpected format)"], set()
        found = set()
        for n in pkls:
            found |= imports_of(z.read(n))
    return suspicious(found), found


if __name__ == "__main__":
    rc = 0
    for p in sys.argv[1:]:
        bad, found = scan(p)
        mods = sorted({m.split(".")[0] for m, _ in found})
        print(f"{p}: {len(found)} imports from {mods} -> {'SUSPICIOUS ' + str(bad) if bad else 'clean'}")
        rc |= bool(bad)
    sys.exit(rc)
