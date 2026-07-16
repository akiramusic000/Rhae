from symbols import parse_symbols
from pathlib import Path
import argparse

parser = argparse.ArgumentParser(
    description="Translates a group of symbols from one game to another using a different base address."
)
parser.add_argument(
    "address",
    type=str,
    help="Address to translate, in the current game.",
)

args = parser.parse_args()
address = int(args.address, 16)

symbols_path = Path("symbols.txt")
symbols_txt = symbols_path.read_text()
symbols = parse_symbols(symbols_txt)

base_addr = symbols.symbols[0].address
displacement = address - base_addr

for symbol in symbols.symbols:
    symbol.address += displacement
    print(f"{symbol}")
