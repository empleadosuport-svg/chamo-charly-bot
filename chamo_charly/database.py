"""Persistence layer supporting both SQLite and PostgreSQL (Supabase)."""

from __future__ import annotations

import os
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Any

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS sorteos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_sorteo TEXT NOT NULL,
    hora_sorteo TEXT NOT NULL,
    codigo TEXT NOT NULL,
    animal TEXT NOT NULL,
    dia_semana TEXT NOT NULL,
    fuente TEXT NOT NULL DEFAULT 'panel',
    capturado_en TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'confirmado',
    UNIQUE(fecha_sorteo, hora_sorteo)
);

CREATE TABLE IF NOT EXISTS predicciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creada_en TEXT NOT NULL,
    objetivo_fecha TEXT NOT NULL,
    objetivo_hora TEXT NOT NULL,
    modelo TEXT NOT NULL,
    observaciones INTEGER NOT NULL,
    top10_json TEXT NOT NULL,
    ranking_completo TEXT NOT NULL DEFAULT '[]',
    probabilidades_json TEXT NOT NULL,
    probabilidad_conjunto REAL NOT NULL,
    explicacion_json TEXT NOT NULL,
    resultado_codigo TEXT,
    resultado_animal TEXT,
    acierto INTEGER,
    posicion_ganador INTEGER,
    franja TEXT,
    pilares_influyentes TEXT,
    verificada_en TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    primera_creada_en TEXT,
    resultado_capturado_en TEXT,
    fuente_resultado TEXT,
    correccion_motivo TEXT,
    UNIQUE(objetivo_fecha, objetivo_hora)
);

CREATE TABLE IF NOT EXISTS auditoria_correcciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tabla TEXT NOT NULL,
    registro_id INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    datos_anteriores TEXT NOT NULL,
    datos_nuevos TEXT NOT NULL,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pesos_pilares_contexto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pilar TEXT NOT NULL,
    hora INTEGER NOT NULL,
    dia_semana INTEGER NOT NULL,
    peso REAL NOT NULL DEFAULT 1.0,
    ultima_actualizacion TEXT NOT NULL,
    total_verificaciones INTEGER NOT NULL DEFAULT 0,
    UNIQUE(pilar, hora, dia_semana)
);

CREATE TABLE IF NOT EXISTS pruebas_historicas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    configuracion TEXT NOT NULL DEFAULT '{}',
    modelo TEXT NOT NULL,
    particion TEXT NOT NULL DEFAULT '60/20/20',
    rango_dias INTEGER NOT NULL DEFAULT 0,
    posicion_promedio REAL NOT NULL DEFAULT 0.0,
    top5 INTEGER NOT NULL DEFAULT 0,
    top10 INTEGER NOT NULL DEFAULT 0,
    top20 INTEGER NOT NULL DEFAULT 0,
    sorteos_entrenamiento INTEGER NOT NULL DEFAULT 0,
    sorteos_validacion INTEGER NOT NULL DEFAULT 0,
    sorteos_prueba INTEGER NOT NULL DEFAULT 0,
    fecha_ejecucion TEXT NOT NULL,
    duracion_segundos REAL NOT NULL DEFAULT 0.0
);
"""

SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS sorteos (
    id SERIAL PRIMARY KEY,
    fecha_sorteo VARCHAR(10) NOT NULL,
    hora_sorteo VARCHAR(10) NOT NULL,
    codigo VARCHAR(10) NOT NULL,
    animal VARCHAR(50) NOT NULL,
    dia_semana VARCHAR(20) NOT NULL,
    fuente VARCHAR(50) NOT NULL DEFAULT 'panel',
    capturado_en VARCHAR(50) NOT NULL,
    estado VARCHAR(50) NOT NULL DEFAULT 'confirmado',
    UNIQUE(fecha_sorteo, hora_sorteo)
);

CREATE TABLE IF NOT EXISTS predicciones (
    id SERIAL PRIMARY KEY,
    creada_en VARCHAR(50) NOT NULL,
    objetivo_fecha VARCHAR(10) NOT NULL,
    objetivo_hora VARCHAR(10) NOT NULL,
    modelo VARCHAR(50) NOT NULL,
    observaciones INTEGER NOT NULL,
    top10_json TEXT NOT NULL,
    ranking_completo TEXT NOT NULL DEFAULT '[]',
    probabilidades_json TEXT NOT NULL,
    probabilidad_conjunto DOUBLE PRECISION NOT NULL,
    explicacion_json TEXT NOT NULL,
    resultado_codigo VARCHAR(10),
    resultado_animal VARCHAR(50),
    acierto INTEGER,
    posicion_ganador INTEGER,
    franja VARCHAR(50),
    pilares_influyentes TEXT,
    verificada_en VARCHAR(50),
    estado VARCHAR(50) NOT NULL DEFAULT 'pendiente',
    primera_creada_en VARCHAR(50),
    resultado_capturado_en VARCHAR(50),
    fuente_resultado VARCHAR(50),
    correccion_motivo TEXT,
    UNIQUE(objetivo_fecha, objetivo_hora)
);

CREATE TABLE IF NOT EXISTS auditoria_correcciones (
    id SERIAL PRIMARY KEY,
    tabla VARCHAR(50) NOT NULL,
    registro_id INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    datos_anteriores TEXT NOT NULL,
    datos_nuevos TEXT NOT NULL,
    creado_en VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS pesos_pilares_contexto (
    id SERIAL PRIMARY KEY,
    pilar VARCHAR(50) NOT NULL,
    hora INTEGER NOT NULL,
    dia_semana INTEGER NOT NULL,
    peso DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    ultima_actualizacion VARCHAR(50) NOT NULL,
    total_verificaciones INTEGER NOT NULL DEFAULT 0,
    UNIQUE(pilar, hora, dia_semana)
);

CREATE TABLE IF NOT EXISTS pesos (
    pilar VARCHAR(50) PRIMARY KEY,
    peso DOUBLE PRECISION NOT NULL,
    actualizaciones INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pruebas_historicas (
    id SERIAL PRIMARY KEY,
    configuracion TEXT NOT NULL DEFAULT '{}',
    modelo VARCHAR(50) NOT NULL,
    particion VARCHAR(50) NOT NULL DEFAULT '60/20/20',
    rango_dias INTEGER NOT NULL DEFAULT 0,
    posicion_promedio DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    top5 INTEGER NOT NULL DEFAULT 0,
    top10 INTEGER NOT NULL DEFAULT 0,
    top20 INTEGER NOT NULL DEFAULT 0,
    sorteos_entrenamiento INTEGER NOT NULL DEFAULT 0,
    sorteos_validacion INTEGER NOT NULL DEFAULT 0,
    sorteos_prueba INTEGER NOT NULL DEFAULT 0,
    fecha_ejecucion VARCHAR(50) NOT NULL,
    duracion_segundos DOUBLE PRECISION NOT NULL DEFAULT 0.0
);
"""

PILLARS = ("base", "hora", "dia_hora", "markov", "reciente", "penalizacion", "piramide")
BASE_WEIGHTS = {
    "base": 0.18,
    "hora": 0.32,
    "dia_hora": 0.22,
    "markov": 0.16,
    "reciente": 0.10,
    "penalizacion": 0.02,
    "piramide": 0.03,
}

def get_database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL")

class UnifiedCursor:
    def __init__(self, cursor: Any, is_pg: bool):
        self._cursor = cursor
        self.is_pg = is_pg
        self.lastrowid = getattr(cursor, "lastrowid", None)

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def _convert_sql(self, sql: str) -> str:
        if not self.is_pg:
            return sql
        # Convert SQLite ? placeholders to PostgreSQL %s
        sql = sql.replace("?", "%s")
        # Convert INSERT OR IGNORE INTO to INSERT INTO ... ON CONFLICT DO NOTHING
        if "INSERT OR IGNORE INTO sorteos" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO sorteos", "INSERT INTO sorteos")
            sql += " ON CONFLICT (fecha_sorteo, hora_sorteo) DO NOTHING"
        elif "INSERT OR IGNORE INTO predicciones" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO predicciones", "INSERT INTO predicciones")
            sql += " ON CONFLICT (objetivo_fecha, objetivo_hora) DO NOTHING"
        elif "INSERT OR IGNORE INTO pesos_pilares_contexto" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO pesos_pilares_contexto", "INSERT INTO pesos_pilares_contexto")
            sql += " ON CONFLICT (pilar, hora, dia_semana) DO NOTHING"
        elif "INSERT OR IGNORE INTO" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            sql += " ON CONFLICT DO NOTHING"
        return sql

    def execute(self, sql: str, params: tuple | list | None = None) -> UnifiedCursor:
        sql = self._convert_sql(sql)
        if params is None:
            self._cursor.execute(sql)
        else:
            self._cursor.execute(sql, params)
        if self.is_pg:
            self.lastrowid = getattr(self._cursor, "lastrowid", None)
        return self

    def executemany(self, sql: str, params_seq: Iterable[tuple | list]) -> UnifiedCursor:
        sql = self._convert_sql(sql)
        if self.is_pg:
            psycopg2.extras.execute_batch(self._cursor, sql, list(params_seq))
        else:
            self._cursor.executemany(sql, params_seq)
        return self

    def executescript(self, sql: str) -> UnifiedCursor:
        if self.is_pg:
            self._cursor.execute(sql)
        else:
            self._cursor.executescript(sql)
        return self

    def fetchone(self) -> dict | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self) -> list[dict]:
        rows = self._cursor.fetchall()
        return [dict(r) for r in rows]

class UnifiedConnection:
    def __init__(self, conn: Any, is_pg: bool):
        self._conn = conn
        self.is_pg = is_pg

    @property
    def total_changes(self) -> int:
        if self.is_pg:
            return 0
        return self._conn.total_changes

    def cursor(self) -> UnifiedCursor:
        if self.is_pg:
            return UnifiedCursor(self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor), is_pg=True)
        else:
            c = self._conn.cursor()
            return UnifiedCursor(c, is_pg=False)

    def execute(self, sql: str, params: tuple | list | None = None) -> UnifiedCursor:
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def executemany(self, sql: str, params_seq: Iterable[tuple | list]) -> UnifiedCursor:
        cursor = self.cursor()
        cursor.executemany(sql, params_seq)
        return cursor

    def executescript(self, sql: str) -> UnifiedCursor:
        cursor = self.cursor()
        cursor.executescript(sql)
        return cursor

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> UnifiedConnection:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._conn.rollback()
        else:
            self.commit()
        self.close()

def connect(database_path: str | Path = "data/chamo_charly.db") -> UnifiedConnection:
    db_url = get_database_url()
    if db_url and HAS_PSYCOPG2:
        pg_conn = psycopg2.connect(db_url)
        return UnifiedConnection(pg_conn, is_pg=True)
    else:
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_conn = sqlite3.connect(path)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_conn.execute("PRAGMA foreign_keys = ON")
        return UnifiedConnection(sqlite_conn, is_pg=False)

def init_db(database_path: str | Path = "data/chamo_charly.db") -> None:
    db_url = get_database_url()
    with connect(database_path) as connection:
        if connection.is_pg:
            connection.executescript(SCHEMA_POSTGRES)
        else:
            connection.executescript(SCHEMA_SQLITE)

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        connection.executemany(
            """
            INSERT OR IGNORE INTO pesos_pilares_contexto
                (pilar, hora, dia_semana, peso, ultima_actualizacion, total_verificaciones)
            VALUES (?, -1, 0, 1.0, ?, 0)
            """,
            [(pillar, now) for pillar in PILLARS],
        )
        connection.executemany(
            """
            UPDATE pesos_pilares_contexto
            SET peso = ?
            WHERE pilar = ? AND hora = -1 AND dia_semana = 0 AND total_verificaciones = 0
            """,
            [(BASE_WEIGHTS[pillar], pillar) for pillar in PILLARS],
        )

def insert_draw(
    database_path: str | Path,
    draw_date: str,
    draw_time: str,
    code: str,
    animal: str,
    weekday: str,
    source: str = "panel",
    status: str = "confirmado",
) -> None:
    captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO sorteos
                (fecha_sorteo, hora_sorteo, codigo, animal, dia_semana, fuente, capturado_en, estado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (draw_date, draw_time, code, animal, weekday, source, captured_at, status),
        )

def recent_draws(database_path: str | Path, limit: int = 50) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, fecha_sorteo, hora_sorteo, codigo, animal, dia_semana, fuente, capturado_en, estado
            FROM sorteos
            WHERE estado = 'confirmado'
            ORDER BY fecha_sorteo DESC, hora_sorteo DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows

def chronological_draws(database_path: str | Path, limit: int = 1_000_000) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, fecha_sorteo, hora_sorteo, codigo, animal, dia_semana, fuente, capturado_en, estado
            FROM sorteos
            WHERE estado = 'confirmado'
            ORDER BY fecha_sorteo ASC, hora_sorteo ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows

def count_draws(database_path: str | Path) -> int:
    with connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS total FROM sorteos WHERE estado = 'confirmado'").fetchone()
    return int(row["total"]) if row and row["total"] is not None else 0

def frequency_by_animal(database_path: str) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT codigo, animal, COUNT(*) AS total
            FROM sorteos
            WHERE estado = 'confirmado'
            GROUP BY codigo, animal
            ORDER BY total DESC, animal ASC
            """
        ).fetchall()
    return rows

def save_prediction(database_path: str | Path, prediction: dict) -> int:
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO predicciones
                (creada_en, objetivo_fecha, objetivo_hora, modelo, observaciones,
                  top10_json, ranking_completo, probabilidades_json, probabilidad_conjunto,
                  explicacion_json, estado, primera_creada_en)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendiente', ?)
            """,
            (
                created_at,
                prediction["target_date"],
                prediction["target_time"],
                prediction["model"],
                prediction["observations"],
                json.dumps(prediction["top10"], ensure_ascii=False),
                json.dumps(prediction["ranking"], ensure_ascii=False),
                json.dumps(prediction["ranking"], ensure_ascii=False),
                sum(item["probabilidad"] for item in prediction["top10"]),
                json.dumps(prediction["explanation"], ensure_ascii=False),
                created_at,
            ),
        )
        row = connection.execute(
            "SELECT id FROM predicciones WHERE objetivo_fecha = ? AND objetivo_hora = ?",
            (prediction["target_date"], prediction["target_time"]),
        ).fetchone()
        if row is None:
            raise RuntimeError("No se pudo recuperar la predicción existente.")
        return int(row["id"])

def latest_prediction(database_path: str | Path) -> dict | None:
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM predicciones ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row

def prediction_by_id(database_path: str | Path, prediction_id: int) -> dict | None:
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM predicciones WHERE id = ?", (prediction_id,)
        ).fetchone()
    return row

def prediction_for_target(database_path: str | Path, target_date: str, target_time: str) -> dict | None:
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM predicciones WHERE objetivo_fecha = ? AND objetivo_hora = ?",
            (target_date, target_time),
        ).fetchone()
    return row

def draw_for_slot(database_path: str | Path, draw_date: str, draw_time: str) -> dict | None:
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM sorteos WHERE fecha_sorteo = ? AND hora_sorteo = ?",
            (draw_date, draw_time),
        ).fetchone()
    return row

def confirm_provisional_draw(
    database_path: str | Path,
    draw_date: str,
    draw_time: str,
    code: str,
    animal: str,
    reason: str,
) -> None:
    now = datetime.now().astimezone()
    target = datetime.strptime(f"{draw_date} {draw_time}", "%Y-%m-%d %H:%M").replace(tzinfo=now.tzinfo)
    if now < target + timedelta(minutes=1):
        raise ValueError("El sorteo todavía no está habilitado para confirmación.")
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM sorteos WHERE fecha_sorteo = ? AND hora_sorteo = ?",
            (draw_date, draw_time),
        ).fetchone()
        if row is None or row["estado"] != "pendiente_confirmacion":
            raise ValueError("No existe un resultado provisional confirmable para esa hora.")
        before = row
        connection.execute(
            "INSERT INTO auditoria_correcciones(tabla,registro_id,motivo,datos_anteriores,datos_nuevos,creado_en) VALUES (?,?,?,?,?,?)",
            ("sorteos", row["id"], reason, json.dumps(before, ensure_ascii=False), json.dumps({"codigo": code, "animal": animal, "estado": "confirmado"}, ensure_ascii=False), now.isoformat(timespec="seconds")),
        )
        connection.execute(
            "UPDATE sorteos SET codigo = ?, animal = ?, estado = 'confirmado', fuente = 'panel_confirmado', capturado_en = ? WHERE id = ? AND estado = 'pendiente_confirmacion'",
            (code, animal, now.isoformat(timespec="seconds"), row["id"]),
        )
        connection.execute(
            "UPDATE predicciones SET estado = 'pendiente', correccion_motivo = NULL WHERE objetivo_fecha = ? AND objetivo_hora = ? AND estado = 'pendiente_confirmacion'",
            (draw_date, draw_time),
        )

def prediction_history(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM predicciones
            ORDER BY objetivo_fecha DESC, objetivo_hora DESC, id DESC
            """
        ).fetchall()
    return rows

def context_weights(
    database_path: str | Path,
    hour: int,
    weekday: int,
) -> dict[str, float]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT pilar, peso, hora, dia_semana
            FROM pesos_pilares_contexto
            WHERE (hora = ? AND dia_semana = ?)
               OR (hora = ? AND dia_semana = 0)
               OR (hora = -1 AND dia_semana = 0)
            ORDER BY
                CASE WHEN hora = ? AND dia_semana = ? THEN 0
                     WHEN hora = ? AND dia_semana = 0 THEN 1 ELSE 2 END
            """,
            (hour, weekday, hour, hour, weekday, hour),
        ).fetchall()
    weights = {}
    for row in rows:
        if row["pilar"] not in weights:
            weights[row["pilar"]] = float(row["peso"])
    return {pillar: weights.get(pillar, BASE_WEIGHTS[pillar]) for pillar in PILLARS}

def context_weight_rows(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT pilar, hora, dia_semana, peso, ultima_actualizacion, total_verificaciones
            FROM pesos_pilares_contexto
            ORDER BY hora, dia_semana, pilar
            """
        ).fetchall()
    return rows

def verified_position_summary(database_path: str | Path) -> dict[str, float | int | None]:
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total, AVG(posicion_ganador) AS promedio,
                   SUM(CASE WHEN posicion_ganador <= 5 THEN 1 ELSE 0 END) AS oro,
                   SUM(CASE WHEN posicion_ganador <= 10 THEN 1 ELSE 0 END) AS top10,
                   SUM(CASE WHEN posicion_ganador <= 20 THEN 1 ELSE 0 END) AS top20
            FROM predicciones
            WHERE posicion_ganador IS NOT NULL
            """
        ).fetchone()
    if not row:
        return {"total": 0, "promedio": None, "oro": 0, "top10": 0, "top20": 0}
    return {
        "total": int(row["total"] or 0),
        "promedio": float(row["promedio"]) if row["promedio"] is not None else None,
        "oro": int(row["oro"] or 0),
        "top10": int(row["top10"] or 0),
        "top20": int(row["top20"] or 0),
    }

def update_context_weights(
    database_path: str | Path,
    prediction_id: int,
    code: str,
) -> dict[str, float]:
    with connect(database_path) as connection:
        prediction = connection.execute(
            "SELECT objetivo_hora, objetivo_fecha, posicion_ganador, franja, pilares_influyentes "
            "FROM predicciones WHERE id = ?",
            (prediction_id,),
        ).fetchone()
        if prediction is None or prediction["posicion_ganador"] is None:
            return {}
        hour = int(prediction["objetivo_hora"][:2])
        weekday = datetime.strptime(prediction["objetivo_fecha"], "%Y-%m-%d").weekday() + 1
        signals = json.loads(prediction["pilares_influyentes"] or "{}")
        influential = [pillar for pillar in PILLARS if signals.get(pillar, 0.0) > 0]
        deltas = {pillar: 0.0 for pillar in PILLARS}
        if prediction["franja"] == "Oro":
            deltas.update({pillar: 0.10 if pillar in influential else -0.02 for pillar in PILLARS})
        elif prediction["franja"] == "Plata":
            deltas.update({pillar: 0.05 if pillar in influential else -0.05 for pillar in PILLARS})
        elif prediction["franja"] == "Bronce":
            deltas.update({pillar: 0.02 if pillar in influential else -0.10 for pillar in PILLARS})
        else:
            deltas = {pillar: -0.05 for pillar in PILLARS}
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        updated = {}
        for pillar, delta in deltas.items():
            row = connection.execute(
                "SELECT peso FROM pesos_pilares_contexto WHERE pilar = ? AND hora = ? AND dia_semana = ?",
                (pillar, hour, weekday),
            ).fetchone()
            current = float(row["peso"]) if row else BASE_WEIGHTS[pillar]
            new_weight = min(5.0, max(0.1, current + delta * 0.3))
            if connection.is_pg:
                connection.execute(
                    """
                    INSERT INTO pesos_pilares_contexto
                        (pilar, hora, dia_semana, peso, ultima_actualizacion, total_verificaciones)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(pilar, hora, dia_semana) DO UPDATE SET
                        peso = EXCLUDED.peso,
                        ultima_actualizacion = EXCLUDED.ultima_actualizacion,
                        total_verificaciones = pesos_pilares_contexto.total_verificaciones + 1
                    """,
                    (pillar, hour, weekday, new_weight, now),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO pesos_pilares_contexto
                        (pilar, hora, dia_semana, peso, ultima_actualizacion, total_verificaciones)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(pilar, hora, dia_semana) DO UPDATE SET
                        peso = excluded.peso,
                        ultima_actualizacion = excluded.ultima_actualizacion,
                        total_verificaciones = pesos_pilares_contexto.total_verificaciones + 1
                    """,
                    (pillar, hour, weekday, new_weight, now),
                )
            updated[pillar] = new_weight
    return updated

def pending_predictions(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM predicciones WHERE acierto IS NULL ORDER BY objetivo_fecha, objetivo_hora"
        ).fetchall()
    return rows

def verify_prediction(
    database_path: str | Path,
    prediction_id: int,
    code: str,
    animal: str,
) -> bool:
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT objetivo_fecha, objetivo_hora, ranking_completo, probabilidades_json,
                   estado, acierto
            FROM predicciones WHERE id = ?
            """,
            (prediction_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Predicción no encontrada.")
        if row["estado"] != "pendiente" or row["acierto"] is not None:
            raise ValueError("La predicción ya fue verificada o está bloqueada.")
        target = datetime.strptime(
            f"{row['objetivo_fecha']} {row['objetivo_hora']}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=datetime.now().astimezone().tzinfo)
        if datetime.now().astimezone() < target + timedelta(minutes=1):
            raise ValueError("El sorteo todavía no está habilitado para verificación.")
        ranking = json.loads(row["ranking_completo"] or row["probabilidades_json"])
        winner_index = next((index for index, item in enumerate(ranking) if item["codigo"] == code), None)
        position = winner_index + 1 if winner_index is not None else None
        if position is None:
            franja = "Sin Cobertura"
        elif position <= 5:
            franja = "Oro"
        elif position <= 10:
            franja = "Plata"
        elif position <= 20:
            franja = "Bronce"
        else:
            franja = "Sin Cobertura"
        hit = position is not None and position <= 10
        winner = ranking[winner_index] if winner_index is not None else {}
        pillar_keys = ("base", "hora", "dia_hora", "markov", "reciente", "penalizacion")
        influential = {
            key: (-winner.get(key, 0.0) if key == "penalizacion" else winner.get(key, 0.0))
            for key in pillar_keys
            if key in winner
        }
        cursor = connection.execute(
            """
            UPDATE predicciones
            SET resultado_codigo = ?, resultado_animal = ?, acierto = ?, posicion_ganador = ?,
                franja = ?, pilares_influyentes = ?, verificada_en = ?,
                resultado_capturado_en = ?, fuente_resultado = 'panel', estado = 'verificada'
            WHERE id = ? AND estado = 'pendiente' AND acierto IS NULL
            """,
              (code, animal, int(hit), position, franja, json.dumps(influential),
               datetime.now().astimezone().isoformat(timespec="seconds"),
               datetime.now().astimezone().isoformat(timespec="seconds"), prediction_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("La predicción ya fue verificada por otra operación.")
    update_context_weights(database_path, prediction_id, code)
    return hit

def historical_runs(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM pruebas_historicas
            ORDER BY fecha_ejecucion DESC, id DESC
            """
        ).fetchall()
    return rows

def insert_many(database_path: str | Path, rows: Iterable[tuple]) -> tuple[int, int]:
    with connect(database_path) as connection:
        rows_list = list(rows)
        cursor = connection.executemany(
            """
            INSERT OR IGNORE INTO sorteos
                (fecha_sorteo, hora_sorteo, codigo, animal, dia_semana, fuente, capturado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows_list,
        )
        inserted = cursor.rowcount if cursor.rowcount > 0 else len(rows_list)
        return inserted, len(rows_list) - inserted
