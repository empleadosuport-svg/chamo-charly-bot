"""Iterative Error-Driven Reinforcement Learning Module for Chamo Charly 7 Pillars.

Motor de Entrenamiento Iterativo por Repetición:
- Recorre cronológicamente todos los sorteos del historial.
- Por cada sorteo, evalúa cada pilar de forma INDEPENDIENTE.
- Si el ganador no entra en Top 20 (Malla de Seguridad), ajusta los parámetros
  del pilar y repite hasta acertar o alcanzar el límite de iteraciones.
- Acumula métricas de eficiencia para ponderar el peso final de cada pilar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from chamo_charly.catalog import ANIMALS
from chamo_charly.database import (
    BASE_WEIGHTS,
    chronological_draws,
)
from chamo_charly.predictor import (
    PILLARS_7_PIRAMIDE,
    _context_penalty_signal_laplace,
    _day_hour_signal_laplace,
    _global_signal_laplace,
    _hour_signal_laplace,
    _markov_signal_laplace,
    _piramide_signal_laplace,
    _recent_signal_laplace,
)

logger = logging.getLogger(__name__)


@dataclass
class EstadoPilar:
    """Estado mutable de un pilar durante el entrenamiento iterativo."""

    nombre: str
    # Parámetros ajustables durante el entrenamiento
    epsilon: float = 0.005
    decay: float = 0.95
    factor_impulso: float = 1.0
    # Contadores acumulados
    aciertos_top5: int = 0
    aciertos_top10: int = 0
    aciertos_top20: int = 0
    total_iteraciones: int = 0
    total_sorteos: int = 0

    @property
    def tasa_acierto_malla(self) -> float:
        if self.total_sorteos <= 0:
            return 0.0
        return self.aciertos_top20 / self.total_sorteos

    @property
    def promedio_iteraciones(self) -> float:
        if self.total_sorteos <= 0:
            return 1.0
        return self.total_iteraciones / self.total_sorteos

    @property
    def puntaje_eficiencia(self) -> float:
        """Mayor tasa de aciertos y menos repeticiones = mayor eficiencia (peso final)."""
        if self.total_sorteos <= 0:
            return 0.1
        penalizacion = 1.0 + 0.05 * max(0.0, self.promedio_iteraciones - 1.0)
        return max(0.01, self.tasa_acierto_malla / penalizacion)


def _calcular_senal_pilar(
    pilar: str,
    rows_historia: list[dict],
    target_dict: dict,
    estado: EstadoPilar,
) -> dict[str, float]:
    """Calcula la señal normalizada de un pilar con sus parámetros ajustados."""
    hour = target_dict["hora_sorteo"]
    if pilar == "base":
        return _global_signal_laplace(rows_historia)
    elif pilar == "hora":
        return _hour_signal_laplace(rows_historia, hour)
    elif pilar == "dia_hora":
        return _day_hour_signal_laplace(rows_historia, target_dict)
    elif pilar == "markov":
        return _markov_signal_laplace(rows_historia, hour)
    elif pilar == "reciente":
        return _recent_signal_laplace(rows_historia, hour, decay=estado.decay)
    elif pilar in ("penalizacion", "penalizacion_contextual"):
        return _context_penalty_signal_laplace(rows_historia, hour)
    elif pilar == "piramide":
        return _piramide_signal_laplace(target_dict)
    else:
        return {c: 1.0 / len(ANIMALS) for c in ANIMALS}


def _evaluar_posicion(signal: dict[str, float], winning_code: str) -> int:
    """Retorna el puesto (1-indexed) del animal ganador en el ranking de la señal."""
    sorted_codes = sorted(ANIMALS, key=lambda c: signal.get(c, 0.0), reverse=True)
    try:
        return sorted_codes.index(winning_code) + 1
    except ValueError:
        return len(ANIMALS)


def _ajustar_parametros_pilar(pilar: str, estado: EstadoPilar, iteracion: int) -> None:
    """Ajusta los parámetros internos del pilar para intentar capturar al ganador."""
    factor = 1.0 + 0.015 * iteracion
    if pilar == "reciente":
        if iteracion % 2 == 1:
            estado.decay = max(0.80, estado.decay * 0.98)
        else:
            estado.decay = min(0.99, estado.decay * 1.01)
    elif pilar in ("hora", "dia_hora", "markov"):
        estado.factor_impulso = min(3.0, estado.factor_impulso * factor)
    elif pilar == "base":
        estado.epsilon = min(0.05, estado.epsilon * factor)


class EntrenadorIterativoPilar:
    """Motor de Entrenamiento Iterativo por Repetición para los 7 Pilares.

    Uso típico:
        entrenador = EntrenadorIterativoPilar("data/chamo_charly.db")
        resumen = entrenador.entrenar_historial_completo()
        pesos = entrenador.obtener_pesos_eficientes()
    """

    def __init__(
        self,
        database_path: str | Path,
        max_iteraciones_por_sorteo: int = 20,
        log_progreso_cada: int = 500,
    ):
        self.database_path = Path(database_path)
        self.max_iteraciones = max_iteraciones_por_sorteo
        self.log_progreso_cada = log_progreso_cada
        self.pilares = list(PILLARS_7_PIRAMIDE)
        self.estados: dict[str, EstadoPilar] = {
            p: EstadoPilar(nombre=p) for p in self.pilares
        }

    def _reset_estados(self) -> None:
        """Reinicia todos los estados a valores por defecto."""
        self.estados = {p: EstadoPilar(nombre=p) for p in self.pilares}

    def entrenar_historial_completo(self, reset: bool = True) -> dict[str, dict]:
        """Recorre cronológicamente los 4,140+ sorteos ajustando cada pilar por repetición en caso de error.

        Args:
            reset: Si True, reinicia los estados antes de entrenar (recomendado).

        Returns:
            Diccionario con el resumen de métricas por pilar.
        """
        if reset:
            self._reset_estados()

        rows = chronological_draws(self.database_path)
        total_sorteos = len(rows)
        logger.info(f"🚀 Iniciando entrenamiento iterativo sobre {total_sorteos} sorteos...")

        for i in range(1, total_sorteos):
            t_row = rows[i]
            h_rows = rows[:i]
            winning_code = t_row["codigo"]
            target_dict = {
                "fecha_sorteo": t_row["fecha_sorteo"],
                "hora_sorteo": t_row["hora_sorteo"],
                "dia_semana": t_row["dia_semana"],
            }

            for pilar_nombre, estado in self.estados.items():
                estado.total_sorteos += 1
                iteracion = 0
                acertado = False

                while iteracion < self.max_iteraciones and not acertado:
                    iteracion += 1
                    signal = _calcular_senal_pilar(pilar_nombre, h_rows, target_dict, estado)
                    pos = _evaluar_posicion(signal, winning_code)

                    if pos <= 20:
                        acertado = True
                        if pos <= 5:
                            estado.aciertos_top5 += 1
                        if pos <= 10:
                            estado.aciertos_top10 += 1
                        estado.aciertos_top20 += 1
                    else:
                        _ajustar_parametros_pilar(pilar_nombre, estado, iteracion)

                estado.total_iteraciones += iteracion

            if i % self.log_progreso_cada == 0:
                logger.info(f"  ✔ Procesados {i}/{total_sorteos - 1} sorteos...")

        logger.info("✅ Entrenamiento completado.")
        return self._generar_resumen()

    def _generar_resumen(self) -> dict[str, dict]:
        """Genera el resumen completo de métricas por pilar."""
        pesos = self.obtener_pesos_eficientes()
        resumen = {}
        for p, st in self.estados.items():
            resumen[p] = {
                "total_sorteos": st.total_sorteos,
                "aciertos_top5": st.aciertos_top5,
                "aciertos_top10": st.aciertos_top10,
                "aciertos_top20": st.aciertos_top20,
                "tasa_top5": f"{st.aciertos_top5 / max(1, st.total_sorteos):.2%}",
                "tasa_top10": f"{st.aciertos_top10 / max(1, st.total_sorteos):.2%}",
                "tasa_acierto_malla": f"{st.tasa_acierto_malla:.2%}",
                "promedio_iteraciones": round(st.promedio_iteraciones, 3),
                "puntaje_eficiencia": round(st.puntaje_eficiencia, 5),
                "peso_eficiente_final": f"{pesos[p]:.4%}",
                "epsilon_final": round(st.epsilon, 5),
                "decay_final": round(st.decay, 5),
                "factor_impulso_final": round(st.factor_impulso, 4),
            }
        return resumen

    def obtener_pesos_eficientes(self) -> dict[str, float]:
        """Retorna los pesos normalizados según la eficiencia de cada pilar."""
        puntajes = {p: st.puntaje_eficiencia for p, st in self.estados.items()}
        suma = sum(puntajes.values())
        if suma <= 0:
            return {p: 1.0 / len(self.pilares) for p in self.pilares}
        return {p: puntajes[p] / suma for p in self.pilares}

    def obtener_pesos_como_base_weights(self) -> dict[str, float]:
        """Retorna pesos en el mismo formato que BASE_WEIGHTS del predictor.

        Los pesos se escalan a la misma suma que BASE_WEIGHTS para que sean
        directamente intercambiables en _coverage_score y bma_prediction.
        """
        pesos = self.obtener_pesos_eficientes()
        suma_base = sum(BASE_WEIGHTS.values())
        nombre_map = {"penalizacion_contextual": "penalizacion"}
        return {nombre_map.get(p, p): peso * suma_base for p, peso in pesos.items()}
