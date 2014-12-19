import os


def resolve(name, base=None):
    if base is None:
        base = os.path.dirname(__file__)
    return os.path.join(base, name)
