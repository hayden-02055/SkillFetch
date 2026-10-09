"""Static, line-based inspection of untrusted SKILL.md text.

high   -> loading is blocked
medium -> shown as a warning; the user decides
"""

import re

from skillfetch.models import SecurityFinding, SecurityReport

DISCLAIMER = (
    "Static checks cannot guarantee that a skill is safe. Read the skill text before approving it."
)

CATEGORY_LABELS = {
    "instruction_override": "Tries to override user/system instructions (prompt injection)",
    "shell_execution": "Asks to run shell commands or scripts",
    "secret_access": "Accesses environment variables or secrets",
    "network_transfer": "Sends data over the network",
    "excessive_access": "Requests broad file or system access",
}

_I = re.IGNORECASE
_SECRET_FILES = (
    r"(?:~/\.ssh|id_rsa|id_ed25519|\.aws/credentials|\.netrc|\.git-credentials|/etc/shadow)"
)
_SECRET_VARS = r"\$\{?\w*(?:TOKEN|SECRET|API_KEY|APIKEY|PASSWORD|PASSWD|CREDENTIALS?)\w*\}?"

_RULES: list[tuple[str, str, re.Pattern]] = [
    # --- high: block ---
    (
        "instruction_override",
        "high",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+|your\s+)*"
            r"(?:previous|prior|above|earlier|preceding|user'?s?|system|original)\s+"
            r"(?:instructions?|prompts?|rules|directions|guidelines|messages?)",
            _I,
        ),
    ),
    (
        "instruction_override",
        "high",
        re.compile(
            r"\b(?:do\s+not|don'?t|never)\s+(?:tell|inform|notify|alert|reveal\s+to|mention\s+to)"
            r"\s+the\s+user",
            _I,
        ),
    ),
    (
        "instruction_override",
        "high",
        re.compile(r"\bwithout\s+(?:telling|informing|notifying|alerting)\s+the\s+user", _I),
    ),
    (
        "instruction_override",
        "high",
        re.compile(
            r"\b(?:reveal|print|output|show|leak|repeat)\s+(?:your\s+|the\s+)?system\s+prompt", _I
        ),
    ),
    (
        "instruction_override",
        "high",
        re.compile(
            r"\byou\s+are\s+now\s+(?:in\s+)?(?:developer\s+mode|dan\b|jailbroken|unrestricted)", _I
        ),
    ),
    ("instruction_override", "high", re.compile(r"<\|im_start\|>|<\|system\|>|\[/?INST\]")),
    (
        "shell_execution",
        "high",
        re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b", _I),
    ),
    ("shell_execution", "high", re.compile(r"\b(?:ba|z)?sh\s+<\(\s*(?:curl|wget)\b", _I)),
    ("shell_execution", "high", re.compile(r"base64\s+(?:-d|--decode)\b[^\n]*\|\s*(?:ba|z)?sh\b")),
    ("shell_execution", "high", re.compile(r"\beval\s+\"?\$\(\s*(?:curl|wget)\b")),
    (
        "shell_execution",
        "high",
        re.compile(
            r"\brm\s+-[a-zA-Z]*(?:rf|fr)[a-zA-Z]*\s+(?:--no-preserve-root\s+)?"
            r"(?:/|~/?|\$HOME/?)(?:\*)?(?=[\s\"'`;]|$)"
        ),
    ),
    ("shell_execution", "high", re.compile(r"\bnc\b[^\n]*\s-e\s|/dev/tcp/")),
    (
        "secret_access",
        "high",
        re.compile(rf"\b(?:cat|less|more|head|tail|cp|scp)\b[^\n]*{_SECRET_FILES}"),
    ),
    (
        "network_transfer",
        "high",
        re.compile(
            rf"(?:\b(?:curl|wget|nc)\b|\brequests\.\w+\(|\bfetch\()[^\n]*(?:{_SECRET_VARS}|{_SECRET_FILES}"
            r"|\$\(\s*(?:env|printenv)\s*\))",
            _I,
        ),
    ),
    (
        "network_transfer",
        "high",
        re.compile(
            r"\b(?:send|upload|post|transmit|exfiltrate)\s+(?:the\s+|all\s+|any\s+|your\s+)*"
            r"(?:api\s+keys?|tokens?|secrets?|credentials?|passwords?|env(?:ironment)?\s+variables?|"
            r"ssh\s+keys?)\s+to\b",
            _I,
        ),
    ),
    # --- medium: warn ---
    (
        "shell_execution",
        "medium",
        re.compile(r"^\s*```\s*(?:bash|sh|shell|zsh|console|powershell)\b", _I),
    ),
    (
        "shell_execution",
        "medium",
        re.compile(r"\b(?:subprocess\.\w+|os\.system|os\.popen|child_process|execSync|exec\()"),
    ),
    (
        "shell_execution",
        "medium",
        re.compile(
            r"\b(?:pip3?\s+install|npm\s+(?:install|i)\s|npx\s|yarn\s+add|brew\s+install|"
            r"apt(?:-get)?\s+install|cargo\s+install|go\s+install)\b"
        ),
    ),
    ("shell_execution", "medium", re.compile(r"\brm\s+-[a-zA-Z]*(?:rf|fr)\b")),
    (
        "secret_access",
        "medium",
        re.compile(r"\b(?:os\.environ|os\.getenv|process\.env|printenv)\b|" + _SECRET_VARS),
    ),
    ("secret_access", "medium", re.compile(r"(?:^|[\s\"'`/])\.env\b|" + _SECRET_FILES)),
    (
        "network_transfer",
        "medium",
        re.compile(
            r"\b(?:curl|wget)\s|\brequests\.(?:post|put|patch)\b|\bfetch\(|\burllib\.request\b|"
            r"\bnc\s+-|webhook\.site|requestbin|ngrok\.io|pipedream\.net",
            _I,
        ),
    ),
    (
        "excessive_access",
        "medium",
        re.compile(
            r"\bsudo\s|\bchmod\s+(?:-R\s+)?777\b|\bchown\s+-R\b|(?<![\w.])/etc/|"
            r"~/\.(?:bashrc|zshrc|profile|bash_profile)\b|\bcrontab\b|\b(?:systemctl|launchctl)\s|"
            r"--dangerously-skip-permissions"
        ),
    ),
]


def inspect_skill(content: str) -> SecurityReport:
    findings: list[SecurityFinding] = []
    seen: set[tuple[str, str, int]] = set()
    for lineno, line in enumerate(content.splitlines(), start=1):
        for category, severity, pattern in _RULES:
            key = (category, severity, lineno)
            if key in seen or not pattern.search(line):
                continue
            seen.add(key)
            excerpt = line.strip()
            findings.append(
                SecurityFinding(
                    category=category,
                    severity=severity,
                    line=lineno,
                    excerpt=excerpt[:157] + "..." if len(excerpt) > 160 else excerpt,
                )
            )
    findings.sort(key=lambda f: (f.severity != "high", f.line))
    return SecurityReport(findings=findings)
