#!/usr/bin/env python3

import argparse
from pathlib import Path
import re
from dataclasses import dataclass


@dataclass
class Symbols:
    symbols: list[Symbol]
    addresses: dict[int, int]


@dataclass
class Symbol:
    name: str
    section: str
    address: int
    size: int
    pre: str
    post: str

    def __format__(self, format_spec: str) -> str:
        return f"{self.name} = {self.section}:0x{self.address:X}{self.pre}size:0x{self.size:X}{self.post}"


sym_regex = re.compile(
    r"(?P<name>.+) = (?P<section>\.?[a-zA-Z0-9]+):0x(?P<address>[0-9A-Fa-f]{8})(?P<pre>.*)size:0x(?P<size>[0-9A-Za-z]*)(?P<post>.*)"
)


def parse_symbols(symbols_txt: str) -> Symbols:
    symbol_list = []
    addresses = {}
    i = 0

    for line in symbols_txt.splitlines():
        sym_match = sym_regex.match(line)
        if sym_match != None:
            groups = sym_match.groupdict()
            address = int(groups["address"], 16)
            symbol_list.append(
                Symbol(
                    groups["name"],
                    groups["section"],
                    address,
                    int(groups["size"], 16),
                    groups["pre"],
                    groups["post"],
                )
            )
            if not address in addresses:
                addresses[address] = i
            i += 1

    return Symbols(symbol_list, addresses)


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

    print(f"{sym}")
