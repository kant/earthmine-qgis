import sys
import os


def resolve(name, base=None):
    if base is None:
        base = os.path.dirname(__file__)
    if name.endswith(".ui"):
        sys.path.append(base)
    return os.path.join(base, name)
