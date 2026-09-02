from pydantic import BaseModel
from enum import Enum


class PiiSeverity(str, Enum):
    sensitive = "sensitive"
    personal = "personal"
    public = "public"


class DataCategory(str, Enum):
    """Tipo de dado usado para restringir quais técnicas fazem sentido em cada campo."""
    identifier = "identifier"    # CPF, CNPJ, RG, e-mail...
    categorical = "categorical"  # nome, religião, PCD, endereço, telefone...
    date = "date"                # datas (ex.: nascimento)
    numeric = "numeric"          # valores numéricos (ex.: salário)
    geo = "geo"                  # coordenadas geográficas
    secret = "secret"            # senha, token, cartão


class FieldInfo(BaseModel):
    name: str
    path: str
    severity: PiiSeverity
    auto_detected: bool = False
    category: DataCategory | None = None
