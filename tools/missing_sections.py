from pathlib import Path

import argparse

from splits import parse_splits, ObjectSplit, Split, SplitSection

parser = argparse.ArgumentParser(
    description="Crosses missing section splits from decomp project to another by looking for identical names "
    + "and identical memory gap sizes."
)
parser.add_argument(
    "ref_splits_path", type=Path, help="Path to the splits.txt for the reference game."
)
parser.add_argument(
    "current_splits_path",
    type=Path,
    help="Path to the splits.txt for the current game.",
)
parser.add_argument(
    "file_name",
    type=str,
    help="Name of the file to start crossing from.",
)


def _get_section_addresses(object_splits: ObjectSplit) -> dict[SplitSection, int]:
    return {s.section: s.end for s in object_splits.splits}


def delta_splits(
    ref_splits: list[ObjectSplit],
    current_splits: list[ObjectSplit],
    file_name: str,
) -> list[ObjectSplit]:

    for idx, s in enumerate(ref_splits):
        if s.file == file_name:
            ref_base_idx = idx
            break
    else:
        raise ValueError(f"'{file_name}' not found in reference 'splits.txt'")

    last_section_addresses: dict[SplitSection, int] = {}
    for idx, s in enumerate(current_splits):
        if s.file == file_name:
            current_base_idx = idx
            break
        last_section_addresses.update(_get_section_addresses(s))
    else:
        raise ValueError(f"'{file_name}' not found in current 'splits.txt'")

    # Dicts preserve insertion order
    output: dict[str, ObjectSplit] = {}
    for section in last_section_addresses.keys():
        missing_splits: list[tuple[ObjectSplit, int]] = []
        last_address = last_section_addresses[section]
        for r_section, c_section in zip(
            ref_splits[ref_base_idx:],
            current_splits[current_base_idx:],
        ):
            if r_section.file != c_section.file:
                break
            c_split = ([s for s in c_section.splits if s.section == section] or [None])[
                0
            ]
            output[c_section.file] = c_section
            if c_split is not None:
                address_difference = c_split.start - last_address
                if address_difference != sum(size for _, size in missing_splits):
                    break
                for o_split, size in missing_splits:
                    if size > 0:
                        o_split.splits.append(
                            Split(section, last_address, last_address + size)
                        )
                    last_address += size
                missing_splits.clear()
                last_address = c_split.end

            else:
                split = (
                    [s for s in r_section.splits if s.section == section] or [None]
                )[0]
                size = split.end - split.start if split is not None else 0
                missing_splits.append((c_section, size))

    return list(output.values())


if __name__ == "__main__":
    args = parser.parse_args()
    ref_splits_path: Path = args.ref_splits_path
    current_splits_path: Path = args.current_splits_path
    file_name: str = args.file_name

    ref_splits_txt = ref_splits_path.read_text()
    current_splits_txt = current_splits_path.read_text()

    ref_splits = parse_splits(ref_splits_txt)
    current_splits = parse_splits(current_splits_txt)

    for object_splits in delta_splits(ref_splits, current_splits, file_name):
        print(f"{object_splits}\n")
