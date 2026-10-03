"""Scientific evidence checks; no domain logic in the generic execution loop."""
from dataclasses import dataclass
import math
import re

from ..agent.completion import CompletionIssue, observations


NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
# A Markdown cell boundary may separate the number and unit on the SAME row.
# Do not flatten tables: unrelated columns or rows must not acquire a unit.
ENERGY = re.compile(r"(?<![A-Za-z0-9_.,])(?P<number>" + NUMBER + r")(?:\s*[xX*\u00d7\u00b7]\s*10\s*(?:\^\s*(?P<power>[+-]?\d+)|(?P<sup_power>[\u207a\u207b]?[\u2070\u00b9\u00b2\u00b3\u2074-\u2079]+)))?(?:[ \t]*\|[ \t]*|\s*)(?P<unit>[kMGT]?J(?![A-Za-z])|(?i:joules?)(?![A-Za-z])|\u7126\u8033)")
SUPERSCRIPT_DIGITS = str.maketrans("\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207a\u207b", "0123456789+-")
SCALE = {"kJ": 3, "MJ": 6, "GJ": 9, "TJ": 12}

# The documented earthquake_energy conversion, not a blanket exemption
# for every occurrence of a familiar numerical value.
TNT_JOULES_PER_TONNE = 4.184e9
TNT_MASS_UNIT = r"(?:kiloton(?:ne)?s?|ton(?:ne)?s?|kilograms?|grams?|kt|kg|g|t|\u5343\u5428|\u5428|\u5343\u514b|\u516c\u65a4|\u514b)"
TNT_MASS = (r"(?<![A-Za-z0-9_.,])(?P<amount>" + NUMBER + r")\s*"
            r"(?P<massunit>" + TNT_MASS_UNIT + r")\s*(?:of\s+)?TNT\b")
EQUIVALENCE = r"\s*(?:=|\u2248|equals|is\s+equivalent\s+to|\u76f8\u5f53\u4e8e|\u7b49\u4e8e)\s*"
TNT_BEFORE = re.compile(TNT_MASS + EQUIVALENCE + r"$", re.I)
TNT_AFTER = re.compile(r"^" + EQUIVALENCE + TNT_MASS, re.I)
TNT_PER_AFTER = re.compile(r"^\s*(?:/\s*|per\s+)(?P<massunit>" + TNT_MASS_UNIT + r")\s*(?:of\s+)?TNT\b", re.I)


@dataclass(frozen=True)
class EnergyClaim:
    text: str
    value: float
    rounding_allowance: float
    start: int = 0
    end: int = 0


def numeric_text(answer):
    text = re.sub(r"\\(?:mathrm|text)\{([^}]*)\}", r"\1", answer)
    text = text.replace("\\times", "x").replace("\\cdot", "*")
    text = re.sub(r"\\[()\[\],!]", "", text)
    return text.translate(str.maketrans("", "", "{}$")).replace("**", "").replace(chr(96), "")


def energy_claims(answer):
    text = numeric_text(answer)
    claims = []
    for match in ENERGY.finditer(text):
        raw = match["number"].replace(",", "")
        mantissa, _, exponent = raw.lower().partition("e")
        explicit_power = match["power"] or (match["sup_power"] or "").translate(SUPERSCRIPT_DIGITS)
        power = int(exponent or 0) + int(explicit_power or 0) + SCALE.get(match["unit"], 0)
        decimals = len(mantissa.partition(".")[2])
        try:
            value = float(mantissa) * 10.0 ** power
            allowance = 0.5 * 10.0 ** (power - decimals)
        except OverflowError:
            value, allowance = math.inf, 0.0
        claims.append(EnergyClaim(match.group(), value, allowance, match.start(), match.end()))
    return claims


def tnt_conversion_expected(text, claim):
    """Recognize an explicit TNT mass/energy equality or energy-per-TNT unit.

    Only that particular energy mention becomes a conversion claim. Adjacent
    earthquake results remain subject to their original observed-value check.
    """
    relation = TNT_BEFORE.search(text[:claim.start]) or TNT_AFTER.match(text[claim.end:])
    per_unit = None if relation else TNT_PER_AFTER.match(text[claim.end:])
    if relation is None and per_unit is None:
        return None
    match = relation or per_unit
    amount = float(relation["amount"].replace(",", "")) if relation else 1.0
    unit = match["massunit"].lower()
    if unit in ("kg", "kilogram", "kilograms", "\u5343\u514b", "\u516c\u65a4"):
        tonnes = amount / 1000
    elif unit in ("g", "gram", "grams", "\u514b"):
        tonnes = amount / 1000000
    elif unit in ("kt", "kiloton", "kilotons", "kilotonne", "kilotonnes", "\u5343\u5428"):
        tonnes = amount * 1000
    else:
        tonnes = amount
    return tonnes * TNT_JOULES_PER_TONNE if tonnes > 0 else math.nan


def validate_energy_answer(state):
    values = [float(r["result"]["data"]["energy_j"]) for r in observations(state["messages"])
              if r["result"]["name"] == "GeoMagnitudeToEnergy" and r["result"]["status"] == "ok"]
    if not values:
        return []
    issues = []
    text = numeric_text(state["answer"])
    for claim in energy_claims(state["answer"]):
        conversion = tnt_conversion_expected(text, claim)
        expected = [conversion] if conversion is not None else values
        if not math.isfinite(claim.value) or not any(math.isfinite(value) and
                abs(claim.value - value) <= claim.rounding_allowance + abs(value) * 1e-12 for value in expected):
            if conversion is not None:
                verified = format(conversion, ".17g") + " joules for the explicitly stated TNT mass"
                label = "Numerical inconsistency in TNT conversion: "
            else:
                verified = "; ".join(format(value, ".17g") + " joules" for value in dict.fromkeys(values))
                label = "Numerical inconsistency: "
            issues.append(CompletionIssue(label + claim.text + ". Verified values: " + verified +
                ". Correct this specific claim while preserving other valid results and unit-conversion explanations. "
                "Equivalent scientific notation and requested rounding are allowed; do not repeat successful calculations."))
    return issues
