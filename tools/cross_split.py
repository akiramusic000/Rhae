#!/usr/bin/env python3

from pathlib import Path
from symbols import Symbols, parse_symbols
from splits import Split, ObjectSplit, parse_splits
import argparse
import functools
import sys


parser = argparse.ArgumentParser(
    description="Cross splits one decomp project to another, using symbol names to translate addresses."
)
parser.add_argument(
    "ref_splits_path", type=Path, help="Path to the splits.txt for the reference game."
)
parser.add_argument(
    "ref_path", type=Path, help="Path to the symbols.txt for the reference game."
)
parser.add_argument(
    "current_path", type=Path, help="Path to the symbols.txt of the current game."
)


warn = functools.partial(print, file=sys.stderr)


def translate(split: Split, current_syms: Symbols, ref_syms: Symbols) -> Split | None:
    addresses = [split.start, split.end]

    for address_i, address in enumerate(addresses):
        ref_idx = ref_syms.addresses.get(address)
        if ref_idx is None:
            warn(f"No symbol at 0x{address:X}")
            return None

        ref_sym = ref_syms.symbols[ref_idx]
        final_sym = None

        for sym in current_syms.symbols:
            if ref_sym.name == sym.name:
                if final_sym == None:
                    final_sym = sym
                else:
                    warn(f"Duplicate symbol! {ref_sym.name}")
                    return None

        if final_sym != None:
            addresses[address_i] = final_sym.address
        else:
            warn(f"Not found! {ref_sym.name}")
            return None

    return Split(split.section, *addresses)


def cross_splits(
    ref_splits: list[ObjectSplit],
    ref_syms: Symbols,
    current_syms: Symbols,
) -> list[ObjectSplit]:
    output_splits: list[ObjectSplit] = []

    for object_splits in ref_splits:
        translated_splits = list(
            filter(
                None,
                (
                    translate(split, current_syms, ref_syms)
                    for split in object_splits.splits
                ),
            )
        )
        if translated_splits:
            output_splits.append(ObjectSplit(object_splits.file, translated_splits))
    return output_splits


if __name__ == "__main__":
    args = parser.parse_args()
    ref_splits_path: Path = args.ref_splits_path
    ref_path: Path = args.ref_path
    current_path: Path = args.current_path

    ref_splits_txt = ref_splits_path.read_text()
    ref_syms_txt = ref_path.read_text()
    current_syms_txt = current_path.read_text()

    ref_splits = parse_splits(ref_splits_txt)
    ref_syms = parse_symbols(ref_syms_txt)
    current_syms = parse_symbols(current_syms_txt)

    for object_splits in cross_splits(ref_splits, ref_syms, current_syms):
        print(f"{object_splits}\n")
