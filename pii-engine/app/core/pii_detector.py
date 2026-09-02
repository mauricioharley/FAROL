"""
Two-layer PII detection:
  1. Column/key name heuristics (fast, no data access)
  2. Value-level regex sampling (first N values)
"""

import re
from app.models.schemas import DataCategory, PiiSeverity, FieldInfo

_NAME_HINTS: dict[str, tuple[PiiSeverity, DataCategory]] = {
    "cpf": (PiiSeverity.sensitive, DataCategory.identifier),
    "cnpj": (PiiSeverity.sensitive, DataCategory.identifier),
    "rg": (PiiSeverity.sensitive, DataCategory.identifier),
    "cnh": (PiiSeverity.sensitive, DataCategory.identifier),
    "passaporte": (PiiSeverity.sensitive, DataCategory.identifier),
    "cartao": (PiiSeverity.sensitive, DataCategory.secret),
    "cartão": (PiiSeverity.sensitive, DataCategory.secret),
    "senha": (PiiSeverity.sensitive, DataCategory.secret),
    "password": (PiiSeverity.sensitive, DataCategory.secret),
    "token": (PiiSeverity.sensitive, DataCategory.secret),
    "nome": (PiiSeverity.personal, DataCategory.categorical),
    "name": (PiiSeverity.personal, DataCategory.categorical),
    "razao_social": (PiiSeverity.personal, DataCategory.categorical),
    "razão_social": (PiiSeverity.personal, DataCategory.categorical),
    "email": (PiiSeverity.personal, DataCategory.identifier),
    "e_mail": (PiiSeverity.personal, DataCategory.identifier),
    "telefone": (PiiSeverity.personal, DataCategory.categorical),
    "celular": (PiiSeverity.personal, DataCategory.categorical),
    "phone": (PiiSeverity.personal, DataCategory.categorical),
    "fone": (PiiSeverity.personal, DataCategory.categorical),
    "nascimento": (PiiSeverity.personal, DataCategory.date),
    "data_nasc": (PiiSeverity.personal, DataCategory.date),
    "data_nascimento": (PiiSeverity.personal, DataCategory.date),
    "birth": (PiiSeverity.personal, DataCategory.date),
    "dob": (PiiSeverity.personal, DataCategory.date),
    "endereco": (PiiSeverity.personal, DataCategory.categorical),
    "endereço": (PiiSeverity.personal, DataCategory.categorical),
    "address": (PiiSeverity.personal, DataCategory.categorical),
    "logradouro": (PiiSeverity.personal, DataCategory.categorical),
    "cep": (PiiSeverity.personal, DataCategory.categorical),
    "ip": (PiiSeverity.personal, DataCategory.categorical),
    "latitude": (PiiSeverity.personal, DataCategory.geo),
    "longitude": (PiiSeverity.personal, DataCategory.geo),
    "lat": (PiiSeverity.personal, DataCategory.geo),
    "lon": (PiiSeverity.personal, DataCategory.geo),
    "lng": (PiiSeverity.personal, DataCategory.geo),
    "localizacao": (PiiSeverity.personal, DataCategory.categorical),
    "localização": (PiiSeverity.personal, DataCategory.categorical),
    # Dado sensível por natureza - LGPD Art. 5º, II (origem religiosa)
    "religiao": (PiiSeverity.sensitive, DataCategory.categorical),
    "religião": (PiiSeverity.sensitive, DataCategory.categorical),
    # Dado sensível por natureza - LGPD Art. 5º, II (dado referente a pessoa com deficiência)
    "pcd": (PiiSeverity.sensitive, DataCategory.categorical),
    "deficiencia": (PiiSeverity.sensitive, DataCategory.categorical),
    "deficiência": (PiiSeverity.sensitive, DataCategory.categorical),
    "portador_deficiencia": (PiiSeverity.sensitive, DataCategory.categorical),
    "portador_deficiência": (PiiSeverity.sensitive, DataCategory.categorical),
    # Remuneração - dado pessoal (não sensível), mas ligado a pessoa identificável
    "salario": (PiiSeverity.personal, DataCategory.numeric),
    "salário": (PiiSeverity.personal, DataCategory.numeric),
    "remuneracao": (PiiSeverity.personal, DataCategory.numeric),
    "remuneração": (PiiSeverity.personal, DataCategory.numeric),
    "vencimento": (PiiSeverity.personal, DataCategory.numeric),
}

# All patterns are fully anchored (^…$) and use non-overlapping character classes
# to prevent catastrophic backtracking (ReDoS). Length limits on the email
# local part and domain segments bound worst-case complexity.
_VALUE_PATTERNS: list[tuple[str, re.Pattern, PiiSeverity, DataCategory]] = [
    ("cpf",      re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$"), PiiSeverity.sensitive, DataCategory.identifier),
    ("cnpj",     re.compile(r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$"), PiiSeverity.sensitive, DataCategory.identifier),
    # Local part ≤64 chars (RFC 5321); domain segments ≤63 chars (RFC 1035)
    ("email",    re.compile(r"^[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9\-]{1,63}(?:\.[a-zA-Z0-9\-]{1,63})*\.[a-zA-Z]{2,}$"), PiiSeverity.personal, DataCategory.identifier),
    ("phone_br", re.compile(r"^(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)(?:\d{4,5}[-\s]?\d{4})$"), PiiSeverity.personal, DataCategory.categorical),
    ("date",     re.compile(r"^(?:\d{2}[/\-]\d{2}[/\-]\d{4}|\d{4}[/\-]\d{2}[/\-]\d{2})$"), PiiSeverity.personal, DataCategory.date),
    ("cep",      re.compile(r"^\d{5}-?\d{3}$"), PiiSeverity.personal, DataCategory.categorical),
]


def _match_name(column: str) -> tuple[PiiSeverity, DataCategory] | None:
    normalized = re.sub(r"[\s\-]", "_", column.lower().strip())
    for hint, result in _NAME_HINTS.items():
        if hint in normalized:
            return result
    return None


def _match_values(
    values: list[str],
) -> tuple[PiiSeverity, DataCategory] | None:
    sample = [v for v in values if v and v.strip()][:20]
    if not sample:
        return None
    for _, pattern, severity, category in _VALUE_PATTERNS:
        hits = sum(1 for v in sample if pattern.match(v.strip()))
        if hits / len(sample) >= 0.6:
            return severity, category
    return None


def detect_fields(
    columns: list[str],
    sample_values: dict[str, list[str]] | None = None,
) -> list[FieldInfo]:
    fields: list[FieldInfo] = []
    for col in columns:
        name_match = _match_name(col)
        value_match = None
        if sample_values and col in sample_values:
            value_match = _match_values(sample_values[col])

        if name_match or value_match:
            severity, category = name_match or value_match  # type: ignore[misc]
            fields.append(
                FieldInfo(
                    name=col,
                    path=col,
                    severity=severity,
                    auto_detected=True,
                    category=category,
                )
            )
        else:
            fields.append(
                FieldInfo(
                    name=col,
                    path=col,
                    severity=PiiSeverity.public,
                    auto_detected=False,
                    category=None,
                )
            )
    return fields
