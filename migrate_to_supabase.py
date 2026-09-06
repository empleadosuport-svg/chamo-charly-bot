"""Migrate SQLite data to Supabase PostgreSQL."""

import sqlite3
import psycopg2
import psycopg2.extras

SQLITE_DB = "/home/monkee/Documentos/Chamo Charly/data/chamo_charly.db"
POSTGRES_URL = "postgresql://postgres.qoxcsmzfgaozgvahrykx:ChamoCharly2026@aws-0-us-east-1.pooler.supabase.com:5432/postgres"

DDL_STATEMENTS = [
    """
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
    """,
    """
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
    """,
    """
    CREATE TABLE IF NOT EXISTS auditoria_correcciones (
        id SERIAL PRIMARY KEY,
        tabla VARCHAR(50) NOT NULL,
        registro_id INTEGER NOT NULL,
        motivo TEXT NOT NULL,
        datos_anteriores TEXT NOT NULL,
        datos_nuevos TEXT NOT NULL,
        creado_en VARCHAR(50) NOT NULL
    );
    """,
    """
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
    """,
    """
    CREATE TABLE IF NOT EXISTS pesos (
        pilar VARCHAR(50) PRIMARY KEY,
        peso DOUBLE PRECISION NOT NULL,
        actualizaciones INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
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
]

TABLES_TO_MIGRATE = [
    ("sorteos", ["id", "fecha_sorteo", "hora_sorteo", "codigo", "animal", "dia_semana", "fuente", "capturado_en", "estado"]),
    ("predicciones", [
        "id", "creada_en", "objetivo_fecha", "objetivo_hora", "modelo", "observaciones",
        "top10_json", "ranking_completo", "probabilidades_json", "probabilidad_conjunto",
        "explicacion_json", "resultado_codigo", "resultado_animal", "acierto",
        "posicion_ganador", "franja", "pilares_influyentes", "verificada_en",
        "estado", "primera_creada_en", "resultado_capturado_en", "fuente_resultado", "correccion_motivo"
    ]),
    ("pesos_pilares_contexto", ["id", "pilar", "hora", "dia_semana", "peso", "ultima_actualizacion", "total_verificaciones"]),
    ("pesos", ["pilar", "peso", "actualizaciones"]),
    ("auditoria_correcciones", ["id", "tabla", "registro_id", "motivo", "datos_anteriores", "datos_nuevos", "creado_en"]),
    ("pruebas_historicas", [
        "id", "configuracion", "modelo", "particion", "rango_dias", "posicion_promedio",
        "top5", "top10", "top20", "sorteos_entrenamiento", "sorteos_validacion", "sorteos_prueba",
        "fecha_ejecucion", "duracion_segundos"
    ]),
]

def migrate():
    print("Conectando a SQLite...")
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    print("Conectando a Supabase PostgreSQL...")
    pg_conn = psycopg2.connect(POSTGRES_URL)
    pg_cursor = pg_conn.cursor()

    print("Creando tablas en Supabase...")
    for ddl in DDL_STATEMENTS:
        pg_cursor.execute(ddl)
    pg_conn.commit()
    print("Tablas creadas exitosamente.")

    for table_name, columns in TABLES_TO_MIGRATE:
        col_list = ", ".join(columns)
        sqlite_cursor.execute(f"SELECT {col_list} FROM {table_name}")
        rows = sqlite_cursor.fetchall()
        print(f"Migrando {len(rows)} registros de la tabla '{table_name}'...")

        if not rows:
            continue

        if "id" in columns:
            conflict_target = "id"
            if table_name == "sorteos":
                conflict_clause = "ON CONFLICT (fecha_sorteo, hora_sorteo) DO NOTHING"
            elif table_name == "predicciones":
                conflict_clause = "ON CONFLICT (objetivo_fecha, objetivo_hora) DO NOTHING"
            elif table_name == "pesos_pilares_contexto":
                conflict_clause = "ON CONFLICT (pilar, hora, dia_semana) DO NOTHING"
            else:
                conflict_clause = f"ON CONFLICT ({conflict_target}) DO NOTHING"
        else:
            conflict_clause = "ON CONFLICT (pilar) DO NOTHING"

        query = f"INSERT INTO {table_name} ({col_list}) VALUES %s {conflict_clause}"
        
        batch = [tuple(r[col] for col in columns) for r in rows]

        psycopg2.extras.execute_values(pg_cursor, query, batch, page_size=1000)
        pg_conn.commit()
        print(f"  -> '{table_name}' migrada exitosamente ({len(rows)} filas).")

        # Update SERIAL sequence to max(id) if id column exists
        if "id" in columns:
            pg_cursor.execute(f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE(max(id), 1)) FROM {table_name}")
            pg_conn.commit()

    print("\n--- VERIFICACIÓN EN SUPABASE ---")
    for table_name, _ in TABLES_TO_MIGRATE:
        pg_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = pg_cursor.fetchone()[0]
        print(f"Total en Supabase '{table_name}': {count}")

    sqlite_conn.close()
    pg_conn.close()
    print("\n¡MIGRACIÓN COMPLETA CON ÉXITO!")

if __name__ == "__main__":
    migrate()
