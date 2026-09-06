from datetime import datetime

import pytest

from chamo_charly.catalog import ANIMALS, animal_for_code, code_for_animal, validate_result
from chamo_charly.database import (
    chronological_draws,
    confirm_provisional_draw,
    context_weights,
    count_draws,
    draw_for_slot,
    init_db,
    insert_draw,
    latest_prediction,
    prediction_by_id,
    save_prediction,
    verify_prediction,
)
from chamo_charly.database import insert_many
from chamo_charly.evaluador import run_historical_evaluation
from chamo_charly.importer import parse_raw_text
from chamo_charly.predictor import baseline_prediction, composite_prediction, coverage_prediction, next_target
from chamo_charly.piramide import pyramid_rows, pyramid_signal, pyramid_signal_for_target
from chamo_charly.analytics import frequency_table, markov_transitions, runs_test, uniformity_test


def test_zero_and_double_zero_are_different():
    assert animal_for_code("00") == "Ballena"
    assert animal_for_code("0") == "Delfín"
    assert animal_for_code("01") == "Carnero"
    assert animal_for_code("1") == "Carnero"


def test_code_for_animal_matches_catalog_values():
    assert code_for_animal("Caimán") == "30"
    assert code_for_animal("Perico") == "07"
    assert code_for_animal("Oso") == "16"


def test_result_validation_detects_mismatch():
    assert validate_result("30", "Caimán") is None
    assert validate_result("30", "Iguana") is not None


def test_pyramid_signal_uses_fixed_date_time_rules():
    assert len(pyramid_rows("040920261800")) == 12
    assert pyramid_signal("040920261800") == [
        "08", "00", "04", "02", "10", "16", "09", "11", "15", "17"
    ]


def test_pyramid_signal_uses_target_slot_not_current_time():
    assert pyramid_signal_for_target(datetime(2026, 9, 4).date(), datetime.strptime("18:00", "%H:%M").time()) == pyramid_signal("040920261800")


def test_insert_draw_and_count(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    insert_draw(database_path, "2026-09-03", "10:00", "30", "Caimán", "jueves")
    assert count_draws(database_path) == 1


def test_importer_normalizes_names_and_deduplicates():
    raw_text = """
Resultados del dia: 03/08/2026
03/08/2026
Imagen de Caiman
30 Caiman
Lotto Activo 07:00 PM
Resultados del dia: 03/08/2026
30 Caiman
Lotto Activo 07:00 PM
"""
    records, warnings = parse_raw_text(raw_text)
    assert warnings == []
    assert records == [{
        "fecha": "2026-08-03",
        "hora": "19:00",
        "codigo": "30",
        "animal": "Caimán",
    }]


def test_insert_many_is_idempotent(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    row = ("2026-09-03", "10:00", "30", "Caimán", "jueves", "csv", "2026-09-03T10:00:00+00:00")
    assert insert_many(database_path, [row, row]) == (1, 1)
    assert insert_many(database_path, [row]) == (0, 1)
    assert count_draws(database_path) == 1


def test_provisional_draw_can_be_confirmed_once_after_target_time(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    insert_draw(
        database_path,
        "2026-09-03",
        "10:00",
        "30",
        "Caimán",
        "jueves",
        status="pendiente_confirmacion",
    )

    confirm_provisional_draw(
        database_path,
        "2026-09-03",
        "10:00",
        "01",
        "Carnero",
        "Confirmación de prueba.",
    )

    confirmed = draw_for_slot(database_path, "2026-09-03", "10:00")
    assert confirmed["estado"] == "confirmado"
    assert confirmed["codigo"] == "01"
    with pytest.raises(ValueError, match="No existe un resultado provisional"):
        confirm_provisional_draw(
            database_path,
            "2026-09-03",
            "10:00",
            "30",
            "Caimán",
            "Segundo intento.",
        )


def test_prediction_records_winner_position_and_band(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    ranking = [
        {"codigo": code, "animal": animal, "probabilidad": 1 / 38, "hora": 0.01}
        for code, animal in ANIMALS.items()
    ]
    ranking[6]["codigo"], ranking[6]["animal"] = "16", "Oso"
    prediction = {
        "target_date": "2026-09-03",
        "target_time": "19:00",
        "model": "test",
        "observations": 38,
        "top10": ranking[:10],
        "ranking": ranking,
        "explanation": [],
    }
    prediction_id = save_prediction(database_path, prediction)
    assert verify_prediction(database_path, prediction_id, "16", "Oso") is True
    verified = prediction_by_id(database_path, prediction_id)
    assert verified["posicion_ganador"] == 7
    assert verified["franja"] == "Plata"
    assert verified["ranking_completo"]
    assert latest_prediction(database_path)["id"] == prediction_id
    weights = context_weights(database_path, 19, 4)
    assert weights["hora"] == pytest.approx(0.335)
    assert weights["base"] == pytest.approx(0.165)


def test_chronological_draws_and_recent_signal_order(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    insert_draw(database_path, "2026-09-03", "10:00", "01", "Carnero", "jueves")
    insert_draw(database_path, "2026-09-04", "10:00", "30", "Caimán", "viernes")
    rows = chronological_draws(database_path)
    assert [row["codigo"] for row in rows] == ["01", "30"]
    from chamo_charly.predictor import _recent_decay_signal
    signal = _recent_decay_signal(rows, "10:00")
    assert signal["30"] > signal["01"]


def test_importer_handles_markdown_style_lotto_activo_results():
    raw_text = """
# Resultados del dia: 03/09/2026
##### Fecha: 03/09/2026
![Imagen de Perico](...)
###### 07 Perico
Lotto Activo 08:00 AM

![Imagen de Oso](...)
###### 16 Oso
Lotto Activo 09:00 AM

![Imagen de Carnero](...)
###### 01 Carnero
Lotto Activo 10:00 AM

![Imagen de Caiman](...)
###### 30 Caiman
Lotto Activo 04:00 PM
"""
    records, warnings = parse_raw_text(raw_text)
    assert warnings == []
    assert [record["codigo"] for record in records] == ["07", "16", "01", "30"]
    assert [record["animal"] for record in records] == ["Perico", "Oso", "Carnero", "Caimán"]


def test_next_target_uses_reference_time_when_provided(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    insert_draw(database_path, "2026-09-03", "14:00", "30", "Caimán", "jueves")
    assert next_target(database_path, datetime(2026, 9, 3, 19, 45)) == ("2026-09-04", "08:00")


def test_next_target_respects_daily_schedule_boundaries(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    assert next_target(database_path, datetime(2026, 9, 3, 7, 0)) == ("2026-09-03", "08:00")
    assert next_target(database_path, datetime(2026, 9, 3, 19, 0)) == ("2026-09-03", "19:00")
    assert next_target(database_path, datetime(2026, 9, 3, 19, 1)) == ("2026-09-04", "08:00")


def test_baseline_prediction_has_38_probabilities_and_next_target(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    insert_draw(database_path, "2026-09-03", "14:00", "30", "Caimán", "jueves")
    prediction = baseline_prediction(database_path)
    assert len(prediction["ranking"]) == 38
    assert abs(sum(item["probabilidad"] for item in prediction["ranking"]) - 1) < 1e-9
    assert next_target(database_path) == ("2026-09-03", "15:00")


def test_composite_prediction_uses_combined_pillars(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    for hour, code, animal in [
        ("10:00", "30", "Caimán"),
        ("11:00", "30", "Caimán"),
        ("12:00", "11", "Gato"),
        ("13:00", "11", "Gato"),
        ("14:00", "30", "Caimán"),
        ("15:00", "11", "Gato"),
    ]:
        insert_draw(database_path, "2026-09-03", hour, code, animal, "jueves")
    prediction = composite_prediction(database_path)
    assert prediction["model"] == "combinado_pilares"
    assert len(prediction["ranking"]) == 38
    assert abs(sum(item["probabilidad"] for item in prediction["ranking"]) - 1) < 1e-9
    assert "pilares" in prediction["explanation"][0].lower()


def test_coverage_prediction_prioritizes_target_hour_winner(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    records = [
        ("2026-08-25", "08:00", "31", "Lapa"),
        ("2026-08-26", "09:00", "31", "Lapa"),
        ("2026-08-27", "10:00", "31", "Lapa"),
        ("2026-08-28", "11:00", "31", "Lapa"),
        ("2026-08-29", "12:00", "31", "Lapa"),
        ("2026-08-30", "13:00", "31", "Lapa"),
        ("2026-08-31", "14:00", "31", "Lapa"),
        ("2026-09-01", "17:00", "05", "León"),
        ("2026-09-01", "18:00", "23", "Cebra"),
        ("2026-09-02", "18:00", "23", "Cebra"),
        ("2026-09-02", "15:00", "35", "Jirafa"),
        ("2026-09-02", "16:00", "11", "Gato"),
        ("2026-09-02", "17:00", "23", "Cebra"),
    ]
    for draw_date, hour, code, animal in records:
        insert_draw(database_path, draw_date, hour, code, animal, "jueves")
    prediction = coverage_prediction(database_path, reference_time=datetime(2026, 9, 3, 17, 45))
    assert prediction["target_time"] == "18:00"
    assert any(item["codigo"] == "23" for item in prediction["top10"])
    assert "piramide" in prediction["ranking"][0]


def test_analytics_pillars_return_auditable_metrics(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    for hour, code, animal in [("10:00", "01", "Carnero"), ("11:00", "30", "Caimán"), ("12:00", "01", "Carnero")]:
        insert_draw(database_path, "2026-09-03", hour, code, animal, "jueves")
    from chamo_charly.analytics import history_frame
    frame = history_frame(str(database_path))
    assert len(frequency_table(frame)) == 38
    assert abs(uniformity_test(frame)["p_valor"] - 0.0) >= 0.0
    assert markov_transitions(frame).iloc[0]["desde"] in {"01", "30"}
    assert runs_test(frame)["p_valor"] >= 0.0


def test_historical_evaluation_records_a_baseline_run(tmp_path):
    database_path = tmp_path / "test.db"
    init_db(database_path)
    for day in range(1, 8):
        for hour in ["08:00", "09:00", "10:00", "11:00", "12:00"]:
            code = str((day + hour.count("0")) % 38 + 1)
            animal = ANIMALS.get(code, "Carnero")
            insert_draw(database_path, f"2026-09-{day:02d}", hour, code, animal, "jueves")
    result = run_historical_evaluation(database_path, model_name="6_pilares", train_pct=0.6, val_pct=0.2, test_pct=0.2)
    assert result["sorteos_entrenamiento"] > 0
    assert result["sorteos_validacion"] > 0
    assert result["sorteos_prueba"] > 0
    assert isinstance(result["posicion_promedio"], float)
