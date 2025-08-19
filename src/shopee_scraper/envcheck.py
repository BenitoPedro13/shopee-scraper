from __future__ import annotations

import re
from typing import List, Tuple, Optional

from .config import settings


KNOWN_DOMAINS = {
    "shopee.com.br": {"locale": "pt-BR", "timezone": "America/Sao_Paulo"},
    "shopee.com.mx": {"locale": "es-MX", "timezone": "America/Mexico_City"},
    "shopee.com.my": {"locale": "en-MY", "timezone": "Asia/Kuala_Lumpur"},
    "shopee.sg": {"locale": "en-SG", "timezone": "Asia/Singapore"},
    "shopee.ph": {"locale": "en-PH", "timezone": "Asia/Manila"},
    "shopee.co.id": {"locale": "id-ID", "timezone": "Asia/Jakarta"},
    "shopee.vn": {"locale": "vi-VN", "timezone": "Asia/Ho_Chi_Minh"},
    "shopee.co.th": {"locale": "th-TH", "timezone": "Asia/Bangkok"},
}


def suggest_region_for_domain(domain: str) -> Optional[dict]:
    return KNOWN_DOMAINS.get(domain)


def validate_environment() -> List[Tuple[str, str]]:
    """Returns list of (level, message), where level is 'warn' or 'error'."""
    issues: List[Tuple[str, str]] = []

    # Domain
    domain = settings.shopee_domain
    if domain not in KNOWN_DOMAINS:
        issues.append(("warn", f"SHOPEE_DOMAIN='{domain}' não reconhecido. Verifique a região correta."))
    else:
        rec = KNOWN_DOMAINS[domain]
        if settings.locale != rec["locale"]:
            issues.append(
                (
                    "warn",
                    f"LOCALE='{settings.locale}' diferente do recomendado para {domain} ({rec['locale']}).",
                )
            )
        if settings.timezone_id != rec["timezone"]:
            issues.append(
                (
                    "warn",
                    f"TIMEZONE='{settings.timezone_id}' diferente do recomendado para {domain} ({rec['timezone']}).",
                )
            )

    # Profile
    if not settings.profile_name:
        issues.append(("warn", "PROFILE_NAME não definido. Recomenda-se definir um perfil por conta."))

    # Proxy
    proxy = settings.proxy_url or ""
    if proxy:
        if not re.match(r"^(https?|socks5|socks4|socks5h|socks4a)://", proxy):
            issues.append(("warn", "PROXY_URL sem esquema reconhecido (http/socks4/socks5)."))
        # Simple format check host:port presence
        if "@" in proxy:
            # user:pass@host:port
            if proxy.count(":") < 2:
                issues.append(("error", "PROXY_URL com credenciais mas formato suspeito. Esperado user:pass@host:port."))

    # 3P cookies
    if not settings.disable_3pc_phaseout:
        issues.append(("warn", "DISABLE_3PC_PHASEOUT=false — alguns widgets podem falhar por 3P cookies bloqueados."))

    return issues

