"""Cross-reference large amounts symbols and splits between two decomp projects.

The usual use of `cross_symbol` is to find where reference code lives in the
current game. But here, we turn it around: for each symbol of the current game,
we look up the longest matching run (`_Crossing`) in the further-decompiled
reference game.

We then aggregate all of said 'crossings' and filter those that are consistent
with each other (no overlaps), taking also advantage of the fact that objects
are usually compiled in memory addresses following a consistent order.

This way, we're able to sweep large address ranges and recover names and splits
very quickly.
"""

import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from cross_split import cross_splits
from cross_symbol import cross_symbols
from splits import ObjectSplit, parse_splits
from symbols import Symbol, Symbols, parse_symbols


parser = argparse.ArgumentParser(
    description="Attempts to perform a mass cross-reference of symbols and splits "
    + "from one decomp project to another, by composing and filtering operations "
    + "from cross_symbol and cross_split."
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
parser.add_argument(
    "address_ranges",
    type=lambda x: int(x, 0),
    nargs="*",
    help="Ints separated by spaces: pairs of ints (address ranges) to be processed. "
    + "in the CURRENT code. By default, the whole map is processed",
)


# Minimum run length before a match is considered. Short runs are dominated by
# coincidental size/section matches.
_MIN_CROSSING_LENGTH = 4
# How far the ref/current symbol-index offset may jump between two chained
# crossings. Library code links in roughly the same order, so this stays small;
# it also bounds how far a chain is allowed to wander.
_MAX_OFFSET_DRIFT = 30


@dataclass
class _Crossing:
    current_address_idx: int
    ref_address_idx: int
    length: int

    @property
    def idx_offset(self) -> int:
        return self.ref_address_idx - self.current_address_idx

    def is_mergeable_with(self, _o: Self) -> bool:
        return (self.idx_offset == _o.idx_offset) and (
            min(self.ref_address_idx + self.length, _o.ref_address_idx + _o.length)
            >= max(self.ref_address_idx, _o.ref_address_idx)
        )

    def merge(self, _o: Self) -> Self:
        current_address_idx = min(self.current_address_idx, _o.current_address_idx)
        max_current_address = max(
            self.current_address_idx + self.length, _o.current_address_idx + _o.length
        )
        length = max_current_address - current_address_idx
        ref_address_idx = current_address_idx + self.idx_offset
        return type(self)(current_address_idx, ref_address_idx, length)


class _AddressCrossings:
    def __init__(self) -> None:
        self._crossings_by_offset: dict[int, list[_Crossing]] = defaultdict(list)

    def add(self, x: _Crossing) -> None:
        self._crossings_by_offset[x.idx_offset].append(x)

    def _merge_crossings(self) -> None:
        # Crossings are appended in increasing current-index order, so a single
        # forward pass coalesces all overlapping runs sharing an offset.
        for _, crossings in self._crossings_by_offset.items():
            i = 1
            while i < len(crossings):
                if crossings[i].is_mergeable_with(crossings[i - 1]):
                    crossings[i - 1] = crossings[i - 1].merge(crossings[i])
                    del crossings[i]
                else:
                    i += 1

    def get_crossings(self) -> list[_Crossing]:
        self._merge_crossings()
        flat_crossings = sorted(
            [c for crossings in self._crossings_by_offset.values() for c in crossings],
            key=lambda c: c.current_address_idx,
        )
        if not flat_crossings:
            return []
        best_length = [0] * len(flat_crossings)
        previous_crossing = [-1] * len(flat_crossings)

        for i, c_i in enumerate(flat_crossings):
            best_length[i] = c_i.length
            for j, c_j in enumerate(flat_crossings[:i]):
                # Library code should compile next to each other.
                if abs(c_i.idx_offset - c_j.idx_offset) > _MAX_OFFSET_DRIFT:
                    continue
                # A valid predecessor must not overlap in either index space.
                if (c_j.ref_address_idx + c_j.length <= c_i.ref_address_idx) and (
                    c_j.current_address_idx + c_j.length <= c_i.current_address_idx
                ):
                    if best_length[j] + c_i.length > best_length[i]:
                        best_length[i] = best_length[j] + c_i.length
                        previous_crossing[i] = j

        final_crossing_idx = max(
            range(len(flat_crossings)),
            key=lambda i: best_length[i],
        )
        output: list[_Crossing] = []
        i = final_crossing_idx
        while i != -1:
            output.append(flat_crossings[i])
            i = previous_crossing[i]
        output.reverse()
        return output


def get_longest_crossings(
    ref_syms: Symbols,
    current_syms: Symbols,
    current_address_start: int,
    current_address_end: int,
) -> list[_Crossing]:
    """Returns the longest, mutually-consistent crossings found within
    `current_address_start:current_address_end`, by iterating `cross_symbols(...)`
    over every current address in the range (and resolving conflicts).

    We pass arguments to said function the other way around, as the code originally
    was used to find where the _reference_ code lied in the _current_ code, whereas
    here we're trying to find _what parts of the current code_ have a strong correlation
    in the target code.
    """

    output = _AddressCrossings()

    assert current_address_end > current_address_start

    for current_address, current_address_idx in current_syms.addresses.items():
        if current_address < current_address_start:
            continue
        elif current_address >= current_address_end:
            break

        ref_longest_match_address, longest_match = cross_symbols(
            ref_syms=current_syms,
            current_syms=ref_syms,
            base_address=current_address,
        )
        if longest_match >= _MIN_CROSSING_LENGTH:
            ref_longest_match_address_idx = ref_syms.addresses[
                ref_longest_match_address
            ]
            output.add(
                _Crossing(
                    current_address_idx,
                    ref_longest_match_address_idx,
                    longest_match,
                )
            )

    return output.get_crossings()


def process_symbol_names_inplace(
    ref_syms: Symbols,
    crossings: list[_Crossing],
    out_current_syms: Symbols,
    out_indexed_current_syms: Symbols,
    out_indexed_ref_syms: Symbols,
) -> None:

    for c in crossings:
        for i in range(c.length):
            ref_idx = c.ref_address_idx + i
            current_idx = c.current_address_idx + i

            r_sym = ref_syms.symbols[ref_idx]
            out_current_syms.symbols[current_idx].copy_attributes_from(r_sym)
            out_indexed_ref_syms.symbols[
                ref_idx
            ].name = f"{r_sym.name}@0x{r_sym.address:x}"
            out_indexed_current_syms.symbols[current_idx].copy_attributes_from(
                out_indexed_ref_syms.symbols[ref_idx]
            )


def filter_splits(
    splits: list[ObjectSplit],
    address_ranges: list[tuple[int, int]],
) -> list[ObjectSplit]:
    output: list[ObjectSplit] = []
    for obj_split in splits:
        new_splits = [
            s
            for s in obj_split.splits
            if any((start < s.start < s.end < end) for start, end in address_ranges)
        ]
        if new_splits:
            output.append(
                ObjectSplit(
                    file=obj_split.file,
                    splits=new_splits,
                )
            )

    return output


def filter_symbols(
    symbols: Symbols,
    address_ranges: list[tuple[int, int]],
) -> list[Symbol]:
    return [
        s
        for s in symbols.symbols
        if any(
            s.address > start and s.address + s.size < end
            for start, end in address_ranges
        )
    ]


def do_mass_crossing(
    ref_syms: Symbols,
    current_syms: Symbols,
    ref_splits: list[ObjectSplit],
    address_ranges: list[tuple[int, int]],
) -> tuple[list[Symbol], list[ObjectSplit]]:
    indexed_current_syms = deepcopy(current_syms)
    indexed_ref_syms = deepcopy(ref_syms)

    for start, end in address_ranges:
        crossings = get_longest_crossings(
            ref_syms,
            current_syms,
            start,
            end,
        )
        process_symbol_names_inplace(
            ref_syms,
            crossings,
            current_syms,
            indexed_current_syms,
            indexed_ref_syms,
        )
    new_current_splits = cross_splits(
        ref_splits, indexed_ref_syms, indexed_current_syms
    )
    return (
        filter_symbols(current_syms, address_ranges),
        filter_splits(new_current_splits, address_ranges),
    )


if __name__ == "__main__":
    args = parser.parse_args()
    ref_splits_path: Path = args.ref_splits_path
    ref_path: Path = args.ref_path
    current_path: Path = args.current_path
    address_ranges_raw: list[int] = args.address_ranges
    if len(address_ranges_raw) % 2 != 0:
        parser.error("Address ranges should come in pairs.")
    address_ranges = list(zip(address_ranges_raw[::2], address_ranges_raw[1::2]))

    ref_splits_txt = ref_splits_path.read_text()
    ref_syms_txt = ref_path.read_text()
    current_syms_txt = current_path.read_text()

    ref_splits = parse_splits(ref_splits_txt)
    ref_syms = parse_symbols(ref_syms_txt)
    current_syms = parse_symbols(current_syms_txt)
    if not address_ranges:
        all_addresses = current_syms.addresses.keys()
        address_ranges = [(min(all_addresses), max(all_addresses) + 1)]

    symbols, splits = do_mass_crossing(
        ref_syms,
        current_syms,
        ref_splits,
        address_ranges,
    )
    for sym in symbols:
        print(f"{sym}")
    print("\n" * 10)
    for spl in splits:
        print(f"{spl}")
