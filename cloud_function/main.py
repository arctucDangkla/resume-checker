"""
Cloud Function: resume_parser
=============================
Triggered automatically when a PDF is uploaded to the GCS bucket
(resume-checker-1775416523-resume-uploads).

Pipeline:
  1. Download the PDF bytes from Cloud Storage
  2. Extract raw text using PyMuPDF (fitz)
  3. Send text to the Google Natural Language API to identify entities
  4. Scan the text for tech skills, degree level, experience years,
     certifications, and extra-curricular activities
  5. Write all structured results to Firestore

Cloud services used here:
  - Cloud Storage        : source of the PDF trigger and file download
  - Cloud Functions      : this function itself (2nd gen, event-driven)
  - Natural Language API : entity extraction on resume text
  - Firestore            : destination for structured resume data
"""

import re
from datetime import datetime

import functions_framework
import fitz  # PyMuPDF — fast PDF text extraction
from google.cloud import firestore, language_v1, storage


# ---------------------------------------------------------------------------
# Technical skills regex
# Covers software development, networking, security, cloud, infrastructure,
# and data/ML so the scorer works across many job families — not just dev roles.
# Word-boundary anchors (\b) prevent partial matches (e.g. "Rustacean" != "rust").
# ---------------------------------------------------------------------------
SKILL_KEYWORDS = re.compile(
    # ---- Software development ----
    r"\b(python|java|sql|javascript|typescript|react|node\.?js|go|rust|c\+\+|"
    r"fastapi|flask|django|spring|rails|\.net|php|swift|kotlin|scala|perl|"
    r"html|css|angular|vue\.?js|next\.?js|graphql|rest|soap|grpc|"
    # ---- Data & ML ----
    r"machine learning|deep learning|nlp|natural language processing|"
    r"computer vision|llm|openai|langchain|tensorflow|pytorch|scikit.?learn|"
    r"pandas|numpy|spark|kafka|airflow|dbt|snowflake|databricks|"
    r"data engineering|mlops|data science|"
    # ---- Databases ----
    r"postgresql|mysql|mongodb|redis|cassandra|elasticsearch|dynamodb|"
    r"oracle|sql server|sqlite|firebase|"
    # ---- DevOps & cloud ----
    r"docker|kubernetes|terraform|ansible|puppet|chef|jenkins|ci/cd|"
    r"git|linux|bash|devops|helm|prometheus|grafana|"
    r"aws|gcp|azure|cloud|vmware|virtualization|"
    # ---- Networking protocols & concepts ----
    r"tcp/ip|tcp|udp|bgp|ospf|eigrp|rip|mpls|vpn|vlan|vxlan|"
    r"wan|lan|sd-wan|sdn|nfv|dns|dhcp|nat|qos|"
    r"ipv4|ipv6|http|https|ssh|ftp|smtp|snmp|netflow|syslog|"
    # ---- Network hardware & vendors ----
    r"cisco|juniper|aruba|fortinet|palo alto|checkpoint|f5|"
    r"router|switch|firewall|load balancer|access point|"
    # ---- Network tools ----
    r"wireshark|nmap|netflow|solarwinds|nagios|zabbix|prtg|"
    r"network monitoring|packet analysis|"
    # ---- Security ----
    r"cissp|ceh|penetration testing|pen testing|vulnerability assessment|"
    r"siem|ids|ips|soc|zero trust|oauth|saml|ldap|active directory|"
    r"encryption|ssl|tls|pki|iam|"
    # ---- Systems & IT ----
    r"windows server|active directory|exchange|sharepoint|"
    r"powershell|hyper-v|esxi|vcenter|"
    r"helpdesk|itil|servicenow|jira|confluence)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Education — degree level patterns.
# We detect the *highest* degree so a resume with both BS and MS scores MS.
# DEGREE_ORDER maps each level to a numeric rank for comparison.
# ---------------------------------------------------------------------------
DEGREE_PATTERNS = {
    "phd":        re.compile(r"\b(ph\.?\s*d\.?|doctorate|doctoral|d\.sc\.?)\b", re.I),
    "masters":    re.compile(r"\b(master'?s?|m\.?\s*s\.?|m\.?\s*a\.?|m\.?\s*eng\.?|m\.?\s*b\.?\s*a\.?|mba)\b", re.I),
    "bachelors":  re.compile(r"\b(bachelor'?s?|b\.?\s*s\.?|b\.?\s*a\.?|b\.?\s*eng\.?|b\.?\s*sc\.?)\b", re.I),
    "associates": re.compile(r"\b(associate'?s?|a\.?\s*s\.?|a\.?\s*a\.?)\b", re.I),
}
DEGREE_ORDER = ["associates", "bachelors", "masters", "phd"]  # ascending rank

# Fields of study — used to note whether the degree is in a relevant area
FIELD_PATTERN = re.compile(
    r"\b(computer science|software engineering|information technology|"
    r"electrical engineering|data science|mathematics|statistics|"
    r"information systems|computer engineering|cybersecurity|"
    r"artificial intelligence|machine learning|physics|applied math)\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Experience — year ranges in the resume (e.g. "2019 – 2022", "2021-Present")
# We sum the durations to estimate total years of professional experience.
# ---------------------------------------------------------------------------
YEAR_RANGE_PATTERN = re.compile(
    r"\b((?:19|20)\d{2})\s*[-–—to]+\s*((?:19|20)\d{2}|present|current|now)\b",
    re.I,
)
CURRENT_YEAR = datetime.now().year

# ---------------------------------------------------------------------------
# Certifications — well-known professional and cloud certifications
# ---------------------------------------------------------------------------
CERT_PATTERN = re.compile(
    r"\b(aws certified|google cloud|gcp certified|azure certified|"
    r"pmp|cissp|comptia|network\+|security\+|a\+|linux\+|ceh|oscp|"
    r"ccna|ccnp|ccie|jncia|jncis|jncip|aruba certified|"
    r"cka|ckad|terraform associate|professional cloud|associate cloud|"
    r"six sigma|data engineer certified|machine learning engineer|"
    r"itil|prince2|scrum master|csm|pmi-acp)\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Extra-curriculars — leadership roles, community involvement, awards, etc.
# These are strong soft-skill signals that go beyond technical qualifications.
# ---------------------------------------------------------------------------
EXTRACURRICULAR_PATTERN = re.compile(
    r"\b(volunteer|club|society|hackathon|competition|award|honor|"
    r"dean'?s list|scholarship|fellowship|research|publication|"
    r"open.?source|community|mentor|tutoring|teaching assistant|"
    r"president|vice.?president|treasurer|secretary|captain|"
    r"team.?lead|committee|conference|workshop|seminar|"
    r"intercollegiate|varsity|athletics|greek life|fraternity|sorority)\b",
    re.I,
)

# GPA — e.g. "GPA: 3.8", "3.92 GPA", "cumulative GPA 3.5"
GPA_PATTERN = re.compile(
    r"\b(?:cumulative\s+)?gpa[:\s]+([0-4]\.\d{1,2})|([0-4]\.\d{1,2})\s*(?:\/\s*4\.0\s*)?gpa\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
@functions_framework.cloud_event
def resume_parser(cloud_event):
    """
    Entry point invoked by a Cloud Storage 'object.finalized' event.

    Args:
        cloud_event: CloudEvent whose .data dict contains 'bucket' and 'name'.
    """
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]  # e.g. "resumes/abc-123.pdf"

    if not file_name.lower().endswith(".pdf"):
        print(f"Skipping non-PDF file: {file_name}")
        return

    print(f"Processing: gs://{bucket_name}/{file_name}")

    # 1. Download
    pdf_bytes = _download_pdf(bucket_name, file_name)

    # 2. Extract text
    raw_text = _extract_text(pdf_bytes)

    # 3. Natural Language API entities
    nl_entities = _extract_nl_entities(raw_text)

    # 4. Structured extraction
    skills          = sorted({m.group(0).lower() for m in SKILL_KEYWORDS.finditer(raw_text)})
    degree_level    = _extract_degree(raw_text)
    degree_fields   = sorted({m.group(0).lower() for m in FIELD_PATTERN.finditer(raw_text)})
    experience_years = _extract_experience_years(raw_text)
    certifications  = sorted({m.group(0).lower() for m in CERT_PATTERN.finditer(raw_text)})
    extracurriculars = sorted({m.group(0).lower() for m in EXTRACURRICULAR_PATTERN.finditer(raw_text)})
    gpa             = _extract_gpa(raw_text)

    # Heuristic job titles from NL API WORK_OF_ART / OTHER entities
    titles = [
        e["name"] for e in nl_entities
        if e["type"] in ("WORK_OF_ART", "OTHER") and len(e["name"].split()) <= 5
    ]

    # 5. Persist
    doc_id = file_name.replace("/", "_").replace(".pdf", "")
    _save_to_firestore(
        doc_id, file_name, bucket_name, raw_text,
        skills, titles, nl_entities,
        degree_level, degree_fields, experience_years,
        certifications, extracurriculars, gpa,
    )

    print(
        f"Stored {doc_id}: degree={degree_level}, exp={experience_years}yrs, "
        f"{len(skills)} skills, {len(certifications)} certs, "
        f"{len(extracurriculars)} extras, gpa={gpa}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _download_pdf(bucket_name: str, file_name: str) -> bytes:
    """Download and return the raw bytes of a GCS object."""
    gcs = storage.Client()
    return gcs.bucket(bucket_name).blob(file_name).download_as_bytes()


def _extract_text(pdf_bytes: bytes) -> str:
    """Open PDF from memory with PyMuPDF and return all page text joined."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(page.get_text() for page in doc)


def _extract_nl_entities(text: str) -> list[dict]:
    """
    Call the Natural Language API and return simplified entity dicts.
    Text is capped at 50 000 characters to keep latency predictable.
    """
    client = language_v1.LanguageServiceClient()
    document = language_v1.Document(
        content=text[:50_000],
        type_=language_v1.Document.Type.PLAIN_TEXT,
    )
    response = client.analyze_entities(document=document)
    return [
        {
            "name": e.name,
            "type": language_v1.Entity.Type(e.type_).name,
            "salience": round(e.salience, 4),
        }
        for e in response.entities
    ]


def _extract_degree(text: str) -> str | None:
    """
    Return the highest degree level found in the resume text, or None.
    Levels in ascending order: associates < bachelors < masters < phd.
    """
    found = [level for level, pat in DEGREE_PATTERNS.items() if pat.search(text)]
    if not found:
        return None
    return max(found, key=lambda d: DEGREE_ORDER.index(d))


def _extract_experience_years(text: str) -> float:
    """
    Estimate total years of work experience by summing all year ranges found.
    'Present' / 'Current' / 'Now' is treated as the current calendar year.
    Overlapping ranges (e.g. two part-time jobs) may inflate the number slightly,
    but this gives a reasonable heuristic without a full resume parser.
    """
    total = 0.0
    for m in YEAR_RANGE_PATTERN.finditer(text):
        start = int(m.group(1))
        end_raw = m.group(2).lower()
        end = CURRENT_YEAR if end_raw in ("present", "current", "now") else int(end_raw)
        if end >= start:
            total += end - start
    return round(total, 1)


def _extract_gpa(text: str) -> float | None:
    """
    Return the first GPA value found in the resume, or None.
    Handles formats like 'GPA: 3.85', '3.9 GPA', '3.85/4.0'.
    """
    m = GPA_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    try:
        return float(raw)
    except ValueError:
        return None


def _save_to_firestore(
    doc_id, file_name, bucket_name, raw_text,
    skills, titles, nl_entities,
    degree_level, degree_fields, experience_years,
    certifications, extracurriculars, gpa,
) -> None:
    """
    Write (or overwrite) a document in the 'resumes' Firestore collection.
    The Flask app polls this collection by doc ID to check parse status.
    """
    db = firestore.Client()
    db.collection("resumes").document(doc_id).set({
        "file":              file_name,
        "bucket":            bucket_name,
        "raw_text":          raw_text[:10_000],  # capped to stay under 1 MB doc limit
        # Technical
        "skills":            skills,
        "titles":            titles,
        "entities":          nl_entities[:50],
        # Education
        "degree_level":      degree_level,       # e.g. "bachelors", "masters", None
        "degree_fields":     degree_fields,      # e.g. ["computer science"]
        "gpa":               gpa,                # float or None
        # Experience
        "experience_years":  experience_years,   # estimated float
        # Credentials & enrichment
        "certifications":    certifications,
        "extracurriculars":  extracurriculars,
    })
