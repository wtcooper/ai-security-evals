#!/usr/bin/env python3
"""CWE normalisation shared by every harness: map any CWE to a top-level *family* and
recover a CWE from free-text categories (LLM scanners rarely emit CWE ids).

    from cwe_map import family_of, cwe_from_text
    family_of("639")        -> "284"     (IDOR -> improper access control)
    cwe_from_text("Path traversal in download endpoint") -> "22"

Matching rules for detection benchmarks (design doc §2.4) compare on *family*, so two
scanners that label the same bug CWE-23 and CWE-22 still agree.
"""
from __future__ import annotations

import re

# child -> family (top-level CWE we report on). Identity for anything not listed.
CWE_FAMILY: dict[str, str] = {
    # path traversal / file handling
    "23": "22", "24": "22", "35": "22", "36": "22", "37": "22", "73": "22", "99": "22",
    # command injection
    "77": "78", "88": "78", "624": "78",
    # SQL injection
    "564": "89", "943": "89",
    # XSS
    "80": "79", "81": "79", "83": "79", "85": "79", "86": "79", "87": "79", "116": "79",
    # code injection / eval
    "95": "94", "96": "94", "1336": "94", "917": "94",
    # access control / IDOR / authz
    "285": "284", "639": "284", "862": "284", "863": "284", "566": "284", "1220": "284",
    # memory safety
    "120": "119", "121": "119", "122": "119", "124": "119", "125": "119", "126": "119",
    "127": "119", "787": "119", "788": "119", "805": "119", "806": "119", "416": "119", "415": "119",
    # integer
    "191": "190", "680": "190", "681": "190",
    # hard-coded secrets / credentials
    "259": "798", "321": "798", "13": "798",
    # info exposure
    "209": "200", "215": "200", "532": "200", "538": "200", "548": "200", "497": "200",
    # session / auth
    "384": "613", "614": "613",
    "306": "287", "307": "287", "521": "287", "620": "287", "640": "287", "916": "287",
    # crypto
    "326": "327", "328": "327", "780": "327", "1240": "327",
    "338": "330", "331": "330", "337": "330",
    # XXE / XML
    "776": "611",
    # deserialization
    "915": "915",  # mass assignment keeps its own family
    # SSRF / redirect
    "601": "601", "918": "918",
    # resource exhaustion / DoS
    "770": "400", "400": "400", "409": "400", "835": "400",
    # uploads
    "434": "434", "646": "434",
    # csv/formula injection
    "1236": "1236",
    # csrf
    "352": "352",
    # ldap/xpath/other injections
    "90": "74", "91": "74", "643": "74", "1427": "74",
    # log injection
    "117": "117",
    # race
    "367": "362",
    # improper input validation umbrella
    "20": "20", "1284": "20", "1286": "20",
}

# Keyword -> CWE for free-text categories/titles (LLM scanners). Order matters: more
# specific phrases first. Values are already family-level ids.
CATEGORY_TO_CWE: list[tuple[str, str]] = [
    (r"zip[- ]?slip", "22"),
    (r"path[- ]?traversal|directory[- ]?traversal|\.\./|file[- ]?inclusion|lfi\b", "22"),
    (r"\bssrf\b|server[- ]side request forgery", "918"),
    (r"open[- ]?redirect|unvalidated redirect", "601"),
    (r"\bidor\b|insecure direct object|broken (object[- ]level )?authori[sz]ation|missing authori[sz]ation|"
     r"tenant isolation|cross[- ]tenant|access[- ]control|privilege escalation|bola\b", "284"),
    (r"broken authentication|missing authentication|weak password|credential stuffing|brute[- ]force|"
     r"authentication bypass", "287"),
    (r"session (fixation|management)|insecure cookie|cookie flag", "613"),
    (r"sql[- ]?injection|\bsqli\b", "89"),
    (r"nosql[- ]?injection", "943"),
    (r"(os |shell |command)[- ]?injection|shell=true|subprocess", "78"),
    (r"code[- ]?injection|remote code execution|\brce\b|\beval\b|exec\(", "94"),
    (r"template[- ]?injection|\bssti\b", "94"),
    (r"(cross[- ]?site scripting|\bxss\b|html injection)", "79"),
    (r"\bcsrf\b|cross[- ]site request forgery", "352"),
    (r"deserial|pickle|unpickl|yaml\.load|marshal", "502"),
    (r"\bxxe\b|xml external entit", "611"),
    (r"mass[- ]?assignment|over[- ]?posting|price tamper|parameter tamper", "915"),
    (r"(csv|formula|spreadsheet)[- ]?injection", "1236"),
    (r"(unrestricted|arbitrary|insecure|unsafe) (file )?upload|content[- ]type validation", "434"),
    (r"hard[- ]?coded (secret|credential|password|key|token)|secret(s)? in (source|code|repo)|"
     r"exposed (api )?key|leaked credential", "798"),
    (r"(weak|broken|insecure) (crypto|cipher|hash|encryption)|\bmd5\b|\bsha1\b|\becb\b", "327"),
    (r"insecure random|predictable (token|id|random)|\brandom\.random\b", "330"),
    (r"(information|data|sensitive) (exposure|disclosure|leak)|stack trace|verbose error|debug mode", "200"),
    (r"log[- ]?injection|log forging", "117"),
    (r"prompt[- ]?injection|llm|tool[- ]?argument|agent tool", "77"),   # LLM sinks: neutral-element injection
    (r"(denial of service|\bdos\b|resource exhaustion|unbounded|no (size|rate) limit|regex dos|redos)", "400"),
    (r"race condition|toctou", "362"),
    (r"(ldap|xpath|header|crlf)[- ]?injection|\binjection\b", "74"),
    (r"input validation|missing validation|improper validation", "20"),
]

_CWE_RE = re.compile(r"cwe[-_ ]?0*(\d+)", re.I)


def family_of(cwe: str | int | None) -> str:
    """Top-level family for a CWE id ("22", "CWE-023", 639...). Unknown -> "uncwe"."""
    if cwe is None:
        return "uncwe"
    s = str(cwe).strip()
    m = _CWE_RE.search(s)
    if m:
        s = m.group(1)
    if not s.isdigit():
        return "uncwe"
    s = str(int(s))
    return CWE_FAMILY.get(s, s)


def cwe_from_text(text: str | None) -> str | None:
    """Recover a CWE id from free text: explicit CWE-NNN first, then keyword table."""
    if not text:
        return None
    m = _CWE_RE.search(text)
    if m:
        return str(int(m.group(1)))
    t = text.lower()
    for pat, cwe in CATEGORY_TO_CWE:
        if re.search(pat, t):
            return cwe
    return None
