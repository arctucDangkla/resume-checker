"""
Cloud Run: Resume Job Match Scorer
====================================
Flask web application with multi-factor resume scoring.

Scoring breakdown (weights sum to 100):
  - Technical Skills  45%  — skill keyword overlap between resume and JD
  - Education         25%  — degree level vs. JD requirement + relevant field bonus
  - Experience        20%  — estimated resume years vs. JD required years
  - Certs & Extras    10%  — certifications and extra-curricular activities

Cloud services used:
  - Cloud Storage  : stores uploaded PDF resumes
  - Firestore      : reads parsed resume data written by the Cloud Function
  - Cloud Run      : hosts this Flask application (publicly accessible)

Routes:
  GET  /                    — single-page HTML UI
  POST /upload              — accepts PDF, uploads to GCS, returns resume_id
  GET  /status/<resume_id>  — polls Firestore for parse completion
  POST /score               — computes multi-factor match score
"""

import os
import re
import uuid

from flask import Flask, render_template, request, jsonify
from google.cloud import firestore, storage

app = Flask(__name__)

PROJECT_ID  = os.environ.get("GOOGLE_CLOUD_PROJECT", "resume-checker-1775416523")
BUCKET_NAME = f"{PROJECT_ID}-resume-uploads"

# ---------------------------------------------------------------------------
# Scoring weights — must sum to 100
# ---------------------------------------------------------------------------
W_SKILLS   = 45
W_EDUCATION = 25
W_EXPERIENCE = 20
W_EXTRAS    = 10

# ---------------------------------------------------------------------------
# Degree hierarchy used to compare resume degree vs. JD requirement.
# Higher index = higher degree.
# ---------------------------------------------------------------------------
DEGREE_ORDER = ["associates", "bachelors", "masters", "phd"]

# Map common JD phrases to our internal degree levels
JD_DEGREE_MAP = {
    re.compile(r"\b(ph\.?d|doctorate|doctoral)\b", re.I):            "phd",
    re.compile(r"\b(master'?s?|m\.?s\.?|m\.?a\.?|mba)\b", re.I):    "masters",
    re.compile(r"\b(bachelor'?s?|b\.?s\.?|b\.?a\.?|b\.?eng\.?)\b", re.I): "bachelors",
    re.compile(r"\b(associate'?s?|a\.?s\.?)\b", re.I):               "associates",
}

# Technical skill keywords — same set as the Cloud Function.
# Covers software dev, networking, security, cloud, infrastructure, and data/ML
# so the scorer works across many job families, not just developer roles.
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

# Extract "X years" / "X+ years of experience" from a job description
JD_YEARS_PATTERN = re.compile(
    r"(\d+)\+?\s*(?:to\s*\d+\s*)?year'?s?\s+(?:of\s+)?(?:experience|exp)",
    re.I,
)

# Certification keywords (mirrors Cloud Function list)
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
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_resume():
    """
    Accept a PDF, store it in GCS under resumes/<uuid>.pdf, and return a
    resume_id the browser can use to poll /status until parsing is done.
    """
    if "resume" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["resume"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    resume_id = str(uuid.uuid4())
    blob_name = f"resumes/{resume_id}.pdf"

    gcs = storage.Client()
    blob = gcs.bucket(BUCKET_NAME).blob(blob_name)
    blob.upload_from_file(file, content_type="application/pdf")

    return jsonify({"resume_id": resume_id, "status": "processing"})


@app.route("/status/<resume_id>")
def resume_status(resume_id):
    """
    Poll Firestore for the parsed resume document.
    Returns a summary of extracted data once ready so the UI can display it
    while the user types their job description.
    """
    db = firestore.Client()
    doc = db.collection("resumes").document(f"resumes_{resume_id}").get()

    if not doc.exists:
        return jsonify({"status": "processing"})

    data = doc.to_dict()
    return jsonify({
        "status":           "ready",
        "skills":           data.get("skills", []),
        "degree_level":     data.get("degree_level"),
        "degree_fields":    data.get("degree_fields", []),
        "experience_years": data.get("experience_years", 0),
        "certifications":   data.get("certifications", []),
        "extracurriculars": data.get("extracurriculars", []),
        "gpa":              data.get("gpa"),
    })


@app.route("/score", methods=["POST"])
def score():
    """
    Multi-factor resume scoring against a job description.

    Expected JSON body:
      { resume_id: str, job_description: str }

    Scoring formula (weights in parentheses):
      Technical Skills  (45%) — |resume_skills ∩ jd_skills| / |jd_skills|
      Education         (25%) — degree level match + relevant field bonus + GPA bonus
      Experience        (20%) — resume_years / required_years (capped at 1.0)
      Certs & Extras    (10%) — presence of certs and/or extracurriculars

    Returns:
      {
        score: float,                  — overall weighted score 0-100
        breakdown: {                   — per-category detail
          skills:     { score, weight, detail },
          education:  { score, weight, detail },
          experience: { score, weight, detail },
          extras:     { score, weight, detail },
        },
        matched_skills: [...],
        missing_skills: [...],
        resume_skills:  [...],
        job_skills:     [...],
      }
    """
    body = request.get_json(force=True)
    resume_id = body.get("resume_id")
    job_desc  = body.get("job_description", "")

    if not resume_id or not job_desc:
        return jsonify({"error": "resume_id and job_description are required"}), 400

    db = firestore.Client()
    doc = db.collection("resumes").document(f"resumes_{resume_id}").get()
    if not doc.exists:
        return jsonify({"error": "Resume not found or still processing"}), 404

    resume = doc.to_dict()

    # ------------------------------------------------------------------
    # 1. Skills score (45%)
    # ------------------------------------------------------------------
    resume_skills = set(resume.get("skills", []))
    job_skills    = {m.group(0).lower() for m in SKILL_KEYWORDS.finditer(job_desc)}

    if job_skills:
        matched       = resume_skills & job_skills
        missing       = job_skills - resume_skills
        skills_score  = len(matched) / len(job_skills)
        skills_detail = f"{len(matched)}/{len(job_skills)} required skills matched"
    else:
        # JD has no recognizable skill keywords — award full credit rather than penalizing
        matched, missing = set(), set()
        skills_score  = 1.0
        skills_detail = "No specific skills listed in job description"

    # ------------------------------------------------------------------
    # 2. Education score (25%)
    # ------------------------------------------------------------------
    resume_degree = resume.get("degree_level")       # e.g. "bachelors"
    resume_fields = set(resume.get("degree_fields", []))
    resume_gpa    = resume.get("gpa")                # float or None
    jd_degree     = _parse_jd_degree(job_desc)       # required degree from JD

    edu_score, edu_detail = _score_education(
        resume_degree, resume_fields, resume_gpa, jd_degree, job_desc
    )

    # ------------------------------------------------------------------
    # 3. Experience score (20%)
    # ------------------------------------------------------------------
    resume_years  = resume.get("experience_years", 0)
    required_years = _parse_jd_years(job_desc)

    exp_score, exp_detail = _score_experience(resume_years, required_years)

    # ------------------------------------------------------------------
    # 4. Certifications & Extras score (10%)
    # ------------------------------------------------------------------
    certs   = resume.get("certifications", [])
    extras  = resume.get("extracurriculars", [])
    jd_certs = {m.group(0).lower() for m in CERT_PATTERN.finditer(job_desc)}

    extras_score, extras_detail = _score_extras(certs, extras, jd_certs)

    # ------------------------------------------------------------------
    # Weighted total
    # ------------------------------------------------------------------
    overall = round(
        skills_score  * W_SKILLS   +
        edu_score     * W_EDUCATION +
        exp_score     * W_EXPERIENCE +
        extras_score  * W_EXTRAS,
        1,
    )

    return jsonify({
        "score": overall,
        "breakdown": {
            "skills": {
                "score":  round(skills_score * 100, 1),
                "weight": W_SKILLS,
                "detail": skills_detail,
            },
            "education": {
                "score":  round(edu_score * 100, 1),
                "weight": W_EDUCATION,
                "detail": edu_detail,
            },
            "experience": {
                "score":  round(exp_score * 100, 1),
                "weight": W_EXPERIENCE,
                "detail": exp_detail,
            },
            "extras": {
                "score":  round(extras_score * 100, 1),
                "weight": W_EXTRAS,
                "detail": extras_detail,
            },
        },
        "matched_skills":  sorted(matched),
        "missing_skills":  sorted(missing),
        "resume_skills":   sorted(resume_skills),
        "job_skills":      sorted(job_skills),
        "certifications":  certs,
        "extracurriculars": extras,
        "degree_level":    resume_degree,
        "degree_fields":   sorted(resume_fields),
        "experience_years": resume_years,
        "gpa":             resume_gpa,
    })


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _parse_jd_degree(job_desc: str) -> str | None:
    """Return the highest degree level required by the job description, or None."""
    found = []
    for pattern, level in JD_DEGREE_MAP.items():
        if pattern.search(job_desc):
            found.append(level)
    if not found:
        return None
    return max(found, key=lambda d: DEGREE_ORDER.index(d))


def _parse_jd_years(job_desc: str) -> float:
    """
    Extract the first 'X years of experience' requirement from the JD.
    Returns 0.0 if none found (no requirement = no penalty).
    """
    m = JD_YEARS_PATTERN.search(job_desc)
    return float(m.group(1)) if m else 0.0


def _score_education(
    resume_degree: str | None,
    resume_fields: set[str],
    resume_gpa: float | None,
    jd_degree: str | None,
    job_desc: str,
) -> tuple[float, str]:
    """
    Return (score 0-1, explanation string) for the education category.

    Logic:
      - If JD specifies a degree:
          resume meets requirement  → base 0.80
          resume exceeds requirement → base 1.00
          resume one level below    → base 0.50
          resume two+ levels below  → base 0.20
          no degree on resume       → base 0.10
      - If JD doesn't specify a degree:
          any degree found → 0.90
          no degree found  → 0.60 (doesn't hurt much)
      - Bonus +0.10 if resume field matches a STEM/CS keyword in the JD
      - Bonus +0.05 if GPA ≥ 3.5 (shows academic excellence)
      Score is capped at 1.0.
    """
    base   = 0.0
    notes  = []

    if jd_degree:
        if resume_degree is None:
            base = 0.10
            notes.append(f"No degree detected; JD requires {jd_degree}")
        else:
            resume_rank = DEGREE_ORDER.index(resume_degree)
            jd_rank     = DEGREE_ORDER.index(jd_degree)
            gap         = resume_rank - jd_rank
            if gap >= 1:
                base = 1.00
                notes.append(f"{resume_degree} exceeds JD requirement of {jd_degree}")
            elif gap == 0:
                base = 0.80
                notes.append(f"{resume_degree} meets JD requirement")
            elif gap == -1:
                base = 0.50
                notes.append(f"{resume_degree} is one level below required {jd_degree}")
            else:
                base = 0.20
                notes.append(f"{resume_degree} is significantly below required {jd_degree}")
    else:
        # JD does not state a degree requirement
        if resume_degree:
            base = 0.90
            notes.append(f"{resume_degree} found; no specific degree required")
        else:
            base = 0.60
            notes.append("No degree requirement stated; none detected on resume")

    # Bonus: relevant field of study (CS, engineering, etc.)
    if resume_fields:
        base = min(1.0, base + 0.10)
        notes.append(f"relevant field(s): {', '.join(sorted(resume_fields))}")

    # Bonus: strong GPA
    if resume_gpa is not None and resume_gpa >= 3.5:
        base = min(1.0, base + 0.05)
        notes.append(f"GPA {resume_gpa}")

    return base, "; ".join(notes) or "No education information found"


def _score_experience(resume_years: float, required_years: float) -> tuple[float, str]:
    """
    Return (score 0-1, explanation string) for the experience category.

    If the JD specifies required years:
      score = min(resume_years / required_years, 1.0)
      (meeting the requirement scores 1.0; partial credit for being close)
    If no requirement is stated, award full credit.
    """
    if required_years <= 0:
        detail = f"{resume_years:.1f} yrs detected; no experience requirement stated"
        return 1.0, detail

    score  = min(resume_years / required_years, 1.0)
    detail = f"{resume_years:.1f} yrs detected vs. {required_years:.0f} yrs required"
    return score, detail


def _score_extras(
    certs: list[str],
    extras: list[str],
    jd_certs: set[str],
) -> tuple[float, str]:
    """
    Return (score 0-1, explanation string) for the certifications & extras category.

    Scoring:
      - Certifications matching the JD:  +0.50 base, capped at 0.60
      - Any certification present:       +0.30 if no JD certs required
      - Extra-curricular activities:     +0.40 (capped so total ≤ 1.0)
    """
    score = 0.0
    notes = []

    if jd_certs:
        # JD asks for specific certs — check how many the resume has
        matched_certs = {c for c in certs if any(jc in c or c in jc for jc in jd_certs)}
        if matched_certs:
            score += min(0.60, 0.30 * len(matched_certs))
            notes.append(f"{len(matched_certs)} matching cert(s): {', '.join(sorted(matched_certs))}")
        else:
            notes.append("No matching certifications found")
    else:
        # No cert requirement — reward having any cert
        if certs:
            score += 0.30
            notes.append(f"{len(certs)} certification(s) found")

    # Extra-curriculars add value regardless of JD content
    if extras:
        score = min(1.0, score + 0.40)
        notes.append(f"{len(extras)} extra-curricular indicator(s)")
    elif score == 0.0:
        notes.append("No certifications or extra-curriculars detected")

    score = min(score, 1.0)
    return score, "; ".join(notes)


# ---------------------------------------------------------------------------
# Local dev entry point (Cloud Run uses the Dockerfile CMD instead)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
