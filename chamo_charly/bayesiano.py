"""Bayesian Model Averaging (BMA) with Dirichlet Priors for Chamo Charly Sandbox.

This module implements a formal Bayesian ensemble model using a Dirichlet prior
over the combination weights of the 7 underlying pillars.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple
import numpy as np

ANIMALS = [
    "00", "0", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22",
    "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34",
    "35", "36"
]

DEFAULT_BASE_WEIGHTS = {
    "base": 0.14,
    "hora": 0.22,
    "dia_hora": 0.16,
    "markov": 0.12,
    "reciente": 0.12,
    "penalizacion_contextual": 0.08,
    "piramide": 0.05,
    "eco_desplazado": 0.08,
}


class BayesianModelAveraging:
    def __init__(
        self,
        pillars: List[str] | None = None,
        base_weights: Dict[str, float] | None = None,
        eta: float = 0.5,
        prior_scale: float = 100.0,
        evidence_func: str = "reciprocal",
    ):
        """Initialize BMA model with Dirichlet prior.

        Args:
            pillars: List of pillar names to combine.
            base_weights: Initial weights for Dirichlet prior.
            eta: Learning rate for sequential evidence updates.
            prior_scale: Scaling factor for Dirichlet concentration parameters alpha_0.
            evidence_func: Mode for evidence function ('reciprocal', 'hierarchical_step', 'quadratic_tail').
        """
        self.base_weights = base_weights or DEFAULT_BASE_WEIGHTS
        self.pillars = pillars or list(self.base_weights.keys())
        self.eta = eta
        self.prior_scale = prior_scale
        self.evidence_func = evidence_func

        # Normalize base_weights to ensure sum is exactly 1.0
        total_bw = sum(self.base_weights.get(p, 0.0) for p in self.pillars)
        if total_bw > 0:
            norm_bw = {p: self.base_weights.get(p, 0.0) / total_bw for p in self.pillars}
        else:
            uniform = 1.0 / len(self.pillars)
            norm_bw = {p: uniform for p in self.pillars}

        # Initialize Dirichlet concentration parameters alpha
        self.alpha: Dict[str, float] = {}
        for p in self.pillars:
            w = norm_bw[p]
            self.alpha[p] = max(0.1, w * self.prior_scale)

        self.history_updates: List[Dict[str, float]] = []

    def _calculate_evidence(self, rank: int) -> float:
        """Compute evidence score based on the selected evidence function."""
        r = float(max(1, rank))
        if self.evidence_func == "hierarchical_step":
            if rank == 1:
                return 1.0
            elif rank <= 5:
                return 0.7
            elif rank <= 10:
                return 0.3
            elif rank <= 20:
                return 0.1
            else:
                return 0.01
        elif self.evidence_func == "quadratic_tail":
            return (1.0 / (r ** 1.5)) + (0.05 / r)
        else:  # "reciprocal"
            return 1.0 / r

    def get_expected_weights(self) -> Dict[str, float]:
        """Compute expected weight E[w_m] = alpha_m / sum(alpha)."""
        total = sum(self.alpha.values())
        if total <= 0:
            uniform = 1.0 / len(self.pillars)
            return {p: uniform for p in self.pillars}
        return {p: self.alpha[p] / total for p in self.pillars}

    def combine_probabilities(
        self, pillar_signals: Dict[str, Dict[str, float]], hour: str | None = None
    ) -> Dict[str, float]:
        """Combine 7 pillar signal distributions into single posterior distribution.
        
        If hour >= '13:00', applies Asymmetric Hourly Calibration (boosts Markov,
        Context Penalty, and Day-Hour pillars).
        """
        weights = self.get_expected_weights()
        
        # Apply Asymmetric Hourly Calibration for afternoon draws
        if hour is not None and hour >= "13:00":
            boosted = dict(weights)
            boosted["markov"] = boosted.get("markov", 0.0) * 1.4
            boosted["penalizacion_contextual"] = boosted.get("penalizacion_contextual", 0.0) * 1.3
            boosted["dia_hora"] = boosted.get("dia_hora", 0.0) * 1.2
            total_b = sum(boosted.values())
            if total_b > 0:
                weights = {p: boosted[p] / total_b for p in boosted}

        combined: Dict[str, float] = {code: 0.0 for code in ANIMALS}

        for p in self.pillars:
            w = weights.get(p, 0.0)
            signal = pillar_signals.get(p, {})
            for code in ANIMALS:
                combined[code] += w * signal.get(code, 0.0)

        # Apply Base Floor Smoothing (0.012) to protect coverage against cold animals
        min_floor = 0.012
        for code in combined:
            combined[code] = max(combined[code], min_floor)

        # Normalize combined distribution
        total_prob = sum(combined.values())
        if total_prob > 0:
            for code in combined:
                combined[code] /= total_prob
        else:
            uniform = 1.0 / len(ANIMALS)
            for code in combined:
                combined[code] = uniform

        return combined

    def get_bayesian_escalation(
        self, prev_probs: Dict[str, float], curr_probs: Dict[str, float], top_n: int = 3
    ) -> List[Tuple[str, float]]:
        """Identify animals with maximum positive probability escalation (momentum delta)."""
        deltas = {code: curr_probs.get(code, 0.0) - prev_probs.get(code, 0.0) for code in ANIMALS}
        sorted_deltas = sorted(deltas.items(), key=lambda x: x[1], reverse=True)
        return sorted_deltas[:top_n]

    def update(
        self, pillar_signals: Dict[str, Dict[str, float]], winning_code: str
    ) -> Dict[str, float]:
        """Update Dirichlet parameters alpha based on winner's rank in each pillar.

        Ev_m = 1.0 / rank_m(winner)
        alpha_m_new = alpha_m_old + eta * Ev_m
        """
        evidence: Dict[str, float] = {}

        for p in self.pillars:
            signal = pillar_signals.get(p, {})
            # Rank animals in descending order of probability
            sorted_codes = sorted(
                ANIMALS, key=lambda c: signal.get(c, 0.0), reverse=True
            )
            try:
                rank = sorted_codes.index(winning_code) + 1  # 1-indexed rank
            except ValueError:
                rank = len(ANIMALS)

            # Reciprocal Rank Evidence
            ev = 1.0 / float(rank)
            evidence[p] = ev

            # Update concentration parameter
            self.alpha[p] += self.eta * ev

        self.history_updates.append(dict(evidence))
        return evidence

    def compute_credible_interval(
        self,
        pillar_signals: Dict[str, Dict[str, float]],
        n_samples: int = 1000,
        top_k: int = 10,
        ci_level: float = 0.95,
    ) -> Tuple[float, float, float]:
        """Sample weights from Dirichlet distribution and compute Credible Interval for Top-K coverage.

        Returns:
            (mean_coverage, lower_bound, upper_bound)
        """
        alpha_vec = np.array([self.alpha[p] for p in self.pillars], dtype=float)
        # Sample weights shape: (n_samples, num_pillars)
        sampled_weights = np.random.dirichlet(alpha_vec, size=n_samples)

        # Build signal matrix shape: (num_pillars, 38)
        signal_matrix = np.zeros((len(self.pillars), len(ANIMALS)), dtype=float)
        for i, p in enumerate(self.pillars):
            signal = pillar_signals.get(p, {})
            for j, code in enumerate(ANIMALS):
                signal_matrix[i, j] = signal.get(code, 0.0)

        # Matrix multiply sampled_weights (n_samples, num_pillars) @ signal_matrix (num_pillars, 38) -> (n_samples, 38)
        sampled_probs = sampled_weights @ signal_matrix

        # Normalize sampled probabilities per row
        row_sums = sampled_probs.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        sampled_probs /= row_sums

        # Calculate top-k cumulative probability per sample
        top_k_coverages = np.zeros(n_samples, dtype=float)
        for b in range(n_samples):
            sorted_probs = np.sort(sampled_probs[b, :])[::-1]
            top_k_coverages[b] = np.sum(sorted_probs[:top_k])

        alpha_tail = (1.0 - ci_level) / 2.0
        lower = float(np.percentile(top_k_coverages, alpha_tail * 100))
        upper = float(np.percentile(top_k_coverages, (1.0 - alpha_tail) * 100))
        mean_cov = float(np.mean(top_k_coverages))

        return mean_cov, lower, upper
