from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from rapidfuzz.fuzz import partial_ratio, partial_ratio_alignment
from rapidfuzz.distance.Levenshtein import opcodes
from splits import Split, ObjectSplit, SectionType, parse_splits, check_is_section_type
from symbols import Symbols, Symbol, parse_symbols
from pathlib import Path
from pprint import pp
from typing import Self

import argparse
import functools
import sys

parser = argparse.ArgumentParser(
    description="Attempts to perform a mass cross-reference of symbols and splits "
    + "from one decomp project to another."
)
parser.add_argument(
    "ref_splits_path", type=Path, help="Path to the splits.txt for the reference game."
)
parser.add_argument(
    "ref_syms_path", type=Path, help="Path to the symbols.txt for the reference game."
)
parser.add_argument(
    "current_syms_path", type=Path, help="Path to the symbols.txt of the current game."
)
parser.add_argument(
    "start_split_filename", type=str, help="Split filename to start matching from."
)
parser.add_argument(
    "end_split_filename",
    type=str,
    help="Split filename to stop matching at. Use '-' to include the final split.",
)


_NEEDLE_SIZE_THRESHOLD = 5
_NEEDLE_CONFIDENCE_THRESHOLD = 0.7

_HOLE_FILLING_CONFIDENCE_THRESHOLD = 0.6

_MASK = -1


# ------------------------------------------
# %% Preprocessing functions
# ------------------------------------------


def _symbols_to_size_seq(
    symbols: Symbols,
    start_addr: int | None = None,
    end_addr: int | None = None,
) -> list[int]:
    def index_in_symbols(addr: int | None) -> int | None:
        if addr is None:
            return None

        # We can't use symbols.addresses as symbols and splits sometimes don't align,
        # so we do O(log(n)) slicing instead
        return bisect_left(symbols.symbols, addr, key=lambda s: s.address)

    return [
        s.size
        for s in symbols.symbols[
            index_in_symbols(start_addr) : index_in_symbols(end_addr)
        ]
    ]


def _object_splits_to_size_sequence(
    symbols: Symbols,
    object_splits: list[ObjectSplit],
) -> dict[SectionType, dict[str, tuple[Split, list[int]]]]:

    output: dict[SectionType, dict[str, tuple[Split, list[int]]]] = defaultdict(dict)
    for o_split in object_splits:
        for s in o_split.splits:
            end_addr = s.end if s.end <= symbols.symbols[-1].address else None
            output[s.section][o_split.file] = (
                s,
                _symbols_to_size_seq(symbols, s.start, end_addr),
            )
    return output


def _symbols_to_size_sequences(
    symbols: Symbols,
) -> dict[SectionType, list[int]]:

    first_symbol = symbols.symbols[0]
    start_addr = first_symbol.address
    current_section = check_is_section_type(first_symbol.section)
    section_addresses: dict[SectionType, tuple[int, int | None]] = {}

    for s in symbols.symbols:
        if s.section != current_section:
            section_addresses[current_section] = (start_addr, s.address)
            start_addr = s.address
            current_section = check_is_section_type(s.section)
    section_addresses[current_section] = (start_addr, None)

    return {
        section: _symbols_to_size_seq(symbols, start, end)
        for section, (start, end) in section_addresses.items()
    }


def _slice_object_splits(
    object_splits: list[ObjectSplit],
    filename_start: str,
    filename_end: str | None,
) -> list[ObjectSplit]:
    filename_start = filename_start.rstrip(":")

    for idx, o_split in enumerate(object_splits):
        if o_split.file == filename_start:
            start_idx = idx
            break
    else:
        raise ValueError(f"'{filename_start}' not found in 'splits.txt'")

    if filename_end is None:
        end_idx = None
    else:
        filename_end = filename_end.rstrip(":")
        for idx, o_split in enumerate(object_splits[start_idx:]):
            if o_split.file == filename_end:
                end_idx = idx + start_idx
                break
        else:
            raise ValueError(
                f"'{filename_end}' not found in 'splits.txt' after '{filename_start}'"
            )

    return object_splits[start_idx:end_idx]


# ------------------------------------------
# %% Matching functions
# ------------------------------------------


def _first_matching_index(needle: list[int], haystack: list[int]) -> int:
    haystack = haystack.copy()
    base_score = partial_ratio(needle, haystack)

    for i, x in enumerate(haystack):
        haystack[i] = _MASK
        degraded = partial_ratio(needle, haystack) < base_score
        haystack[i] = x
        if degraded:
            return i

    return 0


@dataclass(frozen=True)
class Bounds:
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start

    def shift(self, delta: int) -> Self:
        return type(self)(self.start + delta, self.end + delta)


@dataclass(frozen=True)
class Match:
    filename: str
    needle_bounds: Bounds
    haystack_bounds: Bounds
    score: float

    @property
    def final_score(self) -> float:
        return self.needle_bounds.size * self.score**2

    def _equalize(self) -> Self:
        """Fixes an issue where the needle and haystack are of different size when matching on edges"""
        needle, haystack = self.needle_bounds, self.haystack_bounds
        if needle.size > haystack.size:
            haystack = (
                Bounds(haystack.start, needle.size)
                if haystack.start == 0
                else Bounds(haystack.end - needle.size, haystack.end)
            )
        elif needle.size < haystack.size:
            needle = (
                Bounds(needle.start, haystack.size)
                if needle.start == 0
                else Bounds(needle.end - haystack.size, needle.end)
            )
        return self.with_bounds(needle_bounds=needle, haystack_bounds=haystack)

    def _trim(self, needle: list[int], haystack: list[int]) -> Self:
        """Resizes needle and haystack bounds because rapidfuzz makes them the same size on most cases"""
        nb, hb = self.needle_bounds, self.haystack_bounds
        n, h = needle[nb.start : nb.end], haystack[hb.start : hb.end]
        rel_start = _first_matching_index(n, h)
        rel_end = nb.size - _first_matching_index(n[::-1], h[::-1])
        return self.with_bounds(
            needle_bounds=Bounds(nb.start + rel_start, nb.start + rel_end),
            haystack_bounds=Bounds(hb.start + rel_start, hb.start + rel_end),
        )

    @classmethod
    def of(cls, filename: str, needle: list[int], haystack: list[int]) -> Self | None:
        raw = partial_ratio_alignment(needle, haystack)
        if raw is None:
            return None
        match = cls(
            filename,
            Bounds(raw.src_start, raw.src_end),
            Bounds(raw.dest_start, raw.dest_end),
            raw.score / 100,  # [0,100] -> [0,1]
        )
        if match.score < 1.0:
            match = match._equalize()._trim(needle, haystack)
        return match

    def with_bounds(
        self,
        *,
        needle_bounds: Bounds | None = None,
        haystack_bounds: Bounds | None = None,
    ) -> Self:
        needle_bounds = needle_bounds or self.needle_bounds
        haystack_bounds = haystack_bounds or self.haystack_bounds
        return type(self)(self.filename, needle_bounds, haystack_bounds, self.score)


def _get_bounded_haystack_holes(
    haystack_space: dict[int, str],
) -> list[tuple[tuple[str, str], Bounds]]:

    if not haystack_space:
        return []
    used_idxs = haystack_space.keys()
    leftover_hole_idxs = set(range(min(used_idxs), max(used_idxs) + 1)).difference(
        used_idxs
    )

    sequences: list[list[int]] = []
    prev_value: int | None = None
    for idxs in sorted(leftover_hole_idxs):
        if idxs - 1 != prev_value:
            sequences.append([idxs])
        else:
            sequences[-1].append(idxs)
        prev_value = idxs

    return [
        (
            (haystack_space[seq[0] - 1], haystack_space[seq[-1] + 1]),
            Bounds(seq[0], seq[-1] + 1),
        )
        for seq in sequences
    ]


# ------------------------------------------
# %% Matching lifetime
# ------------------------------------------


@dataclass
class CrossTextResult:
    matches: dict[str, tuple[Split, list[Symbol]]]
    holes: list[tuple[str | None, str | None, Bounds]]
    unmatched: set[str]


@dataclass
class CrossTextRun:
    needle_map: dict[str, tuple[Split, list[int]]]
    haystack: list[int]
    needle_syms: Symbols
    haystack_syms: Symbols
    accepted_matches: list[Match] = field(default_factory=list)
    haystack_space: dict[int, str] = field(default_factory=dict)
    rejected: set[str] = field(default_factory=set)

    def _get_needle(self, m: Match) -> list[int]:
        return self.needle_map[m.filename][1]

    def _get_needle_split(self, m: Match) -> Split:
        return self.needle_map[m.filename][0]

    def _get_overlapping_needle(self, m: Match) -> list[int]:
        needle = self._get_needle(m)
        return needle[m.needle_bounds.start : m.needle_bounds.end]

    def _dilate(self, m: Match) -> Match:
        overlapping_needle = self._get_overlapping_needle(m)
        base_score = partial_ratio(
            overlapping_needle,
            self.haystack[m.haystack_bounds.start : m.haystack_bounds.end],
        )

        for dilating_right in (True, False):
            while True:
                start, end = m.haystack_bounds.start, m.haystack_bounds.end

                if dilating_right:
                    new_addr = end
                    end += 1
                else:
                    start -= 1
                    new_addr = start

                if new_addr in self.haystack_space:
                    break

                working_haystack = self.haystack[start:end]
                padding = [_MASK] * (len(working_haystack) - len(overlapping_needle))
                padded_needle = (
                    (not dilating_right) * padding
                    + overlapping_needle
                    + dilating_right * padding
                )
                new_score = partial_ratio(padded_needle, working_haystack)

                if new_score > base_score:
                    m = m.with_bounds(haystack_bounds=Bounds(start, end))
                    base_score = new_score
                    self.haystack_space[new_addr] = m.filename
                else:
                    break
        return m

    def _filter(self, candidate_matches: list[Match]) -> None:
        for m in candidate_matches:
            start, end = m.haystack_bounds.start, m.haystack_bounds.end
            if any(i in self.haystack_space for i in range(start, end)):
                self.rejected.add(m.filename)
            else:
                for i in range(start, end):
                    self.haystack_space[i] = m.filename
                if m.score < 1.0:
                    m = self._dilate(m)
                self.accepted_matches.insert(
                    bisect_left(
                        self.accepted_matches,
                        start,
                        key=lambda m: m.haystack_bounds.start,
                    ),
                    m,
                )

    def _fill(self) -> None:
        haystack_holes = _get_bounded_haystack_holes(self.haystack_space)
        all_objects = list(self.needle_map.keys())
        object_order = {filename: idx for idx, filename in enumerate(all_objects)}

        for (previous_split, next_split), hole_bounds in haystack_holes:
            objects_in_between = all_objects[
                object_order[previous_split] + 1 : object_order[next_split]
            ]
            leftover_splits_in_between = list(
                sorted(
                    (
                        (filename, self.needle_map[filename])
                        for filename in objects_in_between
                        if filename in self.rejected
                    ),
                    key=lambda i: len(i[1][1]),
                    reverse=True,
                )
            )
            candidate_matches: list[Match] = []

            for filename, (_, needle) in leftover_splits_in_between:
                match = Match.of(
                    filename,
                    needle,
                    self.haystack[hole_bounds.start : hole_bounds.end],
                )
                if match is None:
                    print("Weird match error!", file=sys.stderr)
                    continue
                match = match.with_bounds(
                    haystack_bounds=match.haystack_bounds.shift(hole_bounds.start)
                )
                if match.score > _HOLE_FILLING_CONFIDENCE_THRESHOLD:
                    self.rejected.remove(filename)
                    candidate_matches.append(match)
            self._filter(candidate_matches)

    def _get_overlapping_syms(
        self,
        m: Match,
    ) -> tuple[list[Symbol], list[Symbol]]:
        needle_start_idx = (
            self.needle_syms.addresses[self._get_needle_split(m).start]
            + m.needle_bounds.start
        )
        overlapping_needle_syms = self.needle_syms.symbols[
            needle_start_idx : needle_start_idx + m.needle_bounds.size
        ]
        overlapping_haystack_syms = self.haystack_syms.symbols[
            m.haystack_bounds.start : m.haystack_bounds.start + m.haystack_bounds.size
        ]
        return overlapping_needle_syms, overlapping_haystack_syms

    def _copy_symbols(
        self,
        m: Match,
        overlapping_needle_syms: list[Symbol],
        overlapping_haystack_syms: list[Symbol],
    ) -> None:
        overlapping_haystack = self.haystack[
            m.haystack_bounds.start : m.haystack_bounds.end
        ]
        for op in opcodes(self._get_overlapping_needle(m), overlapping_haystack):
            if op.tag != "equal":
                continue
            op_length = op.dest_end - op.dest_start
            assert op_length == op.src_end - op.src_start
            for idx in range(op_length):
                overlapping_haystack_syms[op.dest_start + idx].copy_attributes_from(
                    overlapping_needle_syms[op.src_start + idx]
                )

    def _get_orphaned_addresses(self) -> list[tuple[str | None, str | None, Bounds]]:
        orphaned = sorted(set(range(len(self.haystack))) - self.haystack_space.keys())
        contiguous: list[Bounds] = []
        symbols = self.haystack_syms.symbols

        def bound_addr(i: int) -> int:
            return (
                symbols[i].address
                if i < len(symbols)
                else symbols[-1].address + symbols[-1].size
            )

        for idx in orphaned:
            if contiguous and contiguous[-1].end == idx:
                contiguous[-1] = Bounds(contiguous[-1].start, idx + 1)
            else:
                contiguous.append(Bounds(idx, idx + 1))
        return [
            (
                self.haystack_space.get(b.start - 1),
                self.haystack_space.get(b.end),
                Bounds(bound_addr(b.start), bound_addr(b.end)),
            )
            for b in contiguous
        ]

    def run(self) -> CrossTextResult:
        candidate_matches: list[Match] = []

        for filename, (_, needle) in self.needle_map.items():
            if len(needle) < _NEEDLE_SIZE_THRESHOLD:
                self.rejected.add(filename)
                continue

            match = Match.of(filename, needle, self.haystack)
            if match is None:
                self.rejected.add(filename)
                continue

            if match.score < _NEEDLE_CONFIDENCE_THRESHOLD:
                self.rejected.add(filename)
                continue

            candidate_matches.append(match)

        candidate_matches.sort(reverse=True, key=lambda m: m.final_score)

        self._filter(candidate_matches)
        self._fill()

        matches: dict[str, tuple[Split, list[Symbol]]] = {}

        for m in self.accepted_matches:
            start_idx, end_idx = m.haystack_bounds.start, m.haystack_bounds.end
            start_addr = self.haystack_syms.symbols[start_idx].address
            try:
                end_addr = self.haystack_syms.symbols[end_idx].address
            except IndexError:
                end_addr = (
                    self.haystack_syms.symbols[-1].address
                    + self.haystack_syms.symbols[-1].size
                )
            new_split = Split(".text", start_addr, end_addr)

            overlapping_needle_syms, overlapping_haystack_syms = (
                self._get_overlapping_syms(m)
            )
            self._copy_symbols(
                m,
                overlapping_needle_syms,
                overlapping_haystack_syms,
            )
            matches[m.filename] = (new_split, overlapping_haystack_syms)

        return CrossTextResult(matches, self._get_orphaned_addresses(), self.rejected)


# ------------------------------------------
# %% Main
# ------------------------------------------


def do_mass_cross(
    needle_splits: list[ObjectSplit],
    needle_syms: Symbols,
    haystack_syms: Symbols,
    start_split_filename: str,
    end_split_filename: str | None,
) -> CrossTextResult:
    selected_splits = _slice_object_splits(
        needle_splits,
        start_split_filename,
        end_split_filename,
    )
    needles_by_section = _object_splits_to_size_sequence(needle_syms, selected_splits)
    haystacks_by_section = _symbols_to_size_sequences(haystack_syms)

    text_run = CrossTextRun(
        needles_by_section[".text"],
        haystacks_by_section[".text"],
        Symbols.of([s for s in needle_syms.symbols if s.section == ".text"]),
        Symbols.of([s for s in haystack_syms.symbols if s.section == ".text"]),
    )
    return text_run.run()


def print_crosstext_results(results: CrossTextResult) -> None:
    ww = functools.partial(pp, stream=sys.stderr)
    warn = functools.partial(print, file=sys.stderr, flush=True)
    warn("\nHoles (preceding_split; posterior_split; bounds):")
    for preceding_split, posterior_split, bounds in results.holes:
        warn(
            f"\t{preceding_split}; {posterior_split}; (0x{bounds.start:08X} : 0x{bounds.end:08X})"
        )

    warn("\nUnmatched files:")
    ww(results.unmatched)

    print("\n" * 5 + "-" * 15)
    print("Matches (splits.txt):")
    print("\n" * 3)
    for filename, (split, _) in results.matches.items():
        object_split = ObjectSplit(filename, [split])
        print(f"{object_split}")

    print("\n" * 5 + "-" * 15)
    print("Matches (symbols.txt):")
    print("\n" * 3)

    for filename, (_, syms) in results.matches.items():
        print(f"\t// {filename}:")
        for s in syms:
            print(f"{s}")
        print("\n" * 3)

    pass


if __name__ == "__main__":
    args = parser.parse_args()
    ref_splits_path: Path = args.ref_splits_path
    ref_syms_path: Path = args.ref_syms_path
    current_syms_path: Path = args.current_syms_path

    ref_splits_txt = ref_splits_path.read_text()
    ref_syms_txt = ref_syms_path.read_text()
    current_syms_txt = current_syms_path.read_text()

    ref_splits = parse_splits(ref_splits_txt)
    ref_syms = parse_symbols(ref_syms_txt)
    current_syms = parse_symbols(current_syms_txt)

    start_split_filename: str = args.start_split_filename
    end_split_filename: str | None = args.end_split_filename
    end_split_filename = None if end_split_filename == "-" else end_split_filename

    results = do_mass_cross(
        ref_splits,
        ref_syms,
        current_syms,
        start_split_filename,
        end_split_filename,
    )
    print_crosstext_results(results)
