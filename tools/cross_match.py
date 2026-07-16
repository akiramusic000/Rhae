#!/usr/bin/env python3

import argparse
from pathlib import Path
from symbols import parse_symbols

parser = argparse.ArgumentParser(
    description="Cross matches symbols from one decomp project to another."
)
parser.add_argument(
    "ref_path", type=Path, help="Path to the symbols.txt for the reference game."
)
parser.add_argument(
    "current_path", type=Path, help="Path to the symbols.txt of the current game."
)
parser.add_argument(
    "base_address",
    type=str,
    help="Address of the base symbol to start matching from, in the reference game.",
)
args = parser.parse_args()
ref_path: Path = args.ref_path
current_path: Path = args.current_path
base_address: int = int(args.base_address, 16)

ref_syms_txt = ref_path.read_text()
current_syms_txt = current_path.read_text()

ref_syms = parse_symbols(ref_syms_txt)
current_syms = parse_symbols(current_syms_txt)

ref_idx = ref_syms.addresses[base_address]

longest_match = 0
longest_match_address = 0
current_match = 0
current_match_address = 0
i = 0

while i < len(current_syms.symbols):
    sym = current_syms.symbols[i]
    ref_sym = ref_syms.symbols[ref_idx + current_match]

    if sym.size == ref_sym.size:
        if current_match == 0:
            current_match_address = sym.address

        current_match += 1

        if current_match > longest_match:
            longest_match = current_match
            longest_match_address = current_match_address
    elif current_match != 0:
        current_match = 0
        current_match_address = 0
        i -= current_match + 1

    i += 1

base_idx = current_syms.addresses[longest_match_address]
for i in range(longest_match):
    sym = current_syms.symbols[base_idx + i]
    ref_sym = ref_syms.symbols[ref_idx + i]
    sym.name = ref_sym.name
    sym.scope = ref_sym.scope

    print(f"{sym}")
