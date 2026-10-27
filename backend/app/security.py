import hashlib
import ipaddress
import json
import secrets

import bcrypt

from .config import cfg
from .models import Organization


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=cfg.bcrypt_rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def get_trusted_ips(org: Organization) -> list[str]:
    try:
        return list(json.loads(org.trusted_ips or "[]"))
    except ValueError:
        return []


def normalize_ip_list(items: list[str]) -> list[str]:
    """Validate IPs / CIDRs from Dev Settings. Raises ValueError on bad input."""
    out: list[str] = []
    for raw in items:
        s = raw.strip()
        if not s:
            continue
        ipaddress.ip_network(s, strict=False)  # raises ValueError
        out.append(s)
    return out


def ip_is_trusted(ip: str, org: Organization) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in get_trusted_ips(org):
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False
