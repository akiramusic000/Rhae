import re
from dataclasses import dataclass

from typing import cast, get_args, Literal, Self, TypeAlias

SectionType: TypeAlias = Literal[
    ".init",
    "extab",
    "extabindex",
    ".text",
    ".ctors",
    ".dtors",
    ".BINARY",
    ".rodata",
    ".data",
    ".bss",
    ".sdata",
    ".sbss",
    ".sdata2",
    ".sbss2",
]


def check_is_section_type(section: str) -> SectionType:
    if section not in get_args(SectionType):
        raise ValueError(f"Unknown section '{section}'")
    return cast(SectionType, section)


_SPLIT_RE = re.compile(
    r"\s*(?P<section>\S*)\s+start:(?P<start>0x[a-fA-F0-9]+)\s+end:(?P<end>0x[a-fA-F0-9]+)"
)


@dataclass
class Split:
    section: SectionType
    start: int
    end: int

    def __format__(self, _: str, /) -> str:
        return f"\t{self.section:<12} start:0x{self.start:08X} end:0x{self.end:08X}"

    @classmethod
    def parse(cls, split_txt: str) -> Self:
        re_match = _SPLIT_RE.match(split_txt)
        if re_match is None:
            raise ValueError(f"No split detected for '{split_txt}'")
        groups = re_match.groupdict()
        section = check_is_section_type((groups["section"] or "").lower())
        start_str = groups["start"]
        if not start_str:
            raise ValueError(f"Can't find start addr in section '{section}'")
        end_str = groups["end"]
        if not end_str:
            raise ValueError(f"Can't find end addr in section '{section}'")
        return cls(section, int(start_str, 16), int(end_str, 16))


@dataclass
class ObjectSplit:
    file: str
    splits: list[Split]

    def __format__(self, _: str, /) -> str:
        return (
            f"{self.file}:\n" + "\n".join(i.__format__(_) for i in self.splits) + "\n"
        )


def parse_splits(splits_txt: str) -> list[ObjectSplit]:
    all_object_splits: list[ObjectSplit] = []
    # None state is also used for the Sections header
    working_file: str | None = None
    working_splits: list[Split] = []

    def save_object_split():
        if working_file is None:
            return
        all_object_splits.append(ObjectSplit(working_file, working_splits))

    for line in (i.strip() for i in splits_txt.splitlines()):
        if not line:
            pass
        elif line == "Sections:":
            pass
        elif line.endswith(":"):
            save_object_split()
            working_file = line.rstrip(":")
            working_splits = []
        elif working_file is not None:
            split = Split.parse(line)
            working_splits.append(split)
    save_object_split()
    return all_object_splits
