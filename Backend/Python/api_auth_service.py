"""
Camada de negócio para autenticação, autorização e gestão de convites.

Este módulo concentra:

- hashing de passwords (bcrypt via passlib);
- emissão/validação de tokens JWT (HS256 com `python-jose`);
- operações sobre utilizadores (registo de user, registo de especialista,
  listagem, aprovação e rejeição);
- gestão de convites para admins (criar, listar, consumir);
- persistência de credenciais (ficheiros carregados pelos especialistas);
- notificações persistidas em BD (usadas nos ecrãs de pending/rejected).

O `api_main.py` importa exclusivamente este módulo para toda a lógica auth.
A camada HTTP não deve conter regras de negócio.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from jose import JWTError, jwt
from passlib.context import CryptContext

from api_db import db_cursor


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")


JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_TTL_HOURS = int(os.getenv("JWT_TTL_HOURS", "12"))
INVITE_TTL_HOURS = int(os.getenv("INVITE_TTL_HOURS", "48"))

CREDENTIALS_UPLOAD_DIR = (
    _PROJECT_ROOT / os.getenv("CREDENTIALS_UPLOAD_DIR", "uploads/credentials")
).resolve()
CREDENTIALS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_CREDENTIAL_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_CREDENTIAL_BYTES = 10 * 1024 * 1024  # 10 MB


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Estruturas
# ---------------------------------------------------------------------------
@dataclass
class AuthUser:
    id: str
    email: str
    full_name: str
    role: str          # user | specialist | admin
    status: str        # active | pending | rejected
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
_PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


def validate_password_strength(password: str) -> None:
    """Mínimo 8 caracteres com pelo menos uma letra e um dígito."""
    if not _PASSWORD_RE.match(password or ""):
        raise ValueError(
            "A password tem de ter pelo menos 8 caracteres, incluindo letras e números."
        )


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def issue_token(user: "AuthUser") -> Tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS)
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "exp": expires_at,
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Token inválido: {exc}") from exc


# ---------------------------------------------------------------------------
# Mapeamento de linhas → AuthUser
# ---------------------------------------------------------------------------
_USER_COLUMNS = "id, email, password_hash, full_name, role, status, created_at, updated_at"


def _row_to_user(row) -> AuthUser:
    return AuthUser(
        id=str(row[0]),
        email=row[1],
        full_name=row[3],
        role=row[4],
        status=row[5],
        created_at=row[6],
        updated_at=row[7],
    )


def get_user_by_email(email: str) -> Optional[Tuple[AuthUser, str]]:
    """Devolve (AuthUser, password_hash) ou None se não existir."""
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {_USER_COLUMNS} FROM dbo.auth_users WHERE email = ?",
            email.strip().lower(),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _row_to_user(row), row[2]


def get_user_by_id(user_id: str) -> Optional[AuthUser]:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {_USER_COLUMNS} FROM dbo.auth_users WHERE id = ?",
            user_id,
        )
        row = cur.fetchone()
        return _row_to_user(row) if row else None


# ---------------------------------------------------------------------------
# Registo
# ---------------------------------------------------------------------------
def register_user(email: str, password: str, full_name: str) -> AuthUser:
    """Registo público de um utilizador normal (role=user, status=active)."""
    _validate_registration_payload(email, password, full_name)

    email_norm = email.strip().lower()
    password_hash = hash_password(password)

    with db_cursor(commit=True) as cur:
        if _email_exists(cur, email_norm):
            raise ValueError("Já existe uma conta com este email.")

        cur.execute(
            """
            INSERT INTO dbo.auth_users (email, password_hash, full_name, role, status)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, 'user', 'active')
            """,
            email_norm,
            password_hash,
            full_name.strip(),
        )
        user_id = str(cur.fetchone()[0])

    user = get_user_by_id(user_id)
    assert user is not None
    return user


def register_specialist(
    email: str,
    password: str,
    full_name: str,
    specialty: Optional[str] = None,
    institution: Optional[str] = None,
    country: Optional[str] = None,
) -> AuthUser:
    """Registo de especialista — conta criada em estado `pending`.

    Os campos `specialty`, `institution` e `country` foram tornados opcionais
    quando a narrativa do especialista mudou de "profissional médico de uma
    instituição clínica" para "engenheiro regulatório / consultor MDR-AI Act".
    Mantidos no schema da DB por retrocompatibilidade (e para informação
    extra opcional), mas podem vir vazios.
    """
    _validate_registration_payload(email, password, full_name)

    email_norm = email.strip().lower()
    password_hash = hash_password(password)

    with db_cursor(commit=True) as cur:
        if _email_exists(cur, email_norm):
            raise ValueError("Já existe uma conta com este email.")

        cur.execute(
            """
            INSERT INTO dbo.auth_users (email, password_hash, full_name, role, status)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, 'specialist', 'pending')
            """,
            email_norm,
            password_hash,
            full_name.strip(),
        )
        user_id = str(cur.fetchone()[0])

        cur.execute(
            """
            INSERT INTO dbo.specialist_profiles (user_id, specialty, institution, country)
            VALUES (?, ?, ?, ?)
            """,
            user_id,
            (specialty or "").strip() or None,
            (institution or "").strip() or None,
            (country or "").strip() or None,
        )

    user = get_user_by_id(user_id)
    assert user is not None
    return user


def _validate_registration_payload(email: str, password: str, full_name: str) -> None:
    if not email or "@" not in email:
        raise ValueError("Email inválido.")
    if not full_name or not full_name.strip():
        raise ValueError("O nome completo é obrigatório.")
    validate_password_strength(password)


def _email_exists(cur, email_norm: str) -> bool:
    cur.execute("SELECT 1 FROM dbo.auth_users WHERE email = ?", email_norm)
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Credenciais (ficheiros de especialistas)
# ---------------------------------------------------------------------------
def store_credential(
    user_id: str,
    original_filename: str,
    content: bytes,
    mime_type: str,
    submission_round: int = 1,
) -> Dict[str, Any]:
    """Grava o ficheiro em disco + metadados na BD."""
    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_CREDENTIAL_EXTENSIONS:
        raise ValueError(
            f"Extensão '{ext or '?'}' não permitida. Aceites: "
            + ", ".join(sorted(ALLOWED_CREDENTIAL_EXTENSIONS))
        )
    if len(content) > MAX_CREDENTIAL_BYTES:
        raise ValueError("O ficheiro excede o limite de 10 MB.")
    if not content:
        raise ValueError("O ficheiro está vazio.")

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_filename).name).strip("_") or "credential"
    filename = f"cred_{user_id}_r{submission_round}_{uuid.uuid4().hex[:8]}_{safe_name}"
    target_path = CREDENTIALS_UPLOAD_DIR / filename
    target_path.write_bytes(content)

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dbo.specialist_credentials
                (user_id, file_path, original_filename, mime_type, size_bytes, submission_round)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            user_id,
            str(target_path),
            original_filename[:255],
            (mime_type or "application/octet-stream")[:100],
            len(content),
            submission_round,
        )
        cred_id = str(cur.fetchone()[0])

    return {
        "id": cred_id,
        "file_path": str(target_path),
        "original_filename": original_filename,
        "mime_type": mime_type,
        "size_bytes": len(content),
        "submission_round": submission_round,
    }


def list_credentials(user_id: str) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, file_path, original_filename, mime_type, size_bytes,
                   submission_round, uploaded_at
              FROM dbo.specialist_credentials
             WHERE user_id = ?
          ORDER BY submission_round DESC, uploaded_at DESC
            """,
            user_id,
        )
        rows = cur.fetchall()

    return [
        {
            "id": str(r[0]),
            "file_path": r[1],
            "original_filename": r[2],
            "mime_type": r[3],
            "size_bytes": r[4],
            "submission_round": r[5],
            "uploaded_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


def latest_submission_round(user_id: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            "SELECT ISNULL(MAX(submission_round), 0) FROM dbo.specialist_credentials WHERE user_id = ?",
            user_id,
        )
        return int(cur.fetchone()[0] or 0)


def get_credential_file(cred_id: str) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, file_path, original_filename, mime_type
              FROM dbo.specialist_credentials
             WHERE id = ?
            """,
            cred_id,
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "user_id": str(row[1]),
        "file_path": row[2],
        "original_filename": row[3],
        "mime_type": row[4],
    }


# ---------------------------------------------------------------------------
# Perfil do especialista
# ---------------------------------------------------------------------------
def get_specialist_profile(user_id: str) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT user_id, specialty, institution, country,
                   rejection_reason, reviewed_at, reviewed_by
              FROM dbo.specialist_profiles
             WHERE user_id = ?
            """,
            user_id,
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "user_id": str(row[0]),
        "specialty": row[1],
        "institution": row[2],
        "country": row[3],
        "rejection_reason": row[4],
        "reviewed_at": row[5].isoformat() if row[5] else None,
        "reviewed_by": str(row[6]) if row[6] else None,
    }


def update_specialist_profile(
    user_id: str,
    specialty: Optional[str] = None,
    institution: Optional[str] = None,
    country: Optional[str] = None,
) -> None:
    updates = []
    values: List[Any] = []
    if specialty is not None and specialty.strip():
        updates.append("specialty = ?")
        values.append(specialty.strip())
    if institution is not None and institution.strip():
        updates.append("institution = ?")
        values.append(institution.strip())
    if country is not None and country.strip():
        updates.append("country = ?")
        values.append(country.strip())
    if not updates:
        return
    values.append(user_id)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE dbo.specialist_profiles SET {', '.join(updates)} WHERE user_id = ?",
            *values,
        )


# ---------------------------------------------------------------------------
# Aprovação / rejeição de especialistas
# ---------------------------------------------------------------------------
def approve_specialist(user_id: str, reviewer_id: str) -> None:
    now = datetime.now(timezone.utc)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE dbo.auth_users SET status = 'active', updated_at = ? WHERE id = ? AND role = 'specialist'",
            now,
            user_id,
        )
        cur.execute(
            """
            UPDATE dbo.specialist_profiles
               SET rejection_reason = NULL,
                   reviewed_at = ?,
                   reviewed_by = ?
             WHERE user_id = ?
            """,
            now,
            reviewer_id,
            user_id,
        )
    _create_notification(
        user_id=user_id,
        kind="specialist_approved",
        title="A tua conta de especialista foi aprovada.",
        body="Já podes fazer login e aceder à área do especialista.",
    )


def reject_specialist(user_id: str, reviewer_id: str, reason: str) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("É obrigatório indicar a razão da rejeição.")

    now = datetime.now(timezone.utc)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE dbo.auth_users SET status = 'rejected', updated_at = ? WHERE id = ? AND role = 'specialist'",
            now,
            user_id,
        )
        cur.execute(
            """
            UPDATE dbo.specialist_profiles
               SET rejection_reason = ?,
                   reviewed_at = ?,
                   reviewed_by = ?
             WHERE user_id = ?
            """,
            reason,
            now,
            reviewer_id,
            user_id,
        )
    _create_notification(
        user_id=user_id,
        kind="specialist_rejected",
        title="A submissão da tua conta de especialista foi rejeitada.",
        body=reason,
    )


def resubmit_specialist(user_id: str) -> None:
    """Volta a colocar o especialista em `pending` após nova submissão."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE dbo.auth_users SET status = 'pending', updated_at = SYSUTCDATETIME() WHERE id = ? AND role = 'specialist'",
            user_id,
        )
        cur.execute(
            """
            UPDATE dbo.specialist_profiles
               SET rejection_reason = NULL,
                   reviewed_at = NULL,
                   reviewed_by = NULL
             WHERE user_id = ?
            """,
            user_id,
        )


# ---------------------------------------------------------------------------
# Listagem de utilizadores (admin)
# ---------------------------------------------------------------------------
def list_users(
    role: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    where = []
    values: List[Any] = []
    if role:
        where.append("role = ?")
        values.append(role)
    if status:
        where.append("status = ?")
        values.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, email, full_name, role, status, created_at, updated_at
              FROM dbo.auth_users
              {clause}
          ORDER BY created_at DESC
            """,
            *values,
        )
        rows = cur.fetchall()

    return [
        {
            "id": str(r[0]),
            "email": r[1],
            "full_name": r[2],
            "role": r[3],
            "status": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
            "updated_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


def list_specialist_queue() -> List[Dict[str, Any]]:
    """Lista especialistas em `pending` com perfil + credenciais mais recentes."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT u.id, u.email, u.full_name, u.status, u.created_at,
                   p.specialty, p.institution, p.country, p.rejection_reason
              FROM dbo.auth_users u
              JOIN dbo.specialist_profiles p ON p.user_id = u.id
             WHERE u.role = 'specialist' AND u.status IN ('pending','rejected')
          ORDER BY u.created_at ASC
            """
        )
        users = cur.fetchall()

    result = []
    for u in users:
        user_id = str(u[0])
        creds = list_credentials(user_id)
        result.append({
            "id": user_id,
            "email": u[1],
            "full_name": u[2],
            "status": u[3],
            "created_at": u[4].isoformat() if u[4] else None,
            "specialty": u[5],
            "institution": u[6],
            "country": u[7],
            "rejection_reason": u[8],
            "credentials": creds,
        })
    return result


# ---------------------------------------------------------------------------
# Convites de admin
# ---------------------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_admin_invite(created_by: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Cria um convite único. Devolve o token em claro **uma única vez**."""
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dbo.admin_invites (token_hash, created_by, expires_at, note)
            OUTPUT INSERTED.id, INSERTED.created_at
            VALUES (?, ?, ?, ?)
            """,
            token_hash,
            created_by,
            expires_at,
            (note or None),
        )
        row = cur.fetchone()

    return {
        "id": str(row[0]),
        "token": token,  # devolvido só aqui
        "expires_at": expires_at.isoformat(),
        "created_at": row[1].isoformat() if row[1] else None,
        "note": note,
    }


def list_admin_invites() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT i.id, i.created_at, i.expires_at, i.used_at, i.used_by, i.note,
                   creator.email, used.email
              FROM dbo.admin_invites i
              JOIN dbo.auth_users creator ON creator.id = i.created_by
         LEFT JOIN dbo.auth_users used ON used.id = i.used_by
          ORDER BY i.created_at DESC
            """
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        expires_at = r[2]
        used_at = r[3]
        if used_at is not None:
            state = "used"
        elif expires_at and expires_at.replace(tzinfo=timezone.utc) < now:
            state = "expired"
        else:
            state = "pending"
        out.append({
            "id": str(r[0]),
            "created_at": r[1].isoformat() if r[1] else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "used_at": used_at.isoformat() if used_at else None,
            "used_by_email": r[7],
            "created_by_email": r[6],
            "note": r[5],
            "state": state,
        })
    return out


def consume_admin_invite(
    token: str,
    email: str,
    password: str,
    full_name: str,
) -> AuthUser:
    """
    Verifica o token, cria o admin com role=admin/status=active e marca o convite como usado.

    Lança `ValueError` com mensagem clara se o token for inválido, expirado ou já usado.
    """
    _validate_registration_payload(email, password, full_name)

    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc)

    with db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT id, expires_at, used_at FROM dbo.admin_invites WHERE token_hash = ?",
            token_hash,
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("Convite inválido.")
        invite_id, expires_at, used_at = row

        if used_at is not None:
            raise ValueError("Este convite já foi utilizado.")
        expires_utc = expires_at.replace(tzinfo=timezone.utc) if expires_at and expires_at.tzinfo is None else expires_at
        if expires_utc and expires_utc < now:
            raise ValueError("Este convite expirou.")

        email_norm = email.strip().lower()
        if _email_exists(cur, email_norm):
            raise ValueError("Já existe uma conta com este email.")

        password_hash = hash_password(password)
        cur.execute(
            """
            INSERT INTO dbo.auth_users (email, password_hash, full_name, role, status)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, 'admin', 'active')
            """,
            email_norm,
            password_hash,
            full_name.strip(),
        )
        user_id = str(cur.fetchone()[0])

        cur.execute(
            """
            UPDATE dbo.admin_invites
               SET used_at = ?, used_by = ?
             WHERE id = ?
            """,
            now,
            user_id,
            invite_id,
        )

    user = get_user_by_id(user_id)
    assert user is not None
    return user


# ---------------------------------------------------------------------------
# Notificações
# ---------------------------------------------------------------------------
def _create_notification(user_id: str, kind: str, title: str, body: Optional[str]) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dbo.user_notifications (user_id, kind, title, body)
            VALUES (?, ?, ?, ?)
            """,
            user_id,
            kind,
            title,
            body,
        )


def list_notifications(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT TOP (?) id, kind, title, body, created_at, read_at
              FROM dbo.user_notifications
             WHERE user_id = ?
          ORDER BY created_at DESC
            """,
            limit,
            user_id,
        )
        rows = cur.fetchall()
    return [
        {
            "id": str(r[0]),
            "kind": r[1],
            "title": r[2],
            "body": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
            "read_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Login (retorna user + token + notifications + profile)
# ---------------------------------------------------------------------------
def authenticate(email: str, password: str) -> Tuple[AuthUser, str, datetime]:
    """Valida credenciais e emite token. Não bloqueia aqui por status — a decisão fica no endpoint."""
    found = get_user_by_email(email)
    if not found:
        raise ValueError("Email ou password incorretos.")
    user, password_hash = found
    if not verify_password(password, password_hash):
        raise ValueError("Email ou password incorretos.")
    token, expires_at = issue_token(user)
    return user, token, expires_at
