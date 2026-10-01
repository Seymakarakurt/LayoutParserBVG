import argparse
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

OUTPUT_DIR = BASE_DIR / "data" / "output" / "extracted"


# ALLGEMEIN


def normalize_text(text):

    if not text:
        return ""

    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = text.replace("−", "-")

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def get_attempts(item):

    attempts = item.get(
        "all_ocr_attempts",
        [],
    )

    if attempts:
        return attempts

    return [
        {
            "text": item.get(
                "ocr_text",
                "",
            ),
            "confidence": item.get(
                "ocr_confidence",
                0,
            ),
            "psm": None,
        }
    ]


# PLAN-NUMMER
#
# Erster Schritt nach dem Kollegen-Vorschlag:
# Label erkennen, vollständige IDs bevorzugen,
# kurze Teilstrings verwerfen, Label-Nähe statt
# pauschalem Zeichnungs-Bonus.

PLAN_REJECT_WORDS = [
    "schnitt",
    "ansicht",
    "draufsicht",
    "punkt",
]

PLAN_BLOCKED_VALUES = {
    "none",
    "null",
    "n/a",
    "na",
    "notreadable",
    "not readable",
    "unreadable",
    "unleserlich",
    "keine",
}

PLAN_LABEL_PATTERN = re.compile(
    r"(?:"
    r"zeichnungs?\s*[- ]?\s*(?:nummer|nr\.?|n[rr]\.?)"
    r"|zeichnungsnummer"
    r"|zg\s*[-.]?\s*n[rr]\.?"
    r"|zg\.?\s*n[rr]\.?"
    r"|plan\s*[- ]?\s*(?:nummer|nr\.?|n[rr]\.?)"
    r"|plan[- ]?nr\.?"
    r")\s*[:.]?\s*",
    flags=re.IGNORECASE,
)

# OCR verwechselt Stempelbuchstaben oft mit Ziffern.
LETTER_DIGIT_OCR = {
    "B": "8",
    "S": "5",
    "G": "6",
    "O": "0",
    "D": "0",
    "I": "1",
    "Z": "2",
}


def is_letter_plan_id(value):

    return bool(
        re.fullmatch(
            r"[A-Z]\d{3,5}-\d{2,4}",
            value or "",
        )
    )


def prefer_letter_over_digit_ocr(results):

    letter_candidates = [
        candidate
        for candidate in results
        if (
            is_letter_plan_id(candidate["value"])
            and candidate["detector_label"] == "PLAN_NUMBER_FIELD"
            and candidate["support"] >= 2
        )
    ]

    for letter_candidate in letter_candidates:

        letter = letter_candidate["value"][0]

        rest = letter_candidate["value"][1:]

        digit = LETTER_DIGIT_OCR.get(letter)

        if not digit:
            continue

        alt_value = digit + rest

        for other in results:

            if other["value"] != alt_value:
                continue

            letter_candidate["score"] = max(
                letter_candidate["score"],
                other["score"] + 0.25,
            )


def plan_compact_key(value):

    return re.sub(
        r"[^A-Za-z0-9Σσ]+",
        "",
        value or "",
    ).upper()


def is_blocked_plan_value(value):

    folded = re.sub(
        r"\s+",
        " ",
        (value or "").strip().lower(),
    )

    if folded in PLAN_BLOCKED_VALUES:
        return True

    compact = plan_compact_key(value).lower()

    return compact in {
        "none",
        "null",
        "na",
        "notreadable",
        "unreadable",
        "unleserlich",
        "keine",
    }


def looks_like_scale_or_date(value):

    text = value or ""

    if re.fullmatch(r"1\s*:\s*\d{1,4}", text):
        return True

    if re.fullmatch(
        r"\d{1,2}[./]\d{1,2}[./]\d{2,4}",
        text,
    ):
        return True

    return False


def normalize_plan_identifier(raw):

    text = normalize_text(raw)

    if not text:
        return ""

    text = re.sub(
        r"\s*([-_./])\s*",
        r"\1",
        text,
    )

    # Historisch E_328_A -> E 328 A, Wp_Zo behalten.
    text = re.sub(
        r"(?<=[A-Za-zΣ])_(?=\d)",
        " ",
        text,
    )

    text = re.sub(
        r"(?<=\d)_(?=[A-Za-zΣ])",
        " ",
        text,
    )

    text = text.strip(" ,;:|")

    return text.upper()


def mask_plan_labels(text):

    labels = list(PLAN_LABEL_PATTERN.finditer(text or ""))

    if not labels:
        return text, []

    chars = list(text)

    for match in labels:

        for index in range(match.start(), match.end()):

            chars[index] = " "

    return "".join(chars), labels


def identifier_follows_label(
    labels,
    start,
    text,
):

    for label in labels:

        if start < label.end():
            continue

        gap = text[label.end() : start]

        if not gap.strip() or re.fullmatch(
            r"[\s:.-]*",
            gap,
        ):
            return True, label.group(0).strip()

    return False, None


def suppress_plan_substrings(candidates):

    if not candidates:
        return []

    ranked = sorted(
        candidates,
        key=lambda item: (
            len(plan_compact_key(item["value"])),
            item["end"] - item["start"],
            item.get("label_context", False),
        ),
        reverse=True,
    )

    kept = []

    kept_keys = []

    seen_values = set()

    for candidate in ranked:

        value = candidate["value"]

        if value in seen_values:
            continue

        key = plan_compact_key(value)

        if not key:
            continue

        if any(
            key != other and key in other
            for other in kept_keys
        ):
            continue

        kept.append(candidate)

        kept_keys.append(key)

        seen_values.add(value)

    kept.sort(
        key=lambda item: (
            item["start"],
            item["end"],
            item["value"],
        )
    )

    return kept


def normalize_plan_prefix_glyph(marker):

    # £ und { sind typische OCR-Lesungen für Σ auf den Plänen.
    if marker in {"Σ", "£", "{"}:
        return "Σ"

    return marker.upper()


def is_plan_category_token(token):

    if not token:
        return False

    upper = token.upper()

    if upper in PLAN_REJECT_WORDS:
        return False

    # Häufige Fließtext-Wörter, keine ID-Bausteine.
    if upper in {
        "DER",
        "DIE",
        "DAS",
        "UND",
        "MIT",
        "VON",
        "DEN",
        "DEM",
        "DES",
        "BEI",
        "AUS",
        "ZUR",
        "ZUM",
        "NR",
        "BZW",
        "BZ",
        "CA",
        "MM",
        "CM",
    }:
        return False

    return bool(
        re.fullmatch(
            r"[A-ZÄÖÜ]{2,4}",
            upper,
        )
    )


def collect_plan_pattern_matches(
    text,
    detector_label,
):

    matches = []

    # Allgemeines Compound:
    # Präfix + Zahl + Kategorie (+ optionale Zahl)
    # Trenner: Punkt, Bindestrich, Unterstrich, Leerzeichen
    # Beispiele: Σ 504. Ein. 01 | £504. Ein. | S507-SK 20892
    for match in re.finditer(
        r"(?<![A-Za-z0-9])"
        r"([A-ZΣ£{])"
        r"[\s.\-_]*"
        r"(\d{2,4})"
        r"[\s.\-_]+"
        r"([A-Za-zÄÖÜäöü]{2,4})"
        r"(?:[\s.\-_]+(\d{1,4}))?"
        r"(?![A-Za-z0-9])",
        text,
        flags=re.IGNORECASE,
    ):

        category = match.group(3).upper()

        if not is_plan_category_token(category):
            continue

        prefix = normalize_plan_prefix_glyph(match.group(1))

        number = match.group(2)

        suffix = match.group(4)

        if suffix:

            value = f"{prefix}{number}-{category}-{suffix}"

        else:

            value = f"{prefix}{number}-{category}"

        matches.append(
            (
                match.start(),
                match.end(),
                normalize_plan_identifier(value),
                match.group(0),
            )
        )

    # Historisch: E 328 a  (nur ein Buchstaben-Suffix)
    for match in re.finditer(
        r"(?<![A-Za-z0-9Σ])"
        r"([A-ZΣ])"
        r"[\s_\-.]+"
        r"(\d{2,4})"
        r"[\s_\-.]+"
        r"([A-Za-z])"
        r"(?![A-Za-z0-9])",
        text,
    ):

        value = (
            f"{match.group(1)} "
            f"{match.group(2)} "
            f"{match.group(3).upper()}"
        )

        matches.append(
            (
                match.start(),
                match.end(),
                normalize_plan_identifier(value),
                match.group(0),
            )
        )

    # Historischer OCR-Sonderfall nur im Plannummer-Kasten.
    # Nur wenn danach kein Kategorie-Wort (2+ Buchstaben) folgt.
    if detector_label == "PLAN_NUMBER_FIELD":

        for match in re.finditer(
            r"(?<![A-Za-z0-9])"
            r"[£{]"
            r"\s*"
            r"(\d{2,4})"
            r"\s*[_\-. ]+"
            r"([A-Za-z])"
            r"(?![A-Za-z0-9])",
            text,
        ):

            after = text[match.start(2) :]

            if re.match(
                r"[A-Za-z]{2,}",
                after,
            ):
                continue

            value = (
                f"E "
                f"{match.group(1)} "
                f"{match.group(2).upper()}"
            )

            matches.append(
                (
                    match.start(),
                    match.end(),
                    normalize_plan_identifier(value),
                    match.group(0),
                )
            )

    # 263 6/47 -> 2636/47
    for match in re.finditer(
        r"(?<!\d)(\d{2,4})\s+(\d)\s*/\s*(\d{2,4})(?!\d)",
        text,
    ):

        value = (
            match.group(1)
            + match.group(2)
            + "/"
            + match.group(3)
        )

        matches.append(
            (
                match.start(),
                match.end(),
                normalize_plan_identifier(value),
                match.group(0),
            )
        )

    compact = re.sub(
        r"(?<=\d)\s+(?=\d)",
        "",
        text,
    )

    compact = re.sub(
        r"\s*([/-])\s*",
        r"\1",
        compact,
    )

    patterns = [
        # Stempel / Prefix-Nummer
        r"[A-Z]\d{3,5}-\d{2,4}",
        r"[A-Z]\d{2,4}-\d{2,4}[A-Z]?",
        r"[A-ZΣ]\d{2,4}-[A-Z]\b",
        # Mehrere Zahlengruppen
        r"\d{3,6}(?:-\d{2,6}){1,3}",
        r"\d{3,6}/\d{2,4}",
        # DE 016
        r"\bDE\s+\d{3,4}\b",
        # Compound: Präfix-Zahl-Kategorie(-Zahl) mit Trennern
        r"[A-ZΣ]\d{2,4}[-_. ][A-Z]{2,4}(?:[-_. ]\d{1,4})?",
        r"[A-Z]{2,3}[-_][A-Z]{2,3}[-_]\d{2,4}",
        r"[A-Z]/[A-Z](?:-\d{2,4})+",
        r"[A-Z](?:-\d{2,4}){2,}",
        r"[A-Z]{1,3}[-_][A-Z]{1,3}[-_][A-Z]{2,3}[-_]\d{2,4}",
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            compact,
            flags=re.IGNORECASE,
        ):

            value = normalize_plan_identifier(
                match.group(0)
            )

            # Position näherungsweise im Originaltext.
            matches.append(
                (
                    match.start(),
                    match.end(),
                    value,
                    match.group(0),
                )
            )

    return matches


def parse_plan_identifier_candidates(
    text,
    detector_label="",
):

    text = normalize_text(text)

    if not text:
        return []

    masked_text, labels = mask_plan_labels(text)

    spans = []

    for start, end, value, raw in collect_plan_pattern_matches(
        masked_text,
        detector_label,
    ):

        if not value:
            continue

        if is_blocked_plan_value(value):
            continue

        if looks_like_scale_or_date(value):
            continue

        if not any(char.isdigit() for char in value):
            continue

        label_context, label_text = identifier_follows_label(
            labels,
            start,
            text,
        )

        spans.append(
            {
                "value": value,
                "raw_text": normalize_text(raw),
                "start": start,
                "end": end,
                "label_context": label_context,
                "label": label_text,
            }
        )

    return suppress_plan_substrings(spans)


def clean_plan_field_reading(text):

    # Nur bereinigen, nicht in Muster zerlegen.
    text = normalize_text(text)

    if not text:
        return ""

    text = PLAN_LABEL_PATTERN.sub("", text, count=1).strip()

    text = text.replace("£", "Σ").replace("{", "Σ")

    text = text.strip(" \"'`´|()[]«»“”‘’.,;:")

    # Kaputte Label-Reste vor der Zahl: TER.1925...
    # Nicht den Stempelbuchstaben von A318-005 entfernen.
    text = re.sub(
        r"^[A-Za-zÄÖÜ]{1,4}-?NR\.?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"^[A-Za-zÄÖÜ]{2,4}\.?\s*(?=\d)",
        "",
        text,
    )

    text = re.sub(
        r"\s*([.\-_?/])\s*",
        r"\1",
        text,
    )

    # Σ 504 / A 318 zusammenziehen, Wörter wie Ein behalten.
    text = re.sub(
        r"(?<=[A-Za-zΣσ])\s+(?=\d)",
        "",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text


def is_usable_plan_field_reading(text):

    if not text:
        return False

    if is_blocked_plan_value(text):
        return False

    if looks_like_scale_or_date(text):
        return False

    digits = sum(char.isdigit() for char in text)

    if digits < 2:
        return False

    # Echte Plannummern haben mindestens eine dreistellige Gruppe.
    if not re.search(r"\d{3,}", text):
        return False

    if "|" in text:
        return False

    lower = text.lower()

    if re.match(
        r"^(schnitt|ansicht|draufsicht|punkt)\b",
        lower,
    ):
        return False

    if re.search(r"\b1\s*:\s*\d{2,4}\b", text):
        return False

    words = text.split()

    if len(words) > 6:
        return False

    # Fließtext mit Zufallsziffer verwerfen.
    if any(
        len(re.sub(r"[^A-Za-zÄÖÜäöüß]", "", word)) >= 8
        for word in words
    ):
        return False

    allowed = 0

    for char in text:

        if (
            char.isalnum()
            or char.isspace()
            or char in "Σσ.-_/"
        ):
            allowed += 1

    if allowed / max(len(text), 1) < 0.75:
        return False

    compact = plan_compact_key(text)

    if len(compact) < 4:
        return False

    if digits / len(compact) < 0.25:
        return False

    return True


def prefer_complete_plan_readings(results):

    # Bei gleicher Ziffernfolge: häufigere OCR-Lesung
    # behalten. Danach kürzere Bruchstücke verwerfen.
    best_by_digits = {}

    for candidate in results:

        key = plan_compact_key(candidate["value"])

        digits = re.sub(r"\D+", "", key)

        if not digits:
            continue

        previous = best_by_digits.get(digits)

        if previous is None:

            best_by_digits[digits] = candidate

            continue

        previous_key = plan_compact_key(previous["value"])

        if (
            candidate["support"],
            len(key),
            candidate.get("score", 0),
        ) > (
            previous["support"],
            len(previous_key),
            previous.get("score", 0),
        ):

            best_by_digits[digits] = candidate

    ranked = sorted(
        best_by_digits.values(),
        key=lambda item: len(
            re.sub(
                r"\D+",
                "",
                plan_compact_key(item["value"]),
            )
        ),
        reverse=True,
    )

    kept = []

    kept_digits = []

    for candidate in ranked:

        digits = re.sub(
            r"\D+",
            "",
            plan_compact_key(candidate["value"]),
        )

        if any(
            digits != other and digits in other
            for other in kept_digits
        ):
            continue

        kept.append(candidate)

        kept_digits.append(digits)

    return kept


def extract_plan_numbers(
    text,
    detector_label="",
):

    cleaned = clean_plan_field_reading(text)

    if is_usable_plan_field_reading(cleaned):

        return [cleaned]

    return []


def find_plan_numbers(items):

    # Einfache DIA-Logik:
    # 1. Layoutelement PLAN_NUMBER_FIELD
    # 2. OCR-Lesungen dieses Kastens
    # 3. Beste zusammenhängende Lesung behalten

    results = []

    for item in items:

        if item.get("label") != "PLAN_NUMBER_FIELD":
            continue

        layout_score = float(
            item.get(
                "layout_score",
                0,
            )
        )

        candidates = {}

        for attempt in get_attempts(item):

            raw = normalize_text(
                attempt.get(
                    "text",
                    "",
                )
            )

            confidence = float(
                attempt.get(
                    "confidence",
                    0,
                )
            )

            cleaned = clean_plan_field_reading(raw)

            if not is_usable_plan_field_reading(cleaned):
                continue

            key = cleaned.upper()

            if key not in candidates:

                candidates[key] = {
                    "value": cleaned,
                    "support": 0,
                    "max_confidence": 0.0,
                    "drawing_context": False,
                    "label_context": bool(
                        PLAN_LABEL_PATTERN.search(raw)
                    ),
                    "source_text": "",
                    "raw_text": raw,
                    "reject_context": False,
                }

            candidate = candidates[key]

            candidate["support"] += 1

            if confidence > candidate["max_confidence"]:

                candidate["max_confidence"] = confidence

                candidate["source_text"] = raw

                candidate["raw_text"] = raw

                candidate["value"] = cleaned

            if PLAN_LABEL_PATTERN.search(raw):

                candidate["label_context"] = True

        for candidate in candidates.values():

            compact = plan_compact_key(candidate["value"])

            score = 0.0

            score += layout_score

            score += candidate["max_confidence"] / 100

            score += (
                min(
                    candidate["support"],
                    15,
                )
                * 0.20
            )

            # Längere zusammenhängende ID bevorzugen.
            score += min(len(compact), 24) * 0.20

            # Lesungen mit Buchstaben/Σ sind echte IDs,
            # reine Ziffernfragmente oft OCR-Müll.
            if any(
                char.isalpha() or char == "Σ"
                for char in candidate["value"]
            ):

                score += 1.5

            if candidate["label_context"]:

                score += 1.0

            results.append(
                {
                    **candidate,
                    "score": score,
                    "detector_label": "PLAN_NUMBER_FIELD",
                }
            )

    prefer_letter_over_digit_ocr(results)

    results = prefer_complete_plan_readings(results)

    results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return results


# LINE


def looks_like_line_keyword(word):

    normalized = re.sub(
        r"[^A-Za-zÄÖÜäöüß]",
        "",
        word,
    ).lower()

    if len(normalized) < 4:
        return False

    if "linie" in normalized:
        return True

    if "iniel" in normalized:
        return True

    if "injel" in normalized:
        return True

    similarity = SequenceMatcher(
        None,
        normalized,
        "linie",
    ).ratio()

    return similarity >= 0.50


def clean_line_code(token):

    token = re.sub(
        r"[^A-Za-z0-9]",
        "",
        token,
    ).upper()

    if not token:
        return None

    if re.fullmatch(
        r"\d{1,3}",
        token,
    ):
        return token

    if re.fullmatch(
        r"[A-Z]",
        token,
    ):
        return token

    if re.fullmatch(
        r"[A-Z]\d{1,3}",
        token,
    ):
        return token

    return None


def extract_line_value(text):

    text = normalize_text(text)

    if not text:
        return None

    tokens = re.findall(
        r"[A-Za-zÄÖÜäöüß]+\d*|\d+",
        text,
    )

    for index, token in enumerate(tokens):

        if not looks_like_line_keyword(token):
            continue

        next_index = index + 1

        if next_index >= len(tokens):
            continue

        code = clean_line_code(tokens[next_index])

        if not code:
            continue

        if re.fullmatch(
            r"[A-Z]",
            code,
        ) and next_index + 1 < len(tokens):

            following = clean_line_code(tokens[next_index + 1])

            if following and following.isdigit():

                return code + following

        return code

    return None


def get_line_attempt_weight(
    attempt,
):

    psm = attempt.get("psm")

    weights = {
        6: 4.0,
        7: 2.0,
        11: 1.0,
        10: 0.25,
        13: 0.25,
    }

    return weights.get(
        psm,
        1.0,
    )


def find_line(items):

    global_candidates = {}

    for item in items:

        detector_label = item.get(
            "label",
            "",
        )

        layout_score = float(
            item.get(
                "layout_score",
                0,
            )
        )

        for attempt in get_attempts(item):

            text = normalize_text(
                attempt.get(
                    "text",
                    "",
                )
            )

            confidence = float(
                attempt.get(
                    "confidence",
                    0,
                )
            )

            value = extract_line_value(text)

            if not value:
                continue

            if value not in global_candidates:

                global_candidates[value] = {
                    "value": value,
                    "support": 0,
                    "weighted_support": 0.0,
                    "max_confidence": 0.0,
                    "best_layout_score": 0.0,
                    "line_detector_hits": 0,
                    "source_text": "",
                }

            candidate = global_candidates[value]

            candidate["support"] += 1

            attempt_weight = get_line_attempt_weight(attempt)

            confidence_factor = (
                0.5
                + max(
                    confidence,
                    0,
                )
                / 100
            )

            candidate["weighted_support"] += attempt_weight * confidence_factor

            if detector_label == "LINE_FIELD":

                candidate["line_detector_hits"] += 1

            candidate["best_layout_score"] = max(
                candidate["best_layout_score"],
                layout_score,
            )

            if confidence > candidate["max_confidence"]:

                candidate["max_confidence"] = confidence

                candidate["source_text"] = text

    complete_prefixes = set()

    for value in global_candidates:

        match = re.fullmatch(
            r"([A-Z])\d+",
            value,
        )

        if match:

            complete_prefixes.add(match.group(1))

    results = []

    for value, candidate in global_candidates.items():

        score = candidate["weighted_support"]

        score += candidate["max_confidence"] / 100

        score += candidate["best_layout_score"]

        if candidate["line_detector_hits"] > 0:

            score += 1.0

        if len(value) == 1 and value in complete_prefixes:

            score *= 0.05

        candidate["score"] = score

        results.append(candidate)

    results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return results


# STATION

STATION_REJECT_WORDS = [
    "schnitt",
    "ansicht",
    "draufsicht",
    "punkt",
    "bestandsplan",
]

STATION_LIST_PATH = BASE_DIR / "data" / "bvg_station_names.json"

_STATION_NAMES = None


def fold_station_text(text):

    text = normalize_text(text).lower()

    if not text:
        return ""

    text = text.replace("ß", "ss")
    text = text.replace("ä", "ae")
    text = text.replace("ö", "oe")
    text = text.replace("ü", "ue")
    text = text.replace("str.", "strasse")

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    text = re.sub(
        r"\bstrabe\b",
        "strasse",
        text,
    )

    text = re.sub(
        r"\bstr\b",
        "strasse",
        text,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def station_lookup_keys(text):

    folded = fold_station_text(text)

    if not folded:
        return []

    variants = [folded]

    parts = folded.split()

    if parts[0] in {"u", "s"} and len(parts) > 1:

        variants.append(" ".join(parts[1:]))

    if len(parts) > 2 and parts[0] == "s" and parts[1] == "u":

        variants.append(" ".join(parts[2:]))

    keys = []

    for variant in variants:

        key = variant.replace(" ", "")

        if len(key) >= 4 and key not in keys:

            keys.append(key)

    return keys


def station_display_name(station):

    for alias in station.get("aliases", []):

        if "straße" in alias.lower():

            return alias

    return station.get("name", "")


def load_station_names():

    global _STATION_NAMES

    if _STATION_NAMES is not None:

        return _STATION_NAMES

    lookup = {}

    if STATION_LIST_PATH.exists():

        with open(
            STATION_LIST_PATH,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        for station in data.get("stations", []):

            display = station_display_name(station)

            names = [station.get("name", "")]

            names.extend(station.get("aliases", []))

            for name in names:

                for key in station_lookup_keys(name):

                    lookup.setdefault(key, display)

    _STATION_NAMES = lookup

    return lookup


def readable_station_name(text):

    text = normalize_text(text)

    if not text:
        return None

    lower = text.lower()

    if any(word in lower for word in STATION_REJECT_WORDS):

        return None

    if "linie" in lower or "tinie" in lower:

        return None

    blocked = (
        "auftrag",
        "teilvorhaben",
        "grundriss",
        "grundriß",
        "lageplan",
        "zeichnung",
        "übersicht",
        "uebersicht",
    )

    if any(word in lower for word in blocked):

        return None

    # "U-Bhf." oder "Rekonstruktion" ist ein Plantitel,
    # kein Stationsname. Ein echter Name nach Bhf
    # wird weiter oben über das Schlüsselwort gelesen.
    if (
        "bhf" in lower
        or "bahnhof" in lower
        or "rekonstruktion" in lower
    ):

        return None

    letters = re.findall(
        r"[A-Za-zÄÖÜäöüß]",
        text,
    )

    if len(letters) < 6:

        return None

    if len(letters) / len(text) < 0.7:

        return None

    words = re.findall(
        r"[A-Za-zÄÖÜäöüß]{2,}",
        text,
    )

    if not words or len(words) > 6:

        return None

    return text.strip(" ,;:-.|")


def match_known_station(text):

    lookup = load_station_names()

    for key in station_lookup_keys(text):

        if key in lookup:

            return lookup[key]

    return None


def format_bhf_prefix(raw):

    compact = re.sub(
        r"[\s.\-]+",
        "",
        raw,
    ).lower()

    if "s+u" in compact:

        head = "S+U-"

    elif compact.startswith("u"):

        head = "U-"

    elif compact.startswith("s"):

        head = "S-"

    else:

        head = ""

    if "bahnhof" in compact:

        word = "Bahnhof"

    elif "bhf" in compact:

        word = "Bhf."

    else:

        word = "Bf."

    if not head:

        return word

    if word == "Bf.":

        return "Bf."

    return head + word


def name_after_prefix(rest):

    rest = rest.lstrip(" ,;:.-„“\"»«'`´")

    stop = re.search(
        r"\b(?:nebenr|ausgang|rekonstruktion|geschoss|schnitt|ansicht|lageplan|zeichnung)\w*",
        rest,
        flags=re.IGNORECASE,
    )

    if stop:

        rest = rest[: stop.start()]

    words = re.findall(
        r"[A-Za-zÄÖÜäöüß0-9\-]+",
        rest,
    )[:4]

    if not words:

        return None

    for count in range(len(words), 0, -1):

        chunk = " ".join(words[:count])

        known = match_known_station(chunk)

        if not known:

            known = match_known_station(chunk.replace(" ", ""))

        if known:

            return known

    return None


def station_as_written(text):

    text = normalize_text(text)

    if not text:

        return None

    match = re.search(
        r"\b((?:S\s*\+\s*U|U|S)\s*[- ]?\s*)?(Bahnhof|Bhf|Bf)\.?",
        text,
        flags=re.IGNORECASE,
    )

    if not match:

        return None

    prefix_raw = f"{match.group(1) or ''}{match.group(2)}"

    name = name_after_prefix(text[match.end() :])

    if not name:

        return None

    return f"{format_bhf_prefix(prefix_raw)} {name}"


def quoted_station_name(text):

    if not text:

        return None

    if not any(
        mark in text
        for mark in ("„", "“", '"', "»", "«")
    ):

        return None

    return match_known_station(text)


SUGGESTION_MIN_RATIO = 0.73

SUGGESTION_MIN_GAP = 0.05

_STATION_CATALOG = None


def station_catalog():

    global _STATION_CATALOG

    if _STATION_CATALOG is not None:

        return _STATION_CATALOG

    best = {}

    for key, display in load_station_names().items():

        current = best.get(display)

        if current is None or len(key) > len(current):

            best[display] = key

    _STATION_CATALOG = [
        (display, key)
        for display, key in best.items()
        if len(key) >= 8
    ]

    return _STATION_CATALOG


def suggestion_tokens(text):

    folded = fold_station_text(text)

    parts = folded.split()

    if parts and parts[0] in {
        "haltestelle",
        "bahnhof",
        "bhf",
        "bf",
        "station",
    }:

        parts = parts[1:]

    tokens = []

    for part in parts:

        if part.isdigit():

            continue

        if part == "strasse" and tokens:

            tokens[-1] += "strasse"

        else:

            tokens.append(part)

    return [
        token
        for token in tokens
        if len(token) >= 8
    ]


def suggest_from_text(text):

    if not text:

        return None

    lower = text.lower()

    if any(word in lower for word in STATION_REJECT_WORDS):

        return None

    if match_known_station(text):

        return None

    tokens = suggestion_tokens(text)

    exact_names = []

    best = None

    for token in tokens:

        scored = []

        for display, key in station_catalog():

            longer = max(len(token), len(key))

            if abs(len(token) - len(key)) / longer > 0.25:

                continue

            ratio = SequenceMatcher(
                None,
                token,
                key,
            ).ratio()

            scored.append((ratio, display))

        scored.sort(
            reverse=True,
        )

        if not scored:

            continue

        best_ratio, best_name = scored[0]

        second_ratio = scored[1][0] if len(scored) > 1 else 0.0

        if best_ratio >= 0.999:

            exact_names.append(best_name)

        if best_ratio < SUGGESTION_MIN_RATIO:

            continue

        if best_ratio - second_ratio < SUGGESTION_MIN_GAP:

            continue

        if best is None or best_ratio > best["similarity"]:

            best = {
                "name": best_name,
                "read_text": normalize_text(text),
                "similarity": round(best_ratio, 3),
            }

    if len(set(exact_names)) > 1:

        return None

    return best


def suggest_station_name(items, station_name):

    best = None

    for item in items:

        if item.get("label") != "STATION_FIELD":

            continue

        suggestion = suggest_from_text(
            item.get("ocr_text", ""),
        )

        if suggestion is None:

            continue

        if (
            best is None
            or suggestion["similarity"] > best["similarity"]
        ):

            best = suggestion

    if best is None:

        return None

    if station_name and match_known_station(station_name) == best["name"]:

        return None

    if station_name:

        known_keys = set(load_station_names())

        station_tokens = suggestion_tokens(station_name)

        for token in station_tokens:

            if token in known_keys:

                return None

        suggestion_key = ""

        for display, key in station_catalog():

            if display == best["name"]:

                suggestion_key = key

                break

        for read_token in suggestion_tokens(best["read_text"]):

            if read_token in station_tokens:

                continue

            ratio_to_name = SequenceMatcher(
                None,
                read_token,
                suggestion_key,
            ).ratio()

            if any(
                SequenceMatcher(
                    None,
                    read_token,
                    token,
                ).ratio()
                >= ratio_to_name
                for token in station_tokens
            ):

                return None

    return best


def clean_station_text(text):

    text = normalize_text(text)

    if not text:
        return None

    lower = text.lower()

    if any(word in lower for word in STATION_REJECT_WORDS):

        return None

    # U-Bhf. / S-Bhf. / Bahnhof plus Name, wie auf dem Plan.
    # Ein kurzer Stationskasten darf den Namen nicht abschneiden.

    written = station_as_written(text)

    if written:

        return written

    # Bahnhof / Bhf / Bf, wenn der Name nicht in der Liste steht

    bhf_match = re.search(
        r"\b(?:Bahnhof|Bhf|Bf)\.?\s+" r"[A-Za-zÄÖÜäöüß0-9\- ]+",
        text,
        flags=re.IGNORECASE,
    )

    if bhf_match:

        station = bhf_match.group(0)

        station = re.split(
            r"[\(\[\{|]",
            station,
            maxsplit=1,
        )[0]

        station = re.sub(
            r"\s*-\s*",
            "-",
            station,
        )

        station = re.sub(
            r"\s+",
            " ",
            station,
        )

        station = station.strip(" ,;:-.")

        return station

    # Linienbeschreibung ist keine Station

    if "linie" in lower or "tinie" in lower:

        return None

    # Haltestelle / Station

    generic_station_match = re.search(
        r"\b(?:Haltestelle|Station)\s+" r"[A-Za-zÄÖÜäöüß0-9\- ]+",
        text,
        flags=re.IGNORECASE,
    )

    if generic_station_match:

        station = generic_station_match.group(0)

        station = re.split(
            r"[\(\[\{|]",
            station,
            maxsplit=1,
        )[0]

        station = re.sub(
            r"\s+",
            " ",
            station,
        )

        return station.strip(" ,;:-.")

    # Bahnüberführung

    text = re.sub(
        r"u[- ]?bahn[uü]berf[uü]hrung",
        "U-Bahnüberführung",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"bahn[uü]berf[uü]hrung",
        "Bahnüberführung",
        text,
        flags=re.IGNORECASE,
    )

    lower = text.lower()

    start_terms = [
        "u-bahnüberführung",
        "bahnüberführung",
    ]

    start = None

    for term in start_terms:

        position = lower.find(term)

        if position >= 0:

            if start is None or position < start:

                start = position

    if start is None:
        return None

    text = text[start:].strip()

    street_match = re.search(
        r"[A-Za-zÄÖÜäöüß\-]+?" r"(?:straße|strasse)",
        text,
        flags=re.IGNORECASE,
    )

    if street_match:

        text = text[: street_match.end()]

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    text = text.strip(" |,;:-.")

    if len(text) < 4:
        return None

    return text


def find_station(items):

    global_candidates = defaultdict(
        lambda: {
            "value": "",
            "support": 0,
            "max_confidence": 0.0,
            "best_layout_score": 0.0,
            "station_detector_hits": 0,
        }
    )

    for item in items:

        detector_label = item.get(
            "label",
            "",
        )

        layout_score = float(
            item.get(
                "layout_score",
                0,
            )
        )

        for attempt in get_attempts(item):

            text = attempt.get(
                "text",
                "",
            )

            confidence = float(
                attempt.get(
                    "confidence",
                    0,
                )
            )

            value = clean_station_text(text)

            if (
                not value
                and detector_label == "STATION_FIELD"
                and not any(
                    word in text.lower()
                    for word in STATION_REJECT_WORDS
                )
            ):

                value = match_known_station(text)

            if not value:

                value = quoted_station_name(text)

            if not value:
                continue

            key = value.lower().replace(".", "")

            candidate = global_candidates[key]

            candidate["value"] = value

            candidate["support"] += 1

            candidate["max_confidence"] = max(
                candidate["max_confidence"],
                confidence,
            )

            candidate["best_layout_score"] = max(
                candidate["best_layout_score"],
                layout_score,
            )

            if detector_label == "STATION_FIELD":

                candidate["station_detector_hits"] += 1

        if detector_label == "STATION_FIELD":

            raw = item.get(
                "ocr_text",
                "",
            )

            if (
                not clean_station_text(raw)
                and not match_known_station(raw)
            ):

                value = readable_station_name(raw)

                if value:

                    key = value.lower().replace(".", "")

                    candidate = global_candidates[key]

                    candidate["value"] = value

                    candidate["support"] += 1

                    candidate["max_confidence"] = max(
                        candidate["max_confidence"],
                        float(
                            item.get(
                                "ocr_confidence",
                                0,
                            )
                            or 0
                        ),
                    )

                    candidate["best_layout_score"] = max(
                        candidate["best_layout_score"],
                        layout_score,
                    )

                    candidate["station_detector_hits"] += 1

    # "Spittelmarkt" allein fällt weg, wenn dieselbe
    # Zeile schon "U-Bhf. Spittelmarkt" gelesen hat.
    full_names = {}

    for candidate in global_candidates.values():

        match = re.match(
            r"^(?:S\+U-Bahnhof|S\+U-Bhf\.|U-Bahnhof|U-Bhf\.|S-Bahnhof|S-Bhf\.|Bahnhof|Bhf\.|Bf\.)\s+(.+)$",
            candidate["value"],
        )

        if match and candidate["support"] >= 3:

            full_names[match.group(1).lower()] = candidate

    if full_names:

        for key in list(global_candidates.keys()):

            bare = global_candidates[key]["value"].lower()

            if bare in full_names:

                del global_candidates[key]

    results = []

    for candidate in global_candidates.values():

        score = (
            min(
                candidate["support"],
                15,
            )
            * 0.30
        )

        score += candidate["max_confidence"] / 100

        score += candidate["best_layout_score"]

        if candidate["station_detector_hits"] > 0:

            score += 1.0

        candidate["score"] = score

        results.append(candidate)

    results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return results


# MAIN


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "ocr_json",
        type=str,
        help=("OCR JSON auf Originalauflösung"),
    )

    args = parser.parse_args()

    input_path = Path(args.ocr_json)

    if not input_path.exists():

        raise FileNotFoundError(input_path)

    with open(
        input_path,
        "r",
        encoding="utf-8",
    ) as file:

        items = json.load(file)

    print("Informationsextraktion")

    print("=========================")

    print(f"\nOCR-Kandidaten: " f"{len(items)}")

    plan_candidates = find_plan_numbers(items)

    line_candidates = find_line(items)

    station_candidates = find_station(items)

    plan_number = plan_candidates[0]["value"] if plan_candidates else None

    line = line_candidates[0]["value"] if line_candidates else None

    station_name = station_candidates[0]["value"] if station_candidates else None

    station_suggestion = suggest_station_name(
        items,
        station_name,
    )

    result = {
        "station_name": station_name,
        "station_suggestion": station_suggestion,
        "line": line,
        "plan_number": plan_number,
        "debug": {
            "plan_number_candidates": plan_candidates[:10],
            "line_candidates": line_candidates[:10],
            "station_candidates": station_candidates[:10],
        },
    }

    print("\nEXTRAHIERTE INFORMATIONEN")

    print("-------------------------")

    print(f"Station:     " f"{station_name}")

    print(f"Vorschlag:   " f"{station_suggestion}")

    print(f"Linie:       " f"{line}")

    print(f"Plannummer:  " f"{plan_number}")

    print("\nTop Line Kandidaten:")

    if not line_candidates:

        print("  Keine sichere Linie.")

    for candidate in line_candidates[:5]:

        print(
            f"  {candidate['value']}"
            f" | Support "
            f"{candidate['support']}"
            f" | Weighted "
            f"{candidate['weighted_support']:.2f}"
            f" | Score "
            f"{candidate['score']:.3f}"
            f" | OCR "
            f"{repr(candidate['source_text'])}"
        )

    print("\nTop Plan-Number Kandidaten:")

    if not plan_candidates:

        print("  Keine Plannummer erkannt.")

    for candidate in plan_candidates[:5]:

        print(
            f"  {candidate['value']}"
            f" | Support "
            f"{candidate['support']}"
            f" | Zeichnung "
            f"{candidate['drawing_context']}"
            f" | Score "
            f"{candidate['score']:.3f}"
            f" | OCR "
            f"{repr(candidate['source_text'])}"
        )

    print("\nTop Station Kandidaten:")

    if not station_candidates:

        print("  Keine Station erkannt.")

    for candidate in station_candidates[:5]:

        print(
            f"  {candidate['value']}"
            f" | Support "
            f"{candidate['support']}"
            f" | Score "
            f"{candidate['score']:.3f}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = OUTPUT_DIR / (input_path.stem + "_extracted.json")

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            result,
            file,
            indent=4,
            ensure_ascii=False,
        )

    print("\nJSON gespeichert:")

    print(output_path)


if __name__ == "__main__":
    main()
