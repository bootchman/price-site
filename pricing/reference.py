"""Начальные справочники и нормализация названий."""
import re

TERMINALS = [
    # code, name, group, country
    ("SAV", "Savannah, GA", "GA", "US"),
    ("ELZ", "Elizabeth, NJ", "NJ", "US"),
    ("NYC", "New York", "NJ", "US"),
    ("HOU", "Houston, TX", "TX", "US"),
    ("LAX", "Los Angeles, CA", "CA", "US"),
    ("IND", "Indianapolis, IN", "IN", "US"),
    ("CHI", "Chicago, IL", "IL", "US"),
    ("ORF", "Norfolk, VA", "VA", "US"),
    ("MIA", "Miami, FL", "FL", "US"),
    ("SEA", "Seattle, WA", "WA", "US"),
    ("HNL", "Honolulu, HI", "HI", "US"),
    ("ANC", "Anchorage, AK", "AK", "US"),
    ("MTL", "Montreal, QC", "QC", "CA"),
    ("YTO", "Toronto, ON", "ON", "CA"),
]

# Как склады называются в прайсах операторов → код склада
TERMINAL_ALIASES = {
    "savannah, ga": "SAV", "savannah": "SAV", "ga georgia": "SAV", "georgia": "SAV",
    "elizabeth, nj": "ELZ", "nj new jersey": "ELZ", "new jersey": "ELZ",
    "new york": "NYC",
    "houston, tx": "HOU", "houston": "HOU", "tx texas": "HOU", "texas": "HOU",
    "los angeles, ca": "LAX", "los angeles": "LAX", "ca california": "LAX", "california": "LAX",
    "indianapolis, in": "IND", "indianapolis": "IND",
    "chicago": "CHI", "chicago, il": "CHI", "illinoise, il": "CHI", "illinois, il": "CHI",
    "fl florida": "MIA", "florida": "MIA", "wa washington": "SEA",
    "norfolk": "ORF", "miami": "MIA", "seattle": "SEA", "honolulu": "HNL", "anchorage": "ANC",
    "montreal, qc": "MTL", "montreal": "MTL", "toronto": "YTO",
}

DESTINATION_PORTS = [
    ("KLJ", "Клайпеда", "Литва", 1),
    ("GDY", "Гдыня", "Польша", 2),
    ("BRV", "Бремерхафен", "Германия", 3),
    ("POT", "Поти", "Грузия", 4),
    ("BUS", "Батуми", "Грузия", 5),
]
DESTINATION_ALIASES = {"klaipeda": "KLJ", "gdynia": "GDY", "bremerhaven": "BRV", "poti": "POT", "batumi": "BUS"}

VEHICLE_TYPES = [
    ("sedan", "Седан", 1),
    ("suv", "SUV малый/средний", 2),
    ("suv_big", "SUV большой", 3),
    ("pickup", "Пикап", 4),
    ("moto", "Мотоцикл", 5),
    ("atv", "ATV (квадроцикл)", 6),
    ("snowmobile", "Снегоход", 7),
    ("jetski", "Гидроцикл", 8),
    ("mower", "Газонокосилка", 9),
]

AUCTIONS = ["Copart", "IAAI", "Manheim", "Adesa"]

US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY", "Puerto Rico": "PR",
    "Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB", "New Brunswick": "NB",
    "Newfoundland and Labrador": "NL", "Newfoundland and Lab": "NL", "Nova Scotia": "NS", "Ontario": "ON", "Quebec": "QC", "Saskatchewan": "SK",
}

CANADA = {"AB", "BC", "MB", "NB", "NL", "NS", "ON", "QC", "SK", "PE", "YT", "NT", "NU"}


def name_key(name: str, state: str = "") -> str:
    """Нормализованное название площадки: регистр, индекс, «(ST)», пунктуация, дефисы."""
    n = str(name or "").upper()
    n = re.sub(r"\b\d{5}(-\d{4})?\b", " ", n)  # ZIP США
    n = re.sub(r"\b[A-Z]\d[A-Z][ -]?\d[A-Z]\d\b", " ", n)  # индекс Канады
    if state:
        n = re.sub(r"\(\s*" + re.escape(state) + r"\s*\)", " ", n)
        n = re.sub(r",\s*" + re.escape(state) + r"\s*$", " ", n)
    n = re.sub(r"[.,()]", " ", n)
    n = re.sub(r"\s*-\s*", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    if state and n.endswith(" " + state.upper()):  # «TUCSON AZ)», «CONCORD NC ( )»
        n = n[: -len(state) - 1].strip()
    return n


def normalize_state(value: str) -> str:
    """«NV» / «nv» / «Nevada» → «NV»."""
    v = str(value or "").strip()
    if len(v) == 2:
        return v.upper()
    for full, code in US_STATES.items():
        if full.lower() == v.lower():
            return code
    return v.upper()


def terminal_code(raw: str):
    return TERMINAL_ALIASES.get(str(raw or "").strip().lower())
