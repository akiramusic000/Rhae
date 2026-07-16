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
    type: str
    size: int
    scope: str
    align: int
    data: str | None

    def __format__(self, _: str) -> str:
        return f"{self.name} = {self.section}:0x{self.address:X}; // type:{self.type}{f" size:0x{self.size:X}" if self.size != 0 else ""} scope:{self.scope}{f" align:{self.align}" if self.align != 1 else ""}{f" data:{self.data}" if self.data != None else ""}"


sym_regex = re.compile(
    r"(?P<name>.+) = (?P<section>\.?[a-zA-Z0-9]+):0x(?P<address>[0-9A-Fa-f]{8}); // type:(?P<type>[a-z]*)( size:0x(?P<size>[0-9A-Za-z]*))?( scope:(?P<scope>[a-z]*))?( align:(?P<align>[0-9]*))?( data:(?P<data>[a-z]*))?"
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

            type = groups["type"]

            if groups["size"] != None:
                size = int(groups["size"], 16)
            else:
                size = 0

            if groups["scope"] != None:
                scope = groups["scope"]
            else:
                scope = "global"

            if groups["align"] != None:
                align = int(groups["align"])
            else:
                align = 1

            data = groups["data"]

            symbol_list.append(
                Symbol(
                    groups["name"],
                    groups["section"],
                    address,
                    type,
                    size,
                    scope,
                    align,
                    data,
                )
            )
            if not address in addresses:
                addresses[address] = i
            i += 1

    return Symbols(symbol_list, addresses)
