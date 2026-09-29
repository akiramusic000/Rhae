from pathlib import Path
from symbols import Symbols, parse_symbols
import argparse


def rename(symbols: Symbols, base_addr: int, names: list[str]):
    base_idx = symbols.addresses[base_addr]

    for i in range(len(names)):
        symbols.symbols[base_idx + i].name = names[i].strip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Renames symbols from a list of comma seperated symbols."
    )
    parser.add_argument(
        "symbols_path",
        type=Path,
        help="Path to the symbols.txt for the current game.",
    )
    parser.add_argument(
        "current_path",
        type=Path,
        help="Path to the comma seperated symbols to rename to.",
    )
    parser.add_argument(
        "base_address",
        type=str,
        help="Address of the symbol to start renaming from.",
    )
    args = parser.parse_args()

    symbols_path: Path = args.symbols_path
    current_path: Path = args.current_path
    base_addr: int = int(args.base_address, 16)

    symbols_txt = symbols_path.read_text()
    current_txt = current_path.read_text()

    symbols = parse_symbols(symbols_txt)
    current = current_txt.split(",")

    rename(symbols, base_addr, current)

    base_idx = symbols.addresses[base_addr]

    for i in range(base_idx, base_idx + len(current)):
        print(f"{symbols.symbols[i]}")
