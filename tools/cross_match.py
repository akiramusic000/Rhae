#!/usr/bin/env python3
"""
cross_match.py

Cross-project matching tool for Wii Sports -> Wii Play decompilation reuse.

Compares masked function bodies from both projects' ELF objects (produced by
dtk).  Relocation-dependent instruction bytes are zeroed out before comparison
so that only the invariant code is matched.

An object is "implemented" when it appears in the project's configure.py
with a compilable source-path (.c / .cpp / .s).  Objects listed as raw .o
blobs (unsplit) are ignored.

Usage:
    python tools/cross_match.py ../<ogws_project_dir>

Output directory:  build/cross_match/
    report.txt             overall statistics
    configure_proposal.txt configure.py snippet
    splits_proposal.txt    first approximation for splits.txt
    symbols_proposal.txt   first approximation for symbols.txt
    anomalies.txt          everything that did not fit the expected model

WARNING: please do not take this as the ground truth! It's helpful to locate
common functions semi-automatically to start the diffing process, but it's
sometimes buggy and you might have to fiddle with splits and symbols a bit.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Callable

try:
    from elftools.elf.elffile import ELFFile
except ImportError as exc:
    raise SystemExit(
        "pyelftools is required. Install it with:"
        + "\n\tpython3 -m pip install pyelftools"
    ) from exc

# ===========================================================================
# Project-specific constants
# ===========================================================================

VERSION_SPORTS = "RSPE01_01"  # Wii Sports USA Rev 1
VERSION_PLAY = "RHAE01"  # Wii Play

RELOC_MASKS: dict[int, int] = {
    4: 0x0000FFFF,  # R_PPC_ADDR16_LO
    5: 0x0000FFFF,  # R_PPC_ADDR16_HI
    6: 0x0000FFFF,  # R_PPC_ADDR16_HA
    10: 0x03FFFFFC,  # R_PPC_REL24
    11: 0x0000FFFC,  # R_PPC_REL14
    109: 0x001FFFFF,  # R_PPC_EMB_SDA21
}
DEFAULT_MASK = 0xFFFFFFFF

# Source-file extensions recognised by dtk / configure.py.
SOURCE_EXTS: tuple[str, ...] = (".c", ".cpp", ".s")

# ELF symbol constants
_SYM_TYPE_FUNC = "STT_FUNC"
_SYM_VIS_HIDDEN = "STV_HIDDEN"

# ===========================================================================
# Anomaly log: Write error logs to anomalies.txt at the end of the run.
# ===========================================================================

_anomalies: list[str] = []


def _note_anomaly(msg: str) -> None:
    _anomalies.append(msg)


def _flush_anomalies(path: Path) -> None:
    content = "\n".join(_anomalies) if _anomalies else "(none)"
    path.write_text(content + "\n", encoding="utf-8")


# ===========================================================================
# Data models
# ===========================================================================


@dataclass(frozen=True, slots=True)
class MaskedFunction:
    """A function with its relocation-masked body bytes."""

    name: str
    addr: int
    body: bytes


@dataclass(frozen=True, slots=True)
class ScopeInfo:
    """Binding scope and visibility of a symbol."""

    scope: str  # e.g. "global", "local", "weak"
    hidden: bool

    def format(self) -> str:
        base = f"scope:{self.scope}"
        return f"{base} hidden" if self.hidden else base


@dataclass(frozen=True, slots=True)
class LocatedFunction:
    """Uniquely identifies a function inside a specific object file."""

    obj_path: Path
    func: MaskedFunction

    @property
    def name(self) -> str:
        return self.func.name


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    """Metadata for a single entry in symbols.txt."""

    name: str
    addr: int
    size: int | None = None
    scope: str | None = None
    hidden: bool = False


@dataclass
class EnrichedInfo:
    """Enrichment data attached to a sports function after symbol lookup."""

    abs_addr: int | None = None
    name: str | None = None
    size: int | None = None
    scope: str | None = None
    hidden: bool = False

    def get_name(self, fallback: str) -> str:
        return self.name if self.name is not None else fallback

    def get_size(self, fallback: int) -> int:
        return self.size if self.size is not None else fallback

    def get_scope(self, fallback: ScopeInfo) -> ScopeInfo:
        if self.scope is not None:
            return ScopeInfo(self.scope, self.hidden)
        return fallback


@dataclass
class ObjectReport:
    """Portability report for a single object file."""

    object_path: Path
    total: int
    matched: int
    matched_named: int  # matched functions that are already identified (not auto_)
    matched_auto: int  # matched functions found in anonymous auto chunks

    @property
    def score(self) -> float:
        if self.total == 0:
            return 0.0
        return self.matched / self.total

    @property
    def label(self) -> str:
        if self.score >= 0.99:
            return "FULL"
        if self.score >= 0.75:
            return "MOSTLY"
        return "PARTIAL"


@dataclass
class CrossMatchResult:
    """Aggregated results of a cross-match run."""

    reports: list[ObjectReport]
    matches_by_sports_fn: dict[LocatedFunction, list[LocatedFunction]]
    matched_play_functions: set[LocatedFunction]
    scopes: dict[LocatedFunction, ScopeInfo]
    enriched: dict[LocatedFunction, EnrichedInfo]

    _buckets: dict[str, list[ObjectReport]] = field(default_factory=dict, repr=False)

    BUCKET_LABELS = (
        ("FULL (>=99%)", lambda r: r.score >= 0.99),
        ("MOSTLY (75-99%)", lambda r: 0.75 <= r.score < 0.99),
        ("PARTIAL (25-75%)", lambda r: 0.25 <= r.score < 0.75),
        ("BARELY (1-25%)", lambda r: 0 < r.score < 0.25),
        ("NONE (0%)", lambda r: r.score == 0),
    )

    def __post_init__(self) -> None:
        self._buckets = {
            label: [r for r in self.reports if pred(r)]
            for label, pred in self.BUCKET_LABELS
        }

    @property
    def total_funcs(self) -> int:
        return sum(r.total for r in self.reports)

    @property
    def total_matched(self) -> int:
        return sum(r.matched for r in self.reports)

    @property
    def match_rate(self) -> float:
        if self.total_funcs == 0:
            return 0.0
        return self.total_matched / self.total_funcs


# Type aliases
FunctionsPerObject = dict[Path, list[MaskedFunction]]
"""object-path -> functions contained in that object"""

SplitsLookup = dict[str, dict[str, tuple[int, int]]]
"""source-path -> {section: (start, end)}"""


# ===========================================================================
# configure.py parser (this is surprisingly simpler than importing the file)
# ===========================================================================

# Matches Object(Matching, "path/file.c" ...) across line breaks.
# Also handles MatchingFor(...) and Equivalent.
_RE_OBJECT = re.compile(
    r"Object\(\s*"
    r"(?:Matching|NonMatching|Equivalent|MatchingFor\([^)]*\))"
    r'\s*,\s*"([^"]+)"',
    re.DOTALL,
)

# Matches a library-name key in a lib dict:  "lib": "SomeName",
_RE_LIB = re.compile(r'^\s*"lib"\s*:\s*"([^"]+)"', re.MULTILINE)


def parse_configure_file(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (objects, libs) from a configure.py file.

    objects :
        object-stem -> full source-path as written in configure.py
        e.g. "revolution/OS/OSAlarm" -> "revolution/OS/OSAlarm.c"

    libs :
        source-path -> library name
        e.g. "revolution/OS/OSAlarm.c" -> "RVL_SDK"
    """
    if not path.exists():
        _note_anomaly(f"configure.py not found: {path}")
        return {}, {}

    raw = path.read_text(encoding="utf-8")

    # Strip Python comment-lines so commented-out Object() calls
    # (e.g.  # Object(NonMatching, "foo.c")) are invisible.
    active = "\n".join(
        line for line in raw.splitlines() if not line.strip().startswith("#")
    )

    # Collect lib / Object events ordered by position in the file.
    events: list[tuple[int, str, str]] = []  # (position, kind, value)

    for match in _RE_LIB.finditer(active):
        events.append((match.start(), "lib", match.group(1)))
    for match in _RE_OBJECT.finditer(active):
        events.append((match.start(), "obj", match.group(1)))

    events.sort(key=lambda e: e[0])

    objects: dict[str, str] = {}
    libs: dict[str, str] = {}
    current_lib: str | None = None

    for _pos, kind, value in events:
        if kind == "lib":
            current_lib = value
        elif kind == "obj":
            source_path = value
            stem = str(Path(source_path).with_suffix("")).replace("\\", "/")
            objects[stem] = source_path
            if current_lib is not None:
                libs[source_path] = current_lib
            else:
                _note_anomaly(
                    f"configure.py: Object({source_path!r}) has no preceding "
                    f'"lib" declaration — cannot determine library'
                )

    return objects, libs


# ===========================================================================
# Object / source helpers
# ===========================================================================


def _obj_stem(obj_rel: Path) -> str:
    """Normalised stem of an object path:  foo/bar.o  ->  foo/bar"""
    return str(obj_rel.with_suffix("")).replace("\\", "/")


def is_implemented(obj_rel: Path, config_objs: dict[str, str]) -> bool:
    """True when *obj_rel* appears in *config_objs* as compilable source.

    Entries ending in ".o" (unsplit binary blobs) are never considered
    implemented because they carry no reusable source.
    """
    src = config_objs.get(_obj_stem(obj_rel))
    return src is not None and not src.endswith(".o")


def source_path_for(obj_rel: Path, config_objs: dict[str, str]) -> str | None:
    """Canonical source-path from configure.py, or None."""
    src = config_objs.get(_obj_stem(obj_rel))
    if src is None or src.endswith(".o"):
        return None
    return src


# ===========================================================================
# symbols.txt parser
# ===========================================================================


def parse_symbols_txt(path: Path) -> dict[int, SymbolInfo]:
    """Parse a symbols.txt file into {absolute-address: SymbolInfo}.

    Only *function* entries are kept.  Malformed lines are logged.
    """
    lookup: dict[int, SymbolInfo] = {}
    if not path.exists():
        return lookup

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or " = " not in line:
                continue
            try:
                name_part, rest = line.split(" = ", 1)
                section_addr, comment = rest.split("; // ", 1)
                _section, addr_str = section_addr.split(":")
                addr = int(addr_str, 0)

                attrs: dict[str, object] = {"name": name_part, "addr": addr}
                for token in comment.split():
                    if token.startswith("type:"):
                        attrs["type"] = token[5:]
                    elif token.startswith("size:"):
                        attrs["size"] = int(token[5:], 0)
                    elif token.startswith("scope:"):
                        attrs["scope"] = token[6:]
                    elif token == "hidden":
                        attrs["hidden"] = True

                if attrs.get("type") != "function":
                    continue

                lookup[addr] = SymbolInfo(
                    name=name_part,
                    addr=addr,
                    size=attrs.get("size"),  # type: ignore[arg-type]
                    scope=attrs.get("scope"),  # type: ignore[arg-type]
                    hidden=bool(attrs.get("hidden", False)),
                )
            except Exception as exc:
                _note_anomaly(
                    f"Malformed symbols.txt line in {path.name}: {line!r}  ({exc})"
                )
    return lookup


# ===========================================================================
# splits.txt parser
# ===========================================================================


def parse_splits_txt(path: Path) -> SplitsLookup:
    """Parse a splits.txt file into {source-path: {section: (start, end)}}.

    Malformed lines are logged.
    """
    lookup: SplitsLookup = {}
    if not path.exists():
        return lookup

    current_source: str | None = None
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("Sections:"):
                continue
            if line.endswith(":"):
                current_source = line[:-1]
                lookup[current_source] = {}
                continue
            if current_source is None:
                continue
            try:
                parts = line.split()
                section = parts[0]
                start = int(parts[1].split(":")[1], 0)
                end = int(parts[2].split(":")[1], 0)
                lookup[current_source][section] = (start, end)
            except Exception as exc:
                _note_anomaly(
                    f"Malformed splits.txt line in {path.name}: {line!r}  ({exc})"
                )
    return lookup


# ===========================================================================
# ELF analysis
# ===========================================================================


def extract_masked_functions(
    obj_path: Path,
) -> tuple[list[MaskedFunction], dict[MaskedFunction, ScopeInfo]]:
    """Read a dtk-produced ELF object and return masked function bodies.

    Returns (functions, scopes) where *scopes* maps each function to its
    binding scope and visibility.
    """
    with open(obj_path, "rb") as fh:
        elf = ELFFile(fh)

        text = elf.get_section_by_name(".text")
        if text is None or text["sh_size"] == 0:
            return [], {}

        raw = bytearray(text.data())

        # Zero out the address-dependent bytes indicated by relocations.
        rela = elf.get_section_by_name(".rela.text")
        if rela is not None:
            for reloc in rela.iter_relocations():
                off = reloc["r_offset"]
                r_type = reloc["r_info_type"]
                mask = RELOC_MASKS.get(r_type, DEFAULT_MASK)
                if off + 4 <= len(raw):
                    word = int.from_bytes(raw[off : off + 4], "big") & ~mask
                    raw[off : off + 4] = word.to_bytes(4, "big")

        symtab = elf.get_section_by_name(".symtab")
        if symtab is None:
            return [], {}

        functions: list[MaskedFunction] = []
        scopes: dict[MaskedFunction, ScopeInfo] = {}
        seen: set[tuple[int, int]] = set()

        for sym in symtab.iter_symbols():
            if sym["st_info"]["type"] != _SYM_TYPE_FUNC:
                continue
            addr = sym["st_value"]
            size = sym["st_size"]
            if size == 0 or addr + size > len(raw):
                continue
            key = (addr, size)
            if key in seen:
                continue
            seen.add(key)

            body = bytes(raw[addr : addr + size])
            func = MaskedFunction(sym.name, addr, body)
            functions.append(func)

            bind = sym["st_info"]["bind"]
            vis = sym["st_other"]["visibility"]
            scope = bind.lower().removeprefix("stb_")
            hidden = vis == _SYM_VIS_HIDDEN
            scopes[func] = ScopeInfo(scope, hidden)

        return functions, scopes


def obj_text_size(obj_path: Path) -> int | None:
    """Return the .text section size of an ELF object, or None on failure."""
    with open(obj_path, "rb") as fh:
        elf = ELFFile(fh)
        text = elf.get_section_by_name(".text")
        if text is None:
            _note_anomaly(f"No .text section in {obj_path}")
            return None
        return int(text["sh_size"])


# ===========================================================================
# Function collection
# ===========================================================================


def collect_functions(
    obj_dir: Path,
    config_objs: dict[str, str],
    *,
    only_implemented: bool = False,
) -> tuple[FunctionsPerObject, dict[LocatedFunction, ScopeInfo]]:
    """Walk *obj_dir* for *.o files and extract masked functions.

    When *only_implemented* is True, objects NOT listed in *config_objs*
    with a compilable source are skipped.
    """
    fn_per_obj: FunctionsPerObject = {}
    scopes: dict[LocatedFunction, ScopeInfo] = {}

    for abs_path in sorted(obj_dir.rglob("*.o")):
        rel = abs_path.relative_to(obj_dir)
        if only_implemented and not is_implemented(rel, config_objs):
            continue
        funcs, func_scopes = extract_masked_functions(abs_path)
        if not funcs:
            continue
        fn_per_obj[rel] = funcs
        for func, scope_info in func_scopes.items():
            scopes[LocatedFunction(rel, func)] = scope_info

    return fn_per_obj, scopes


# ===========================================================================
# Matching engine
# ===========================================================================


def _index_by_body(
    fn_per_obj: FunctionsPerObject,
) -> dict[bytes, list[LocatedFunction]]:
    """Return {masked-body: [LocatedFunction, ...]} for fast lookup."""
    index: dict[bytes, list[LocatedFunction]] = defaultdict(list)
    for obj_path, funcs in fn_per_obj.items():
        for func in funcs:
            index[func.body].append(LocatedFunction(obj_path, func))
    return index


def match_sports_play(
    sports_fns: FunctionsPerObject,
    play_fns: FunctionsPerObject,
    play_config: dict[str, str],
    sports_scopes: dict[LocatedFunction, ScopeInfo],
    enriched: dict[LocatedFunction, EnrichedInfo],
) -> CrossMatchResult:
    """Cross-match every sports function against the play function index.

    Sports objects already implemented on the play side (per play's
    configure.py) are skipped entirely.
    """
    play_index = _index_by_body(play_fns)
    matched_play: set[LocatedFunction] = set()
    matches: dict[LocatedFunction, list[LocatedFunction]] = {}
    reports: list[ObjectReport] = []

    for obj_path, funcs in sports_fns.items():
        if is_implemented(obj_path, play_config):
            continue

        n_matched = 0
        n_auto = 0
        for func in funcs:
            loc = LocatedFunction(obj_path, func)
            hits = play_index.get(func.body, [])
            matches[loc] = hits
            matched_play.update(hits)
            if hits:
                n_matched += 1
                if any(hit.func.name.startswith("auto_") for hit in hits):
                    n_auto += 1

        total = len(funcs)
        if total > 0:
            reports.append(
                ObjectReport(obj_path, total, n_matched, n_matched - n_auto, n_auto)
            )

    reports.sort(key=lambda r: (-r.score, -r.total))
    return CrossMatchResult(
        reports=reports,
        matches_by_sports_fn=matches,
        matched_play_functions=matched_play,
        scopes=sports_scopes,
        enriched=enriched,
    )


# ===========================================================================
# Report generation
# ===========================================================================


def _print_header(println: Callable[..., None], title: str, char: str = "=") -> None:
    println()
    println(char * 70)
    println(title)
    println(char * 70)
    println()


def generate_report(
    sports_fn_count: int,
    sports_obj_count: int,
    play_fn_count: int,
    play_obj_count: int,
    sports_fns: FunctionsPerObject,
    result: CrossMatchResult,
    out_path: Path,
) -> None:
    """Write the human-readable cross-match report."""

    with out_path.open("w", encoding="utf-8") as f:
        println = partial(print, file=f)

        # Overview
        _print_header(println, "Wii Sports -> Wii Play Cross-Match results")
        println(f"Wii Sports objects with source:     {sports_obj_count}")
        println(f"Wii Sports functions indexed:       {sports_fn_count}")
        println(f"Wii Play objects indexed:           {play_obj_count}")
        println(f"Wii Play functions indexed:         {play_fn_count}")
        println(
            f"Wii Play functions matched overall: {len(result.matched_play_functions)}"
        )
        println()

        # Buckets
        _print_header(println, "OBJECT-LEVEL PORTABILITY", char="-")
        for label, reports in result._buckets.items():
            println(f"  {label:<24} {len(reports):>4}")
        println(f"  {'Total portable objects:':<24} {len(result.reports):>4}")
        println()

        # Detailed object list (>= 25 %)
        for rep in result.reports:
            if rep.score < 0.25:
                continue
            println(f"[{rep.label}] {rep.object_path}")
            println(
                f"       Functions: {rep.matched}/{rep.total} matched"
                f" ({rep.score * 100:.0f}%)"
            )
            if rep.matched_named:
                println(f"       -> {rep.matched_named} already identified in Wii Play")
            if rep.matched_auto:
                println(f"       -> {rep.matched_auto} found in anonymous auto chunks")
            println()

        # Function-level details (non-FULL, >= 25 %)
        _print_header(println, "FUNCTION-LEVEL DETAILS (non-FULL objects)")
        for rep in result.reports:
            if rep.score >= 0.99 or rep.score < 0.25:
                continue
            println(f"--- {rep.object_path} ({rep.matched}/{rep.total} matched) ---")
            for func in sports_fns[rep.object_path]:
                loc = LocatedFunction(rep.object_path, func)
                hits = result.matches_by_sports_fn.get(loc, [])
                enriched = result.enriched.get(loc, EnrichedInfo())
                name = enriched.get_name(func.name)
                if not hits:
                    println(f"  MISSING: {name}")
                else:
                    locs = [
                        f"{hit.func.name} [{hit.obj_path} @ {hex(hit.func.addr)}]"
                        for hit in hits[:3]
                    ]
                    println(f"  FOUND:   {name}  ->  {', '.join(locs)}")
            println()

        # Summary
        _print_header(println, "SUMMARY STATISTICS")
        println(f"Functions in portable objects:  {result.total_funcs}")
        println(f"Functions matched in Wii Play:  {result.total_matched}")
        println(f"Overall match rate:             {result.match_rate * 100:.1f}%")

    print(f"Report written to {out_path}")


# ===========================================================================
# Auto-chunk / address helpers
# ===========================================================================


def _auto_chunk_base(obj_path: Path) -> int | None:
    """Extract the absolute base address from an auto-chunk filename.

    Recognises patterns like:
        auto_fn_80008490_text.o   -> 0x80008490
        auto_03_8000849C_text.o   -> 0x8000849C
    """
    for part in obj_path.stem.split("_"):
        if (
            len(part) == 8
            and part.startswith("80")
            and all(c in "0123456789abcdefABCDEF" for c in part)
        ):
            return int(part, 16)
    return None


def absolute_address(
    obj_path: Path,
    func: MaskedFunction,
    splits: SplitsLookup | None = None,
) -> int | None:
    """Return the absolute address of *func* in the play binary.

    Auto-chunks carry their base address in the filename.  Named objects
    are resolved through the play project's splits.txt.
    """
    base = _auto_chunk_base(obj_path)
    if base is not None:
        return base + func.addr

    if splits is not None:
        for ext in SOURCE_EXTS:
            key = str(obj_path.with_suffix(ext))
            sec = splits.get(key, {})
            if ".text" in sec:
                return sec[".text"][0] + func.addr
    return None


# ===========================================================================
# Proposal generators
# ===========================================================================


def _build_reverse_index(
    matches: dict[LocatedFunction, list[LocatedFunction]],
) -> dict[LocatedFunction, list[LocatedFunction]]:
    """Invert the match map: play-function -> [sports-functions that match it]."""
    reverse: dict[LocatedFunction, list[LocatedFunction]] = defaultdict(list)
    for sports_loc, play_matches in matches.items():
        for pm in play_matches:
            reverse[pm].append(sports_loc)
    return reverse


def _group_matches_by_sports_obj(
    reverse_index: dict[LocatedFunction, list[LocatedFunction]],
) -> dict[Path, list[tuple[LocatedFunction, list[LocatedFunction]]]]:
    """Group the reverse-indexed matches by the sports object path."""
    by_sports: dict[Path, list[tuple[LocatedFunction, list[LocatedFunction]]]] = (
        defaultdict(list)
    )
    for play_loc, sports_list in reverse_index.items():
        by_sports[sports_list[0].obj_path].append((play_loc, sports_list))
    return by_sports


def _make_symbol_sort_key(
    play_splits: SplitsLookup | None,
) -> Callable[[tuple[LocatedFunction, list[LocatedFunction]]], tuple[int, int]]:
    """Factory for the sort key used in symbols_proposal."""

    def sort_key(
        item: tuple[LocatedFunction, list[LocatedFunction]],
    ) -> tuple[int, int]:
        loc, _ = item
        addr = absolute_address(loc.obj_path, loc.func, play_splits)
        return (0, addr) if addr is not None else (1, 0)

    return sort_key


def _write_symbol_entry(
    println: Callable[..., None],
    play_loc: LocatedFunction,
    abs_addr: int,
    sports_list: list[LocatedFunction],
    result: CrossMatchResult,
) -> None:
    """Emit a single symbols.txt line (plus comments) for a matched play function."""
    play_func = play_loc.func

    # The first sports entry is the "primary" name.
    chosen = sports_list[0]
    chosen_enriched = result.enriched.get(chosen, EnrichedInfo())
    chosen_name = chosen_enriched.get_name(chosen.func.name)

    # Comment out every *other* candidate.
    if len(sports_list) > 1:
        alternatives = [sloc for sloc in sports_list if sloc != chosen]
        for sloc in alternatives[:4]:
            ce = result.enriched.get(sloc, EnrichedInfo())
            cn = ce.get_name(sloc.func.name)
            cs = ce.get_size(len(sloc.func.body))
            cscope = ce.get_scope(result.scopes.get(sloc, ScopeInfo("global", False)))
            println(
                f"# {cn} = .text:{hex(abs_addr)};"
                f" // type:function size:{hex(cs)} {cscope.format()}"
            )

        remaining = len(alternatives) - 4
        if remaining > 0:
            println(
                f"# ... ({remaining} more alternative{'s' if remaining > 1 else ''})"
            )

        if len(play_func.body) > 8:
            println(
                f"# WARNING: multiple sports functions match"
                f" {play_func.name} @ {hex(abs_addr)}"
            )

    if not play_func.name.startswith("fn_"):
        println(f"# Play name: {play_func.name}")

    size = chosen_enriched.get_size(len(play_func.body))
    scope_info = chosen_enriched.get_scope(
        result.scopes.get(chosen, ScopeInfo("global", False))
    )

    println(
        f"{chosen_name} = .text:{hex(abs_addr)};"
        f" // type:function size:{hex(size)} {scope_info.format()}"
    )


def generate_symbols_proposal(
    result: CrossMatchResult,
    out_path: Path,
    play_splits: SplitsLookup | None = None,
) -> None:
    """Generate a symbols.txt proposal for matched play functions."""
    reverse_index = _build_reverse_index(result.matches_by_sports_fn)
    by_sports = _group_matches_by_sports_obj(reverse_index)

    with out_path.open("w", encoding="utf-8") as f:
        println = partial(print, file=f)
        println("# Auto-generated symbols.txt proposal")
        println("# Copy relevant lines into config/RHAE01/symbols.txt")
        println("# WARNING: verify each entry before committing")
        println()

        sort_key = _make_symbol_sort_key(play_splits)
        seen_addrs: set[int] = set()

        for sports_path in sorted(by_sports):
            println(f"# --- from {sports_path} ---")
            entries = by_sports[sports_path]
            entries.sort(key=sort_key)

            for play_loc, sports_list in entries:
                abs_addr = absolute_address(
                    play_loc.obj_path, play_loc.func, play_splits
                )
                if abs_addr is None:
                    println(
                        f"# SKIPPED (no absolute address):"
                        f" {play_loc.func.name} in {play_loc.obj_path}"
                    )
                    continue
                if abs_addr in seen_addrs:
                    continue
                _write_symbol_entry(println, play_loc, abs_addr, sports_list, result)
                seen_addrs.add(abs_addr)
            println()

    print(f"Symbols proposal written to {out_path}")


def generate_splits_proposal(
    sports_fns: FunctionsPerObject,
    sports_obj_dir: Path,
    sports_config_objs: dict[str, str],
    result: CrossMatchResult,
    out_path: Path,
) -> None:
    """Generate a splits.txt proposal for well-matched objects.

    Each play-function address is assigned to the highest-scoring sports
    object, preventing overlapping ranges.
    """
    rows: list[tuple[float, Path, ObjectReport]] = []
    for rep in result.reports:
        if rep.score < 0.75:
            continue
        src = source_path_for(rep.object_path, sports_config_objs)
        if src is None:
            continue
        rows.append((rep.score, rep.object_path, rep))

    rows.sort(key=lambda r: (-r[0], r[1]))

    claimed: set[int] = set()
    entries: list[tuple[int, str, int, ObjectReport, bool]] = []

    for _score, obj_path, rep in rows:
        # Gather absolute addresses of all matched play functions.
        all_addrs: list[int] = []
        for func in sports_fns[obj_path]:
            loc = LocatedFunction(obj_path, func)
            for hit in result.matches_by_sports_fn.get(loc, []):
                addr = absolute_address(hit.obj_path, hit.func)
                if addr is not None:
                    all_addrs.append(addr)

        if not all_addrs:
            continue

        unclaimed = [a for a in all_addrs if a not in claimed]
        use_unclaimed = bool(unclaimed)
        effective = unclaimed if unclaimed else all_addrs

        text_start = min(effective)
        text_size = obj_text_size(sports_obj_dir / obj_path)
        if text_size is None:
            _note_anomaly(
                f"Cannot read .text size for {obj_path} — "
                f"skipping splits proposal entry"
            )
            continue
        text_end = text_start + text_size

        src = source_path_for(obj_path, sports_config_objs)
        if src is None:
            continue

        entries.append((text_start, src, text_end, rep, not use_unclaimed))
        claimed.update(effective)

    entries.sort(key=lambda e: (Path(e[1]).parent.parts, e[0]))

    with out_path.open("w", encoding="utf-8") as f:
        println = partial(print, file=f)
        println("# Auto-generated splits.txt proposal")
        println("# Copy relevant entries into config/RHAE01/splits.txt")
        println(
            "# WARNING: verify start/end addresses and add .rodata/.data/.bss sections"
        )
        println()

        for start, src, end, rep, forced in entries:
            println(f"{src}:")
            println(f"\t.text\tstart:{hex(start)} end:{hex(end)}")
            if forced:
                println(
                    f"\t# WARNING: all matched addresses already claimed"
                    f" — bounds overlap with earlier entries"
                )
            elif rep.score < 0.99:
                println(
                    f"\t# WARNING: only {rep.score * 100:.0f}% matched"
                    f" — bounds may be incomplete"
                )
            println()

    print(f"Splits proposal written to {out_path}")


def generate_configure_proposal(
    sports_config_objs: dict[str, str],
    sports_libs: dict[str, str],
    result: CrossMatchResult,
    out_path: Path,
) -> None:
    """Generate a configure.py proposal snippet.

    Library assignments come directly from the sports project's
    configure.py.  Sources whose library could not be determined are
    logged and skipped.
    """
    libraries: dict[str, list[str]] = defaultdict(list)

    for rep in result.reports:
        if rep.score < 0.25:
            continue
        src = source_path_for(rep.object_path, sports_config_objs)
        if src is None:
            continue
        lib = sports_libs.get(src)
        if lib is None:
            _note_anomaly(
                f"No library mapping for {src!r} — skipping configure proposal entry"
            )
            continue
        libraries[lib].append(src)

    with out_path.open("w", encoding="utf-8") as f:
        println = partial(print, file=f)
        println("# Auto-generated configure.py proposal")
        println("# Copy Object() lines into the matching library dict in configure.py")
        println("# WARNING: verify library assignment, cflags and matching status")
        println()

        for lib_name in sorted(libraries):
            println(f"# Library: {lib_name}")
            for src in sorted(libraries[lib_name]):
                println(f'    Object(NonMatching, "{src}"),')
            println()

    print(f"Configure proposal written to {out_path}")


# ===========================================================================
# Main analysis pipeline
# ===========================================================================


def generate_analysis(
    sports_root: Path,
    play_root: Path,
    out_path: Path,
) -> None:
    """Run the full cross-match pipeline and write all output files."""

    # Directory layout (derived from the two version constants)
    sports_obj_dir = sports_root / "build" / VERSION_SPORTS / "obj"
    play_obj_dir = play_root / "build" / VERSION_PLAY / "obj"

    sports_cfg_dir = sports_root / "config" / VERSION_SPORTS
    play_cfg_dir = play_root / "config" / VERSION_PLAY

    # Parse curated metadata
    symbols_lookup = parse_symbols_txt(sports_cfg_dir / "symbols.txt")
    splits_lookup = parse_splits_txt(sports_cfg_dir / "splits.txt")
    play_splits = parse_splits_txt(play_cfg_dir / "splits.txt")

    # Parse configure.py
    sports_objs, sports_libs = parse_configure_file(sports_root / "configure.py")
    play_objs, _ = parse_configure_file(play_root / "configure.py")

    # Collect & mask functions
    sports_fns, sports_scopes = collect_functions(
        sports_obj_dir,
        sports_objs,
        only_implemented=True,
    )
    play_fns, _ = collect_functions(
        play_obj_dir,
        play_objs,
        only_implemented=False,
    )

    # Enrich sports functions with symbols.txt metadata
    enriched: dict[LocatedFunction, EnrichedInfo] = {}
    for obj_path, funcs in sports_fns.items():
        base = _auto_chunk_base(obj_path)
        if base is None:
            for ext in SOURCE_EXTS:
                key = str(obj_path.with_suffix(ext))
                if key in splits_lookup and ".text" in splits_lookup[key]:
                    base = splits_lookup[key][".text"][0]
                    break

        for func in funcs:
            abs_addr = base + func.addr if base is not None else None
            info = EnrichedInfo(abs_addr=abs_addr)
            if abs_addr is not None and abs_addr in symbols_lookup:
                sym = symbols_lookup[abs_addr]
                info = EnrichedInfo(
                    abs_addr=abs_addr,
                    name=sym.name,
                    size=sym.size,
                    scope=sym.scope,
                    hidden=sym.hidden,
                )
            enriched[LocatedFunction(obj_path, func)] = info

    # Cross-match
    result = match_sports_play(
        sports_fns,
        play_fns,
        play_objs,
        sports_scopes,
        enriched,
    )

    # Write output
    out_path.mkdir(parents=True, exist_ok=True)

    generate_report(
        sports_fn_count=sum(len(v) for v in sports_fns.values()),
        sports_obj_count=len(sports_fns),
        play_fn_count=sum(len(v) for v in play_fns.values()),
        play_obj_count=len(play_fns),
        sports_fns=sports_fns,
        result=result,
        out_path=out_path / "report.txt",
    )
    generate_symbols_proposal(
        result,
        out_path / "symbols_proposal.txt",
        play_splits,
    )
    generate_splits_proposal(
        sports_fns,
        sports_obj_dir,
        sports_objs,
        result,
        out_path / "splits_proposal.txt",
    )
    generate_configure_proposal(
        sports_objs,
        sports_libs,
        result,
        out_path / "configure_proposal.txt",
    )

    _flush_anomalies(out_path / "anomalies.txt")


# ===========================================================================
# Entry point
# ===========================================================================


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python3 {sys.argv[0]} <ogws_project_dir>")
        sys.exit(1)

    sports_root = Path(sys.argv[1]).resolve()
    play_root = Path(__file__).resolve().parent.parent

    # Verify the directories we know the layout of exist.
    missing: list[str] = []
    for label, p in [
        ("sports obj", sports_root / "build" / VERSION_SPORTS / "obj"),
        ("play obj", play_root / "build" / VERSION_PLAY / "obj"),
        ("sports cfg", sports_root / "config" / VERSION_SPORTS),
        ("play cfg", play_root / "config" / VERSION_PLAY),
        ("sports conf", sports_root / "configure.py"),
        ("play conf", play_root / "configure.py"),
    ]:
        if not p.exists():
            missing.append(f"  {label}: {p}")

    if missing:
        raise FileNotFoundError(
            "Required directories/files not found:\n" + "\n".join(missing)
        )

    generate_analysis(sports_root, play_root, play_root / "build" / "cross_match")


if __name__ == "__main__":
    main()
