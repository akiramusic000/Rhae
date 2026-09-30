import argparse
from pathlib import Path
from symbols import parse_symbols
import os
from rename import rename
import subprocess
import re

EXE = ".exe" if os.name == "nt" else ""

objdiff_cli = f"build/tools/objdiff-cli{EXE}"
anonymous_symbol = re.compile(r"@[0-9]+")


def dedup(objs: list[str]) -> list[str]:
    new = []

    for i in objs:
        if i not in new:
            new.append(i)

    return new


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Renames unnamed symbols to compiler-anonymous symbols."
    )
    parser.add_argument(
        "symbols_path",
        type=Path,
        help="Path to the symbols.txt for the current game.",
    )
    parser.add_argument(
        "unit",
        type=str,
        help="Unit to match anonymous symbols of.",
    )
    parser.add_argument(
        "base_address",
        type=str,
        help="Address of the symbol to start renaming from.",
    )
    args = parser.parse_args()

    symbols_path: Path = args.symbols_path
    unit: str = args.unit
    base_addr: int = int(args.base_address, 16)

    symbols_txt = symbols_path.read_text()
    symbols = parse_symbols(symbols_txt)

    args = [objdiff_cli, "diff", "-u", unit, "-o", "-"]
    result = subprocess.run(args, stdout=subprocess.PIPE)

    matches: list[str] = anonymous_symbol.findall(str(result.stdout))
    matches = dedup(matches)
    matches.sort()

    rename(symbols, base_addr, matches)

    base_idx = symbols.addresses[base_addr]

    for i in range(base_idx, base_idx + len(matches)):
        symbols.symbols[i].scope = "local"
        print(f"{symbols.symbols[i]}")

    print(
        f"\t{symbols.symbols[base_idx].section}     start:{hex(symbols.symbols[base_idx].address)} end:{hex(symbols.symbols[base_idx + len(matches)].address)}"
    )
