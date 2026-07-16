#!/usr/bin/env python3

import argparse
from pathlib import Path
from symbols import parse_symbols
from sys import exit

parser = argparse.ArgumentParser(
    description="Translates addresses from one decomp project to another, using symbol names."
)
parser.add_argument(
    "ref_path", type=Path, help="Path to the symbols.txt for the reference game."
)
parser.add_argument(
    "current_path", type=Path, help="Path to the symbols.txt of the current game."
)
parser.add_argument(
    "address",
    type=str,
    help="Address to translate, in the reference game.",
)
args = parser.parse_args()
ref_path: Path = args.ref_path
current_path: Path = args.current_path
address: int = int(args.address, 16)

ref_syms_txt = ref_path.read_text()
current_syms_txt = current_path.read_text()

ref_syms = parse_symbols(ref_syms_txt)
current_syms = parse_symbols(current_syms_txt)

ref_idx = ref_syms.addresses[address]
ref_sym = ref_syms.symbols[ref_idx]

final_sym = None

for sym in current_syms.symbols:
    if ref_sym.name == sym.name:
        if final_sym == None:
            final_sym = sym
        else:
            print(f"Duplicate symbol! {ref_sym.name}")
            exit(1)

if final_sym != None:
    print(f"0x{final_sym.address:X}")
else:
    print(f"Not found! {ref_sym.name}")
