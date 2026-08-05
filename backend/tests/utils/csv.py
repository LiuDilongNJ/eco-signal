import csv


def read_csv_rows(text: str) -> list[list[str]]:
    lines = text.strip().splitlines()
    if not lines:
        return []
    lines[0] = lines[0].lstrip("\ufeff")
    return list(csv.reader(lines))


def read_csv_header(text: str) -> list[str]:
    rows = read_csv_rows(text)
    return rows[0] if rows else []


def read_csv_dict_rows(text: str) -> list[dict[str, str]]:
    lines = text.strip().splitlines()
    if not lines:
        return []
    lines[0] = lines[0].lstrip("\ufeff")
    return list(csv.DictReader(lines))
