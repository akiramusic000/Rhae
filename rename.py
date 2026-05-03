from pathlib import Path
import pyperclip


def get_symbol(line: str) -> str:
    return line.split()[0]


ogws_symbols = Path("ogws_symbols.txt").read_text()
symbols = Path("symbols.txt").read_text()

output = ""

for target, original in zip(ogws_symbols.splitlines(), symbols.splitlines()):
    output += original.replace(get_symbol(original), get_symbol(target)) + "\n"

pyperclip.copy(output.strip())
