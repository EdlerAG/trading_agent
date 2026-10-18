import hashlib
import secrets
from typing import Optional
from fastapi import Header, Cookie, Query, HTTPException, status
from app.core.config import settings


def compute_session_token(password: str) -> str:
    """Генерує детермінований SHA-256 токен сесії з пароля дашборду."""
    salted = f"quantcore_sovereign_v23::{password}".encode("utf-8")
    return hashlib.sha256(salted).hexdigest()


EXPECTED_SESSION_TOKEN: str = compute_session_token(settings.DASHBOARD_PASSWORD)


def verify_password_raw(candidate: str) -> bool:
    if not candidate:
        return False
    return secrets.compare_digest(candidate.strip(), settings.DASHBOARD_PASSWORD)


async def verify_api_access(
    x_api_key: Optional[str] = Header(default=None, alias="X-Api-Key"),
    authorization: Optional[str] = Header(default=None),
    qc_session: Optional[str] = Cookie(default=None),
    key: Optional[str] = Query(default=None),
) -> str:
    """
    Універсальна перевірка доступу для FastAPI ендпоінтів:
    - Через заголовок X-Api-Key (пароль або токен)
    - Через Authorization: Bearer <password/token>
    - Через Cookie 'qc_session' у веб-терміналі
    - Через query-параметр ?key=...
    """
    candidates = [x_api_key, qc_session, key]
    if authorization and authorization.lower().startswith("bearer "):
        candidates.append(authorization[7:].strip())

    for cand in candidates:
        if not cand:
            continue
        if secrets.compare_digest(cand, settings.DASHBOARD_PASSWORD) or secrets.compare_digest(cand, EXPECTED_SESSION_TOKEN):
            return "authenticated"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Невірний або відсутній ключ доступу до термінала",
    )