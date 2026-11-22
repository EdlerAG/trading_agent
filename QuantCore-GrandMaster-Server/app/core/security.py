import hashlib
import os
import secrets
import time
from collections import deque
from typing import Dict, List, Optional, Tuple
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


def get_admin_password() -> str:
    """Повертає пароль адміністратора з файла ключа (.admin_key) або з settings.DASHBOARD_PASSWORD."""
    key_file = getattr(settings, "DASHBOARD_ADMIN_KEY_FILE", "")
    if key_file and os.path.isfile(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                val = f.read().strip()
            if val:
                return val
        except OSError:
            pass
    return settings.DASHBOARD_PASSWORD


def get_view_password() -> str:
    """Повертає опційний пароль режиму «тільки перегляд» (viewer)."""
    return (getattr(settings, "DASHBOARD_VIEW_PASSWORD", "") or "").strip()


def compute_session_token(password: str, role: str = "admin") -> str:
    """Генерує детермінований SHA-256 токен сесії для конкретної ролі (admin/viewer)."""
    salted = f"quantcore_sovereign_{role}::{password}".encode("utf-8")
    return hashlib.sha256(salted).hexdigest()


EXPECTED_SESSION_TOKEN: str = compute_session_token(settings.DASHBOARD_PASSWORD, role="admin")


def authenticate_login_password(candidate: str) -> Optional[Tuple[str, str]]:
    """Перевіряє пароль при логіні та повертає (role, session_token) або None."""
    clean = (candidate or "").strip()
    if not clean:
        return None
    admin_pw = get_admin_password()
    if secrets.compare_digest(clean, admin_pw):
        return ("admin", compute_session_token(admin_pw, role="admin"))
    view_pw = get_view_password()
    if view_pw and secrets.compare_digest(clean, view_pw):
        return ("viewer", compute_session_token(view_pw, role="viewer"))
    return None


def verify_password_raw(candidate: str) -> bool:
    return authenticate_login_password(candidate) is not None


def _resolve_access_role(candidates: List[Optional[str]]) -> Optional[str]:
    admin_pw = get_admin_password()
    admin_tok = compute_session_token(admin_pw, role="admin")
    for cand in candidates:
        if not cand:
            continue
        if secrets.compare_digest(cand, admin_pw) or secrets.compare_digest(cand, admin_tok):
            return "admin"

    view_pw = get_view_password()
    if view_pw:
        view_tok = compute_session_token(view_pw, role="viewer")
        for cand in candidates:
            if not cand:
                continue
            if secrets.compare_digest(cand, view_pw) or secrets.compare_digest(cand, view_tok):
                return "viewer"
    return None


def _collect_auth_candidates(
    x_api_key: Optional[str],
    authorization: Optional[str],
    qc_session: Optional[str],
    key: Optional[str],
) -> List[Optional[str]]:
    candidates: List[Optional[str]] = [x_api_key, qc_session]
    if settings.ALLOW_QUERY_KEY_AUTH and key:
        candidates.append(key)
    if authorization and authorization.lower().startswith("bearer "):
        candidates.append(authorization[7:].strip())
    return candidates


async def verify_api_access(
    x_api_key: Optional[str] = Header(default=None, alias="X-Api-Key"),
    authorization: Optional[str] = Header(default=None),
    qc_session: Optional[str] = Cookie(default=None),
    key: Optional[str] = Query(default=None),
) -> str:
    """Перевіряє доступ для перегляду (admin або viewer) і повертає активну роль."""
    role = _resolve_access_role(_collect_auth_candidates(x_api_key, authorization, qc_session, key))
    if role is not None:
        return role

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Невірний або відсутній ключ доступу до термінала",
    )


async def verify_admin_access(
    x_api_key: Optional[str] = Header(default=None, alias="X-Api-Key"),
    authorization: Optional[str] = Header(default=None),
    qc_session: Optional[str] = Cookie(default=None),
    key: Optional[str] = Query(default=None),
) -> str:
    """Вимагає прав адміністратора (для керування торгами, перезапуску та картриджів)."""
    role = await verify_api_access(
        x_api_key=x_api_key,
        authorization=authorization,
        qc_session=qc_session,
        key=key,
    )
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Тільки перегляд (Read-Only): потрібні права адміністратора",
        )
    return "admin"