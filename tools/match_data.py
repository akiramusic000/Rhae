from copy import copy
from collections import defaultdict
from splits import (
    Split,
    ObjectSplit,
    SectionType,
    parse_splits,
    check_is_section_type,
    slice_object_splits,
)
from symbols import Symbols, Symbol, parse_symbols
from pathlib import Path
from typing import Any, get_args

import argparse
import json
import functools
import re
import subprocess
import sys

parser = argparse.ArgumentParser(
    description="Attempts to recover non `.text` fields for object ranges, by reaching "
    + "into each function's references and comparing them to the compiled code's ones."
)
parser.add_argument(
    "-r",
    "--root",
    type=Path,
    help="Path to project root.",
    default=".",
)

parser.add_argument("filename", type=str, help="Split filename to start matching from.")
parser.add_argument(
    "end_filename",
    type=str,
    help="Split filename to stop matching at. Leave unset to only check one split, "
    + "use '-' to extend to the final split.",
    default="",
    nargs="?",
)

_CONFIGURE_PY = "configure.py"

warn = functools.partial(print, file=sys.stderr)


def _handle_glob(base_path: Path, glob: str) -> Path:
    try:
        return next(base_path.glob(glob))
    except StopIteration as e:
        raise RuntimeError(
            f"No '{glob}' found in '{base_path}', "
            + f"maybe try to run `python3 {_CONFIGURE_PY}; ninja`?"
        ) from e


def _get_objdiff_cli(root: Path) -> Path:
    return root / "build" / "tools" / "objdiff-cli"


def _get_current_data(
    root: Path,
) -> tuple[Symbols, list[ObjectSplit]]:
    base_path = root / "config"
    symbols_txt = _handle_glob(base_path, "*/symbols.txt").read_text()
    splits_txt = _handle_glob(base_path, "*/splits.txt").read_text()
    symbols = parse_symbols(symbols_txt)
    object_splits = parse_splits(splits_txt)
    return symbols, object_splits


def _object_to_objdiff(x: str) -> str:
    return f"main/{Path(x.strip('/')).with_suffix('')}"


def _parse_hex_suffix(name: str) -> int | None:
    _, sep, addr = name.rpartition("_")
    re_addr = re.compile(r"^[0-9A-Fa-f]{8}$")
    if sep and re_addr.match(addr):
        return int(addr, 16)
    return None


def _lookup_symbol(
    name: str,
    symbols: Symbols,
    syms_by_name: dict[str, list[Symbol]],
) -> Symbol | None:
    candidates = syms_by_name.get(name, [])
    if len(candidates) == 1:
        return candidates[0]

    base, sep, _ = name.rpartition("_")
    if sep and (base in syms_by_name):
        addr = _parse_hex_suffix(name)
        if addr is not None and addr in symbols.addresses:
            return symbols.symbols[symbols.addresses[addr]]
        candidates = syms_by_name.get(base, [])
        if len(candidates) == 1:
            return candidates[0]

    return None


def _get_symbol_sections(
    name: str,
    symbols: Symbols,
    syms_by_name: dict[str, list[Symbol]],
) -> SectionType | None:
    symbol = _lookup_symbol(name, symbols, syms_by_name)
    if symbol is None:
        return None
    return check_is_section_type(symbol.section)


def _merge_split(o_split: ObjectSplit, new_splits: list[Split]) -> ObjectSplit:
    output_splits: list[Split] = []
    common_sections: set[SectionType] = set()
    for x in new_splits:
        for x2 in o_split.splits:
            if x.section != x2.section:
                continue
            start = min(x.start, x2.start)
            end = max(x.end, x2.end)
            non_overlap_start = min(x.end, x2.end)
            non_overlap_end = max(x.start, x2.start)
            if non_overlap_start < non_overlap_end:
                warn(
                    f"Warning: merging range (0x{start:08X}, 0x{end:08X}) including the "
                    + f"non-overlapping range (0x{non_overlap_start:08X}, 0x{non_overlap_end:08X})!"
                )
            output_splits.append(Split(x.section, start, end))
            common_sections.add(x.section)

    output_splits.extend([x for x in new_splits if x.section not in common_sections])
    output_splits.extend(
        [x for x in o_split.splits if x.section not in common_sections]
    )
    return ObjectSplit(o_split.file, output_splits)


def _align_splits(splits: list[Split]) -> list[Split]:
    output_splits: list[Split] = []
    for s in splits:
        start = s.start
        end = s.end
        # dtk alignment rules
        align = (
            4
            if s.section
            in (".text", ".init", "extab", "extabindex", ".ctors", ".dtors")
            else 8
        )
        start -= start % align
        end += (-end) % align
        output_splits.append(Split(s.section, start, end))
    return output_splits


def _get_address_range(syms: list[Symbol]) -> tuple[int, int]:
    dims = [(s.address, s.size) for s in syms]
    return min(s[0] for s in dims), max(s[0] + s[1] for s in dims)


def _write_right_data_to_sym(sym: Symbol, right_sym_raw: dict[str, Any]) -> None:
    sym.name = right_sym_raw["name"]
    right_size = right_sym_raw.get("size")
    if right_size is not None:
        sym.size = int(right_size)
    if right_sym_raw.get("kind") == "SYMBOL_OBJECT":
        sym.type = "object"
    match right_sym_raw["flags"]:
        case {"weak": True}:
            sym.scope = "weak"
        case {"global": True}:
            sym.scope = "global"
        case {"local": True}:
            sym.scope = "local"


def _match_split(
    objdiff_output: dict[str, Any],
    symbols: Symbols,
    syms_by_name: dict[str, list[Symbol]],
) -> tuple[list[Symbol], list[Split]]:
    left_syms: list[dict[str, Any]] = objdiff_output["left"]["symbols"]
    right_syms: list[dict[str, Any]] = objdiff_output.get("right", {}).get(
        "symbols", []
    )
    global_left_syms_by_type: dict[SectionType, list[dict[str, Any]]] = {
        section: [
            sym
            for sym in left_syms
            if _get_symbol_sections(sym["name"], symbols, syms_by_name) == section
        ]
        for section in get_args(SectionType)
    }

    syms_to_add: dict[str, dict[int, Symbol]] = defaultdict(dict)
    for sym in global_left_syms_by_type[".text"]:
        if "instructions" not in sym.keys():
            continue
        for idx, instruction in enumerate(sym["instructions"]):
            if instruction.get("diff_kind") != "DIFF_ARG_MISMATCH":
                continue
            details = instruction.get("instruction")
            if details is None:
                continue
            reloc = details.get("relocation")
            if reloc is None:
                continue
            reloc_ref = left_syms[reloc["target_symbol"]]
            if not reloc_ref.get("flags", {}).get("global"):
                continue
            reloc_sym = copy(_lookup_symbol(reloc_ref["name"], symbols, syms_by_name))
            if reloc_sym is None:
                continue
            right_instruction = right_syms[sym["target_symbol"]]["instructions"][idx]
            right_ref = right_instruction["instruction"].get("relocation")
            if right_ref is None:
                continue
            left_offset = int(
                reloc.get("addend") or 0
            )  # the LEFT reloc dict (line 215)
            right_offset = int(right_ref.get("addend") or 0)
            reloc_sym.address += left_offset - right_offset
            right_sym = right_syms[right_ref["target_symbol"]]
            # If 'kind' is defined on the sym, the sym is part of the object,
            # if not, it's an external reference and shall be ignored
            if "kind" not in right_sym.keys():
                continue
            _write_right_data_to_sym(
                reloc_sym,
                right_syms[right_ref["target_symbol"]],
            )
            syms_to_add[reloc_sym.section][reloc_sym.address] = reloc_sym
    ouptput_splits = [
        Split(check_is_section_type(section), *_get_address_range(list(syms.values())))
        for section, syms in syms_to_add.items()
    ]
    return [i for syms in syms_to_add.values() for i in syms.values()], ouptput_splits


def do_match_data(
    object_splits: list[ObjectSplit],
    symbols: Symbols,
    filename: str,
    filename_end: str,
) -> tuple[dict[str, Symbols], list[ObjectSplit]]:
    syms_by_name: dict[str, list[Symbol]] = defaultdict(list)
    for s in symbols.symbols:
        syms_by_name[s.name].append(s)

    match filename_end:
        case "":
            object_splits = slice_object_splits(object_splits, filename, None)[:1]
        case "-":
            object_splits = slice_object_splits(object_splits, filename, None)
        case z:
            object_splits = slice_object_splits(object_splits, filename, z)
    output_o_splits: list[ObjectSplit] = []
    output_syms: dict[str, Symbols] = {}
    for o_split in object_splits:
        objdiff_output = json.loads(
            subprocess.run(
                [
                    _get_objdiff_cli(root),
                    "diff",
                    "-p",
                    root,
                    "-u",
                    _object_to_objdiff(o_split.file),
                    "--output",
                    "-",
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        new_symbols, new_splits = _match_split(objdiff_output, symbols, syms_by_name)
        output_o_splits.append(_merge_split(o_split, _align_splits(new_splits)))
        if new_symbols:
            output_syms[o_split.file] = Symbols.of(new_symbols)
    return output_syms, output_o_splits


def print_match_data(
    new_syms: dict[str, Symbols],
    new_object_splits: list[ObjectSplit],
) -> None:
    print("Matches (splits.txt):")
    print("\n" * 3)
    for o_split in new_object_splits:
        print(f"{o_split}")

    print("\n" * 5 + "-" * 15)
    print("Matches (symbols.txt):")
    print("\n" * 3)
    for filename, syms in new_syms.items():
        print(f"\t// {filename}:")
        for s in syms.symbols:
            print(f"{s}")
        print("\n" * 3)


if __name__ == "__main__":
    args = parser.parse_args()
    root: Path = args.root
    if not (root / _CONFIGURE_PY).is_file():
        parser.error(
            f"Project root '{root}' does not contain {_CONFIGURE_PY}, "
            + "please double-check that it's a valid project"
        )
    filename: str = args.filename
    end_filename: str = args.end_filename

    symbols, object_splits = _get_current_data(root)
    new_syms, new_object_splits = do_match_data(
        object_splits, symbols, filename, end_filename
    )
    print_match_data(new_syms, new_object_splits)
