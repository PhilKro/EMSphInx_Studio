"""Readable structure choices with the SHT database's original identifiers."""

import re


STRUCTURE_NAMES = {
    "A1": "FCC",
    "A2": "BCC",
    "A3": "HCP",
    "A4": "Diamond cubic",
}


def structure_code(value):
    value = value.strip()
    if not value:
        return ""
    match = re.search(r"\[([^\]]+)\]", value)
    if match:
        value = match.group(1).strip()
    else:
        for code, name in STRUCTURE_NAMES.items():
            if value.casefold() == name.casefold():
                return f"[{code.lower()}]"
    return f"[{value.strip('[]').lower()}]"


def structure_label(value):
    code = structure_code(value)[1:-1].upper()
    name = STRUCTURE_NAMES.get(code)
    return f"{name} [{code}]" if name else value


STRUCTURE_CHOICES = tuple(structure_label(code) for code in STRUCTURE_NAMES)
