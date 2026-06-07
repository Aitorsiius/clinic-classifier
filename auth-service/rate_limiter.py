"""
Rate limiter y gestión de bloqueos de inicio de sesión.

Implementa una política de seguridad contra ataques de fuerza bruta sobre el
endpoint de login:

- Si un usuario falla el inicio de sesión ``MAX_FAILED_ATTEMPTS`` veces dentro
  de una ventana de ``ATTEMPT_WINDOW_SECONDS`` segundos, la cuenta queda
  bloqueada. El bloqueo persiste hasta que un administrador lo revisa y
  desbloquea manualmente al usuario.

El bloqueo se aplica **por cuenta** y se registra además la IP del equipo desde
el que se produjeron los intentos. Se opta por bloqueo por cuenta —en lugar de un
baneo estricto por IP en el propio login— para no dejar fuera al administrador ni
a otros usuarios legítimos que compartan IP (NAT, mismo equipo, red interna de
Docker), evitando un bloqueo en cascada que impediría incluso desbloquear. La IP
queda guardada y se muestra al administrador como contexto forense del ataque.

La cuenta se identifica **siempre por su ``user_id``** (el ``_id`` opaco de
MongoDB), nunca por el ``username``. Así, mirando directamente la base de datos
no es posible saber a simple vista a qué usuario corresponde un intento o un
bloqueo (no se filtra el nombre de usuario); la traducción ``username`` ⇆
``user_id`` se hace en el ``auth-service``, de forma transparente para la
aplicación.

La lógica se centraliza aquí (y no en el API Gateway) porque requiere acceso a
MongoDB para persistir los intentos y los bloqueos, y porque la gestión de
usuarios (panel de administración) vive en este mismo servicio.

Colecciones en MongoDB:
- ``login_attempts``: un documento por cada intento de login fallido
  (``user_id``, ``ip_address``, ``user_agent``, ``timestamp``).
- ``login_blocks``: un documento por cada bloqueo producido
  (``user_id``, ``ip_address``, ``reason``, ``blocked_at``, ``active``,
  ``unblocked_at``, ``unblocked_by``). El historial completo permite saber
  cuántas veces ha sido bloqueado un mismo usuario.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURACIÓN (parametrizable por entorno)
# ==========================================
# Número de intentos fallidos permitidos dentro de la ventana antes de bloquear.
MAX_FAILED_ATTEMPTS = int(os.getenv("LOGIN_MAX_FAILED_ATTEMPTS", "5"))
# Ventana temporal (en segundos) en la que se contabilizan los intentos fallidos.
ATTEMPT_WINDOW_SECONDS = int(os.getenv("LOGIN_ATTEMPT_WINDOW_SECONDS", "60"))
# Motivo de bloqueo registrado (permite distinguir/contar bloqueos por la misma razón).
BLOCK_REASON_BRUTE_FORCE = "too_many_failed_login_attempts"
# Máximo de intentos fallidos que se devuelven en la información de bloqueo.
MAX_ATTEMPTS_RETURNED = 100


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    """Convierte un datetime a ISO 8601 de forma segura."""
    if not value:
        return None
    # Mongo devuelve datetimes "naive" en UTC; los marcamos como tales.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class LoginRateLimiter:
    """Gestiona los intentos fallidos y los bloqueos de inicio de sesión."""

    def __init__(self, db):
        """Inicializa el limitador con la base de datos de MongoDB.

        Args:
            db: Instancia de base de datos de ``pymongo`` (``clinic-classifier``).
        """
        self._attempts = db["login_attempts"]
        self._blocks = db["login_blocks"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Crea los índices necesarios (idempotente)."""
        try:
            self._attempts.create_index("user_id")
            self._attempts.create_index("ip_address")
            self._attempts.create_index([("timestamp", -1)])
            self._blocks.create_index("user_id")
            self._blocks.create_index("ip_address")
            self._blocks.create_index("active")
            self._blocks.create_index([("blocked_at", -1)])
        except Exception:
            logger.exception("No se pudieron crear los índices del rate limiter")

    # ==========================================
    # CONSULTAS DE ESTADO
    # ==========================================
    def get_active_block(
        self,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[dict]:
        """Devuelve el bloqueo activo que afecte al usuario o a la IP, si existe.

        El usuario se identifica por su ``user_id`` (opaco), nunca por su nombre.
        """
        conditions = []
        if user_id:
            conditions.append({"user_id": user_id})
        if ip_address:
            conditions.append({"ip_address": ip_address})
        if not conditions:
            return None
        try:
            return self._blocks.find_one({"active": True, "$or": conditions})
        except Exception:
            logger.exception("Error al consultar el bloqueo activo")
            return None

    def is_blocked(
        self,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """Indica si el usuario o la IP están bloqueados actualmente."""
        return self.get_active_block(user_id=user_id, ip_address=ip_address) is not None

    def get_blocked_user_ids(self) -> set:
        """Devuelve el conjunto de ``user_id`` con un bloqueo activo."""
        try:
            cursor = self._blocks.find({"active": True}, {"user_id": 1})
            return {doc["user_id"] for doc in cursor if doc.get("user_id")}
        except Exception:
            logger.exception("Error al obtener los usuarios bloqueados")
            return set()

    # ==========================================
    # REGISTRO DE INTENTOS
    # ==========================================
    def record_failed_attempt(
        self,
        user_id: str,
        ip_address: str,
        user_agent: Optional[str] = None,
    ) -> dict:
        """Registra un intento fallido y bloquea si se supera el umbral.

        Args:
            user_id: Identificador opaco (``_id``) del usuario afectado.
            ip_address: IP del equipo desde el que se realizó el intento.
            user_agent: User-Agent del cliente (opcional, para trazabilidad).

        Returns:
            Diccionario con:
            - ``blocked`` (bool): si el usuario ha quedado bloqueado.
            - ``remaining`` (int): intentos restantes antes del bloqueo.
            - ``block`` (dict | None): documento del bloqueo si se ha creado.
        """
        now = datetime.now(timezone.utc)
        try:
            self._attempts.insert_one(
                {
                    "user_id": user_id,
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                    "timestamp": now,
                }
            )
        except Exception:
            logger.exception("Error al registrar el intento fallido de '%s'", user_id)

        # Si ya está bloqueado, no recalculamos.
        existing = self.get_active_block(user_id=user_id)
        if existing:
            return {"blocked": True, "remaining": 0, "block": existing}

        window_start = now - timedelta(seconds=ATTEMPT_WINDOW_SECONDS)
        try:
            recent = self._attempts.count_documents(
                {"user_id": user_id, "timestamp": {"$gte": window_start}}
            )
        except Exception:
            logger.exception("Error al contar intentos recientes de '%s'", user_id)
            recent = 0

        if recent >= MAX_FAILED_ATTEMPTS:
            block = self._create_block(user_id, ip_address, now)
            return {"blocked": True, "remaining": 0, "block": block}

        return {
            "blocked": False,
            "remaining": max(0, MAX_FAILED_ATTEMPTS - recent),
            "block": None,
        }

    def _create_block(self, user_id: str, ip_address: str, now: datetime) -> dict:
        """Crea un documento de bloqueo activo para el usuario/IP."""
        doc = {
            "user_id": user_id,
            "ip_address": ip_address,
            "reason": BLOCK_REASON_BRUTE_FORCE,
            "blocked_at": now,
            "active": True,
            "unblocked_at": None,
            "unblocked_by": None,
        }
        try:
            result = self._blocks.insert_one(doc)
            doc["_id"] = result.inserted_id
            logger.warning(
                "Usuario '%s' bloqueado por exceso de intentos fallidos desde la IP %s",
                user_id,
                ip_address,
            )
        except Exception:
            logger.exception("Error al crear el bloqueo de '%s'", user_id)
        return doc

    def reset_on_success(self, user_id: str) -> None:
        """Limpia los intentos fallidos tras un inicio de sesión correcto."""
        self._clear_attempts(user_id)

    def _clear_attempts(self, user_id: str) -> None:
        """Elimina los intentos fallidos registrados para un usuario."""
        try:
            self._attempts.delete_many({"user_id": user_id})
        except Exception:
            logger.exception("Error al limpiar los intentos de '%s'", user_id)

    # ==========================================
    # ACCIONES DE ADMINISTRACIÓN
    # ==========================================
    def unblock(self, user_id: str, admin_user_id: Optional[str] = None) -> bool:
        """Desactiva los bloqueos activos del usuario y reinicia su contador.

        Args:
            user_id: Identificador opaco (``_id``) del usuario a desbloquear.
            admin_user_id: ``user_id`` del administrador que desbloquea
                (trazabilidad; tampoco se almacena el nombre de usuario).

        Returns:
            True si se desactivó al menos un bloqueo activo.
        """
        now = datetime.now(timezone.utc)
        try:
            result = self._blocks.update_many(
                {"user_id": user_id, "active": True},
                {
                    "$set": {
                        "active": False,
                        "unblocked_at": now,
                        "unblocked_by": admin_user_id,
                    }
                },
            )
        except Exception:
            logger.exception("Error al desbloquear a '%s'", user_id)
            return False

        # Reiniciar el contador para que el usuario pueda volver a iniciar sesión.
        self._clear_attempts(user_id)
        return result.modified_count > 0

    def get_block_info(self, user_id: str) -> dict:
        """Devuelve la información de bloqueo de un usuario para el panel admin.

        Incluye los intentos de inicio de sesión fallidos con sus fechas, el
        número de veces que el usuario ha sido bloqueado por el mismo motivo y
        los datos del bloqueo activo (si lo hay). El usuario se identifica por su
        ``user_id``; el ``auth-service`` añade el ``username`` a la respuesta.
        """
        # Intentos fallidos (con fechas e IP), de más reciente a más antiguo.
        failed_attempts = []
        try:
            cursor = (
                self._attempts.find({"user_id": user_id})
                .sort("timestamp", -1)
                .limit(MAX_ATTEMPTS_RETURNED)
            )
            failed_attempts = [
                {
                    "ip_address": attempt.get("ip_address"),
                    "user_agent": attempt.get("user_agent"),
                    "timestamp": _to_iso(attempt.get("timestamp")),
                }
                for attempt in cursor
            ]
        except Exception:
            logger.exception("Error al obtener los intentos de '%s'", user_id)

        # Número de veces que el usuario ha sido bloqueado (historial completo).
        try:
            block_count = self._blocks.count_documents(
                {"user_id": user_id, "reason": BLOCK_REASON_BRUTE_FORCE}
            )
        except Exception:
            logger.exception("Error al contar los bloqueos de '%s'", user_id)
            block_count = 0

        active_block = self.get_active_block(user_id=user_id)
        current_block = None
        if active_block:
            current_block = {
                "ip_address": active_block.get("ip_address"),
                "blocked_at": _to_iso(active_block.get("blocked_at")),
                "reason": active_block.get("reason"),
            }

        return {
            "blocked": active_block is not None,
            "block_count": block_count,
            "failed_attempts": failed_attempts,
            "current_block": current_block,
        }

    def delete_user_records(self, user_id: str) -> bool:
        """Elimina todos los registros de intentos y bloqueos de un usuario.

        Se llama cuando se elimina una cuenta de usuario para evitar dejar
        referencias huérfanas en la base de datos.

        Args:
            user_id: Identificador opaco (``_id``) del usuario.

        Returns:
            True si se eliminaron registros (al menos uno).
        """
        try:
            attempts_deleted = self._attempts.delete_many({"user_id": user_id}).deleted_count
            blocks_deleted = self._blocks.delete_many({"user_id": user_id}).deleted_count
            deleted_count = attempts_deleted + blocks_deleted
            if deleted_count > 0:
                logger.info(
                    "Eliminados %d registros de rate-limit para user_id '%s' (intentos: %d, bloqueos: %d)",
                    deleted_count,
                    user_id,
                    attempts_deleted,
                    blocks_deleted,
                )
            return deleted_count > 0
        except Exception:
            logger.exception("Error al eliminar registros de rate-limit para '%s'", user_id)
            return False
