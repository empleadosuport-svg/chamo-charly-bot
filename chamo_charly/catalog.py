"""Official Lotto Activo code and animal catalog."""

import unicodedata

ANIMALS = {
    "00": "Ballena",
    "0": "Delfín",
    "01": "Carnero",
    "02": "Toro",
    "03": "Ciempiés",
    "04": "Alacrán",
    "05": "León",
    "06": "Rana",
    "07": "Perico",
    "08": "Ratón",
    "09": "Águila",
    "10": "Tigre",
    "11": "Gato",
    "12": "Caballo",
    "13": "Mono",
    "14": "Paloma",
    "15": "Zorro",
    "16": "Oso",
    "17": "Pavo",
    "18": "Burro",
    "19": "Chivo",
    "20": "Cochino",
    "21": "Gallo",
    "22": "Camello",
    "23": "Cebra",
    "24": "Iguana",
    "25": "Gallina",
    "26": "Vaca",
    "27": "Perro",
    "28": "Zamuro",
    "29": "Elefante",
    "30": "Caimán",
    "31": "Lapa",
    "32": "Ardilla",
    "33": "Pescado",
    "34": "Venado",
    "35": "Jirafa",
    "36": "Culebra",
}


def normalize_code(value: object) -> str:
    """Normalize a code while preserving the distinct values 00 and 0."""
    text = str(value).strip()
    if text == "00":
        return text
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit():
        number = int(text)
        text = f"{number:02d}" if 1 <= number <= 9 else str(number)
    return text


def normalize_animal(value: object) -> str:
    text = str(value).strip()
    normalized = unicodedata.normalize("NFD", text)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return normalized.lower().replace(" ", "").replace("-", "")


def animal_for_code(code: object) -> str | None:
    return ANIMALS.get(normalize_code(code))


def code_for_animal(animal: object) -> str | None:
    target = normalize_animal(animal)
    for code, candidate in ANIMALS.items():
        if normalize_animal(candidate) == target:
            return code
    return None


def validate_result(code: object, animal: str) -> str | None:
    normalized_code = normalize_code(code)
    expected_animal = animal_for_code(normalized_code)
    if expected_animal is None:
        return "El código debe ser uno de los 38 valores oficiales."
    if normalize_animal(expected_animal) != normalize_animal(animal):
        return f"El código {normalized_code} corresponde a {expected_animal}."
    return None
