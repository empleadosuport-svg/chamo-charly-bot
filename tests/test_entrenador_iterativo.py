"""Unit tests for the iterative error-driven training module."""

import pytest
from pathlib import Path
from chamo_charly.database import PILLARS, init_db, insert_draw
from chamo_charly.entrenador_iterativo import EntrenadorIterativoPilar, EstadoPilar


def test_estado_pilar_eficiencia():
    estado = EstadoPilar(nombre="hora", aciertos_top20=80, total_sorteos=100, total_iteraciones=200)
    assert estado.tasa_acierto_malla == 0.80
    assert estado.promedio_iteraciones == 2.0
    assert estado.puntaje_eficiencia > 0.0


def test_entrenador_iterativo_ejecucion(tmp_path):
    db_path = tmp_path / "test_entrenador.db"
    init_db(db_path)

    # Insert sample draws
    sample_draws = [
        ("2026-09-01", "08:00", "04", "Alacrán", "martes"),
        ("2026-09-01", "09:00", "15", "Zorro", "martes"),
        ("2026-09-01", "10:00", "02", "Toro", "martes"),
        ("2026-09-01", "11:00", "22", "Camello", "martes"),
        ("2026-09-01", "12:00", "27", "Perro", "martes"),
    ]
    for d in sample_draws:
        insert_draw(db_path, d[0], d[1], d[2], d[3], d[4])

    entrenador = EntrenadorIterativoPilar(db_path, max_iteraciones_por_sorteo=3)
    resumen = entrenador.entrenar_historial_completo()

    assert "base" in resumen
    assert "hora" in resumen
    assert "markov" in resumen
    assert len(resumen) == len(PILLARS)

    pesos = entrenador.obtener_pesos_eficientes()
    assert len(pesos) == len(PILLARS)
    assert pytest.approx(sum(pesos.values()), 0.01) == 1.0
