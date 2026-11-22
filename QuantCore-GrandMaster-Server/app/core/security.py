import hashlib
import secrets
import time
from collections import deque
from typing import Dict, Optional
from fastapi import Header, Cookie, Query, HTTPException, status
from app.core.config import settings

_LOGIN_FAILURES: Dict[str, deque] = {}
_LOGIN_WINDOW_SEC = 60.0
_LOGIN_MAX_ATTEMPTS = 5


def check_login_rate_limit(client_ip: str) -> None:
    """Блокує IP при перевищенні ліміту невдалих спроб входу (5 спроб / 60с)."""
    now = time.monotonic()
    q = _LOGIN_FAILURES.get(client_ip)
    if not q:
        return
    while q and now - q[0] > _LOGIN_WINDOW_SEC:
        q.popleft()
    if len(q) >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Забагато невдалих спроб входу. Зачекайте 60 секунд.",
        )


def record_login_failure(client_ip: str) -> None:
    now = time.monotonic()
    q = _LOGIN_FAILURES.setdefault(client_ip, deque())
    q.append(now)


def reset_login_failures(client_ip: str) -> None:
    _LOGIN_FAILURES.pop(client_ip, None)


def compute_session_token(password: str) -> str:
    """Генерує детермінований SHA-256 токен сесії з пароля дашборду."""
    salted = f"quantcore_sovereign_v58::{password}".encode("utf-8")
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
    candidates = [x_api_key, qc_session]
    if settings.ALLOW_QUERY_KEY_AUTH and key:
        candidates.append(key)
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