#!/usr/bin/env python3

import argparse
from pathlib import Path
from symbols import Symbols, parse_symbols
import re


def translate(address: int, current_syms: Symbols, ref_syms: Symbols) -> int | None:
    ref_idx = ref_syms.addresses[address]

    ref_sym = ref_syms.symbols[ref_idx]

    final_sym = None

    for sym in current_syms.symbols:
        if ref_sym.name == sym.name:
            if final_sym == None:
                final_sym = sym
            else:
                print(f"Duplicate symbol! {ref_sym.name}")
                return None

    if final_sym != None:
        return final_sym.address
    else:
        print(f"Not found! {ref_sym.name}")
        return None


parser = argparse.ArgumentParser(
    description="Cross splits one decomp project to another, using symbol names to translate addresses."
)
parser.add_argument(
    "ref_path", type=Path, help="Path to the symbols.txt for the reference game."
)
parser.add_argument(
    "current_path", type=Path, help="Path to the symbols.txt of the current game."
)
args = parser.parse_args()
ref_path: Path = args.ref_path
current_path: Path = args.current_path
splits_path = Path("splits.txt")

ref_syms_txt = ref_path.read_text()
current_syms_txt = current_path.read_text()
splits = splits_path.read_text()

ref_syms = parse_symbols(ref_syms_txt)
current_syms = parse_symbols(current_syms_txt)

filename_regex = re.compile(r"(?P<filename>.*):")
split_regex = re.compile(
    r"\s*(?P<section>[a-zA-Z.]*)\s*start:0x(?P<start>[0-9A-Za-z]*) end:0x(?P<end>[0-9A-Za-z]*)"
)

for line in splits.splitlines():
    if line == "":
        continue

    if line.endswith(":"):
        filename = line.strip(":")
        print(f"{filename}:")
        continue

    match = split_regex.match(line)
    if match != None:
        groups = match.groupdict()
    else:
        continue

    start = int(groups["start"], 16)
    end = int(groups["end"], 16)
    section = groups["section"]

    start = translate(start, current_syms, ref_syms)
    end = translate(end, current_syms, ref_syms)

    if start != None and end != None:
        print(f"\t{section} start:0x{start:X} end:0x{end:X}")
