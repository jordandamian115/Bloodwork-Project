from agents.lab_parser import parse_lab_text
from security.phi import extract_demographics, redact_phi, to_age_band

RAW = (
    "Patient: John Example\n"
    "Age: 45 years old  Sex: Male  Weight: 190 lb\n"
    "Address: 123 Main Street  SSN 123-45-6789\n"
    "Visit 03/01/2024 09:30 am\n"
    "LDL 162  HDL 38  Total testosterone 280  Creatinine 1.1  eGFR 72\n"
)


def test_demographics_and_age_bands() -> None:
    demo = extract_demographics(RAW)
    assert demo.sex == "male"
    assert demo.age_years == 45
    assert to_age_band(45) == "40-49"
    assert to_age_band(92) == "90+"


def test_redact_phi_strips_identifiers() -> None:
    redacted, tags = redact_phi(RAW)
    assert "123-45-6789" not in redacted
    assert "John Example" not in redacted
    assert "ID" in tags or "NAME" in tags


def test_parse_simple_panel() -> None:
    panel = parse_lab_text(RAW)
    assert panel.findings.get("ldl") == 162
    assert panel.findings.get("total_testosterone") == 280
    public = panel.public_dict()
    assert public["range_context"]["age_band"] == "40-49"
    assert "190" not in panel.as_prompt_block()


def test_parse_cystatin_and_hematocrit() -> None:
    cys = parse_lab_text("Cystatin-C, Serum\nH  1.24  mg/L\nHematocrit  41.2 %")
    assert cys.findings.get("cystatin_c") == 1.24
    assert cys.findings.get("hematocrit") == 41.2


def test_quest_testosterone_fractions_and_scope() -> None:
    quest = parse_lab_text(
        "TESTOSTERONE, FREE, BIOAVAILABLE AND TOTAL, MS\n"
        "TESTOSTERONE, FREE 747.4 H 46.0-224.0 pg/mL\n"
        "TESTOSTERONE,BIOAVAILABLE 1504.6 H 110.0-575.0 ng/dL\n"
        "TESTOSTERONE, TOTAL, MS 1796 H 250-1100 ng/dL\n"
        "LDL 162\n"
        "Hematocrit 41.2\n"
    )
    assert quest.findings.get("free_testosterone") == 747.4
    assert quest.findings.get("bioavailable_testosterone") == 1504.6
    assert quest.findings.get("total_testosterone") == 1796
    focused = quest.as_prompt_block("What does my testosterone look like?")
    assert "1796" in focused
    assert "747.4" in focused
    assert "162" not in focused
    assert "41.2" not in focused
    assert "Only markers named" in focused
    wide = quest.as_prompt_block("Summarize my full panel")
    assert "Full panel" in wide
