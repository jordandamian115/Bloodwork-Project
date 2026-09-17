"""Educational literature bands for UI gauges. Not a patient's lab interval."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class MarkerSpec:
    key: str
    label: str
    unit: str
    low: float
    high: float
    plausible: tuple[float, float]
    group: str
    aliases: tuple[str, ...] = ()


# Adult teaching bands from NHLBI / MedlinePlus / NCBI appendix (method-dependent).
SPECS: dict[str, MarkerSpec] = {
    "wbc": MarkerSpec("wbc", "WBC", "x10^3/µL", 4.5, 10.0, (1.0, 30.0), "CBC", ("white blood",)),
    "hemoglobin": MarkerSpec("hemoglobin", "Hemoglobin", "g/dL", 12.0, 17.0, (5.0, 22.0), "CBC", ("hgb", "hb")),
    "hematocrit": MarkerSpec("hematocrit", "Hematocrit", "%", 36.0, 50.0, (15.0, 70.0), "CBC", ("hct",)),
    "platelets": MarkerSpec("platelets", "Platelets", "x10^3/µL", 140.0, 450.0, (20.0, 900.0), "CBC", ("plt",)),
    "glucose": MarkerSpec("glucose", "Glucose", "mg/dL", 70.0, 100.0, (40.0, 400.0), "Chemistry", ()),
    "bun": MarkerSpec("bun", "BUN", "mg/dL", 6.0, 20.0, (2.0, 80.0), "Kidney", ()),
    "creatinine": MarkerSpec("creatinine", "Creatinine", "mg/dL", 0.6, 1.3, (0.2, 8.0), "Kidney", ("creat",)),
    "egfr": MarkerSpec("egfr", "eGFR", "mL/min/1.73m²", 60.0, 120.0, (5.0, 150.0), "Kidney", ()),
    "cystatin_c": MarkerSpec(
        "cystatin_c",
        "Cystatin C",
        "mg/L",
        0.5,
        1.0,
        (0.2, 4.0),
        "Kidney",
        ("cysc", "cys-c", "cystatin-c", "cystatin c"),
    ),
    "sodium": MarkerSpec("sodium", "Sodium", "mmol/L", 135.0, 145.0, (110.0, 170.0), "Chemistry", ("na",)),
    "potassium": MarkerSpec("potassium", "Potassium", "mmol/L", 3.5, 5.0, (2.0, 7.5), "Chemistry", ("k",)),
    "alt": MarkerSpec("alt", "ALT", "U/L", 4.0, 36.0, (1.0, 500.0), "Liver", ()),
    "ast": MarkerSpec("ast", "AST", "U/L", 8.0, 33.0, (1.0, 500.0), "Liver", ()),
    "ldl": MarkerSpec("ldl", "LDL-C", "mg/dL", 0.0, 100.0, (20.0, 400.0), "Lipids", ()),
    "hdl": MarkerSpec("hdl", "HDL-C", "mg/dL", 40.0, 80.0, (10.0, 120.0), "Lipids", ()),
    "triglycerides": MarkerSpec("triglycerides", "Triglycerides", "mg/dL", 0.0, 150.0, (20.0, 1000.0), "Lipids", ()),
    "apob": MarkerSpec("apob", "ApoB", "mg/dL", 0.0, 90.0, (20.0, 250.0), "Lipids", ()),
    "lpa": MarkerSpec("lpa", "Lp(a)", "nmol/L", 0.0, 75.0, (1.0, 400.0), "Lipids", ()),
    "total_testosterone": MarkerSpec(
        "total_testosterone", "Total testosterone", "ng/dL", 264.0, 1000.0, (20.0, 4000.0), "Hormones", ("testosterone",)
    ),
    "free_testosterone": MarkerSpec(
        "free_testosterone", "Free testosterone", "pg/mL", 46.0, 224.0, (0.5, 2500.0), "Hormones", ()
    ),
    "bioavailable_testosterone": MarkerSpec(
        "bioavailable_testosterone",
        "Bioavailable testosterone",
        "ng/dL",
        110.0,
        575.0,
        (10.0, 4000.0),
        "Hormones",
        (),
    ),
    "shbg": MarkerSpec("shbg", "SHBG", "nmol/L", 10.0, 57.0, (2.0, 180.0), "Hormones", ()),
    "estradiol": MarkerSpec("estradiol", "Estradiol", "pg/mL", 10.0, 40.0, (1.0, 400.0), "Hormones", ()),
    "lh": MarkerSpec("lh", "LH", "IU/L", 1.2, 8.6, (0.1, 80.0), "Hormones", ()),
    "fsh": MarkerSpec("fsh", "FSH", "IU/L", 1.4, 15.4, (0.1, 80.0), "Hormones", ()),
    "cortisol": MarkerSpec("cortisol", "Cortisol", "µg/dL", 5.0, 25.0, (0.5, 60.0), "Hormones", ()),
    "tsh": MarkerSpec("tsh", "TSH", "mIU/L", 0.5, 5.0, (0.01, 20.0), "Thyroid", ()),
    "ferritin": MarkerSpec("ferritin", "Ferritin", "ng/mL", 30.0, 300.0, (5.0, 1000.0), "Iron", ()),
    "vitamin_d": MarkerSpec("vitamin_d", "Vitamin D", "ng/mL", 20.0, 50.0, (5.0, 150.0), "Micronutrients", ()),
    "hs_crp": MarkerSpec("hs_crp", "hs-CRP", "mg/L", 0.0, 3.0, (0.05, 20.0), "Inflammation", ("crp",)),
    "magnesium": MarkerSpec("magnesium", "Magnesium", "mg/dL", 1.7, 2.2, (0.8, 4.0), "Micronutrients", ()),
    "homocysteine": MarkerSpec("homocysteine", "Homocysteine", "µmol/L", 4.0, 12.0, (2.0, 50.0), "Micronutrients", ()),
}


def sex_adjusted(spec: MarkerSpec, sex: str | None) -> MarkerSpec:
    if spec.key == "hematocrit" and sex == "male":
        return replace(spec, low=41.0, high=50.0)
    if spec.key == "hematocrit" and sex == "female":
        return replace(spec, low=36.0, high=44.0)
    if spec.key == "hemoglobin" and sex == "male":
        return replace(spec, low=14.0, high=17.0)
    if spec.key == "hemoglobin" and sex == "female":
        return replace(spec, low=12.0, high=15.0)
    return spec


def band_status(value: float, spec: MarkerSpec) -> str:
    if value < spec.low:
        return "below literature band"
    if value > spec.high:
        return "above literature band"
    return "in literature band"


FULL_PANEL_PATTERN = re.compile(
    r"\b(all markers|full panel|entire panel|whole panel|everything|summarize my labs|"
    r"all my labs|overview of my labs|complete panel)\b",
    re.I,
)

# First matching group wins for focus; testosterone does not pull CBC/lipids/etc.
FOCUS_GROUPS: list[tuple[str, tuple[str, ...] | None]] = [
    (r"testosterone|free t\b|bioavailable", ("total_testosterone", "free_testosterone", "bioavailable_testosterone")),
    (r"estradiol|\be2\b|aromatase|anastrozole", ("estradiol", "total_testosterone", "shbg")),
    (r"\bshbg\b", ("shbg", "total_testosterone", "free_testosterone")),
    (r"lh\b|fsh\b", ("lh", "fsh", "total_testosterone")),
    (r"cystatin|egfr|creatinine|kidney", ("cystatin_c", "egfr", "creatinine", "bun")),
    (r"hematocrit|\bhct\b", ("hematocrit",)),
    (r"hemoglobin|\bhgb\b|\bhb\b", ("hemoglobin",)),
    (r"\bwbc\b|white blood", ("wbc",)),
    (r"platelet", ("platelets",)),
    (r"\bldl\b|\bhdl\b|\bapo\b|lp\(\s*a\s*\)|\blipid|\bstatins?\b|triglyceride", ("ldl", "hdl", "triglycerides", "apob", "lpa")),
    (r"glucose|a1c|prediabetes|metformin|berberine", ("glucose",)),
    (r"homocysteine|folate|b12|b6", ("homocysteine",)),
    (r"ferritin|\biron\b", ("ferritin",)),
    (r"vitamin d|25-oh", ("vitamin_d",)),
    (r"\btsh\b|thyroid", ("tsh",)),
    (r"magnesium", ("magnesium",)),
    (r"alt\b|ast\b|liver", ("alt", "ast")),
    (r"hs-?crp|\bcrp\b", ("hs_crp",)),
]


def select_marker_keys(question: str, available: dict[str, float]) -> list[str] | None:
    """Return keys to include, or None to include the full panel."""
    if FULL_PANEL_PATTERN.search(question or ""):
        return None
    selected: list[str] = []
    for pattern, keys in FOCUS_GROUPS:
        if re.search(pattern, question or "", re.I) and keys:
            for key in keys:
                if key in available and key not in selected:
                    selected.append(key)
    return selected


QUERY_HINTS = (
    (
        r"cystatin",
        "cystatin C CysC eGFR creatinine kidney filtration dual measurement muscle mass",
    ),
    (r"hematocrit|\bhct\b", "hematocrit HCT CBC red blood cells hemoglobin"),
    (r"egfr|creatinine|kidney", "eGFR creatinine cystatin C kidney"),
    (r"testosterone|\bfree t\b", "total testosterone free testosterone bioavailable testosterone"),
    (r"\bldl\b|\bhdl\b|\bapo\b|lp\(\s*a\s*\)|\blipid|\bstatins?\b", "LDL HDL triglycerides ApoB Lp(a) hs-CRP statin ACC AHA risk-enhancing"),
    (r"glucose|a1c|prediabetes|metformin|berberine", "metformin berberine prediabetes type 2 diabetes diet Mediterranean DASH"),
    (r"homocysteine|folate|b12|b6", "homocysteine folate vitamin B12 B6 supplementation"),
    (
        r"estradiol|aromatase|anastrozole|trt|anabolic|exogenous testosterone",
        "estradiol aromatase inhibitor anastrozole TRT hypogonadism T:E ratio weight loss SHBG",
    ),
)


def expand_retrieval_query(question: str, lab_context: str) -> str:
    extra: list[str] = []
    lower = question.lower()
    for pattern, hint in QUERY_HINTS:
        if re.search(pattern, lower):
            extra.append(hint)
    if "cystatin" in lower and "cystatin" not in lab_context.lower():
        extra.append("Marker may be listed as CysC or Cystatin-C on lab reports.")
    if not extra:
        return question
    return question + "\n\nRetrieval hints: " + " ".join(extra)
