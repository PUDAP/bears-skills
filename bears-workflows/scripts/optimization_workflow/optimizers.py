"""
Optimizers for colour mixing Delta E 2000 minimization and viscosity (transfer error) minimization.

Colour mixing:
    SOCM_BO      — abstract base: GP fitting, normalisation, volume constraint
    SOCM_BOEI    — Bayesian Optimization with Expected Improvement (LogEI)
    SOCM_BOLCB   — Bayesian Optimization with Lower Confidence Bound (UCB)
    SOCM_LLM — LLM (single objective: Delta E 2000)
    LLMOptimizer     — alias for SOCM_LLM

Viscosity — single-objective (SOVH), box-bounded parameters:
    SOVH_BO  — abstract base: one minimised scalar (e.g. abs error)
    SOVH_EI  — LogEI
    SOVH_LCB — UpperConfidenceBound with maximize=False on absolute error

Aliases: ViscosityBOOptimizer* → SOVH_* (backward compatible).

Viscosity — LLM:
    SOVH_LLM — one scalar goal (e.g. abs error); volume mode or generic params
    ViscosityLLMOptimizer — alias for SOVH_LLM

Dependencies:
    pip install botorch gpytorch torch openai

Environment variable (LLM optimizers):
    OPENROUTER_API_KEY — your OpenRouter API key
"""

from __future__ import annotations

import json
import math
import re
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from openai import OpenAI

# torch / botorch / gpytorch are only required by the BO optimizers.
# Imported lazily inside SOCM_BO.__init__ so colour-mixing LLM classes can be
# used without installing the full torch stack.
try:
    import torch
    from botorch.acquisition import LogExpectedImprovement, UpperConfidenceBound
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.optim import optimize_acqf
    from gpytorch.mlls import ExactMarginalLogLikelihood
    _BO_AVAILABLE = True
except ImportError:
    _BO_AVAILABLE = False


# ---------------------------------------------------------------------------
# OpenRouter model shorthand lookup
# ---------------------------------------------------------------------------

@dataclass
class SuggestionResult:
    volumes: list[float]
    optimizer: Literal["BO", "LLM"]
    llm_reasoning: str | None = None


OPENROUTER_MODELS: dict[str, str] = {
    "gpt-4o":            "openai/gpt-4o",
    "gpt-4.1":           "openai/gpt-4.1",
    "gpt-5.1":           "openai/gpt-5.1",
    "gpt-5.4":           "openai/gpt-5.4",
    "claude-sonnet-4-5": "anthropic/claude-sonnet-4-5",
    "claude-sonnet-4.6": "anthropic/claude-sonnet-4.6",
    "claude-opus-4":     "anthropic/claude-opus-4",
    "claude-opus-4.7":   "anthropic/claude-opus-4.7",
    "gemini-3.1-pro-preview": "google/gemini-3.1-pro-preview",
    "gemini-2.5-pro":    "google/gemini-2.5-pro-preview",
    "llama-4-maverick":  "meta-llama/llama-4-maverick",
    "deepseek-r2":       "deepseek/deepseek-r2",
    "deepseek-chat-v3":  "deepseek/deepseek-chat-v3-0324",
    "deepseek-v3.2":     "deepseek/deepseek-v3.2",
    "deepseek-v4-pro":   "deepseek/deepseek-v4-pro",
    "qwen3.5-plus":      "qwen/qwen3.5-plus-02-15",
    "qwen3-max":         "qwen/qwen3-max",
    "glm-5.1":           "z-ai/glm-5.1",
    "glm-4.6":           "z-ai/glm-4.6",
    "kimi-k2.5":         "moonshotai/kimi-k2.5",
    "kimi-k2-0905":      "moonshotai/kimi-k2-0905",
}


def _response_content_to_text(content: Any) -> str:
    """Normalize OpenAI/OpenRouter response content into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return str(content)


def _extract_first_json_object_text(response: str) -> str:
    """
    Extract the first valid JSON object from a model response.

    This is more robust than a greedy regex because models often prepend or
    append explanations, markdown fences, or multiple brace blocks.
    """
    text = response.strip()
    if not text:
        raise ValueError("Model returned an empty response.")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    else:
        if isinstance(data, dict):
            return text

    for start in (idx for idx, ch in enumerate(text) if ch == "{"):
        depth = 0
        in_string = False
        escape = False

        for end in range(start, len(text)):
            ch = text[end]

            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:end + 1]
                    try:
                        data = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    if isinstance(data, dict):
                        return candidate
                    break

    snippet = text[:200].replace("\n", "\\n")
    raise ValueError(f"Could not extract a valid JSON object from model response: {snippet}")


# ---------------------------------------------------------------------------
# Bayesian Optimization — base
# ---------------------------------------------------------------------------

class SOCM_BO(ABC):
    """
    Abstract base class for Bayesian Optimization of RGBy colour mixing volumes.

    Maintains a running history of (volume_ratios, Delta E 2000) observations, refits a
    SingleTaskGP surrogate after each observation, and suggests the next
    (R_vol, G_vol, B_vol, water_vol) expected to reduce Delta E 2000.

    Inputs are normalised to [0, 1] per dimension so that the equality constraint
    x1 + x2 + x3 + x4 = 1 is enforced directly in the optimisation. Delta E 2000 is negated
    because botorch maximises the acquisition function.

    Equality constraint: x1 + x2 + x3 + x4 = 1  (normalised space)
    This maps to R_vol + G_vol + B_vol + water_vol = total_volume in µL.

    Args:
        total_volume (float): Total well volume in µL. All suggested volumes sum to this.
        num_restarts (int): Restarts for acquisition function optimisation. Default: 10.
        raw_samples (int): Raw samples for initialising the optimisation. Default: 64.
    """

    N_DIMS = 4  # R_vol, G_vol, B_vol, water_vol

    # Equality constraint: indices [0,1,2,3], coefficients [1,1,1,1], rhs = 1.0
    # Enforces x1 + x2 + x3 + x4 = 1 in normalised space during optimize_acqf.
    _EQUALITY_CONSTRAINTS = [
        (
            torch.tensor([0, 1, 2, 3]),            # indices of all four dimensions
            torch.tensor([1.0, 1.0, 1.0, 1.0]),    # coefficients
            1.0,                                     # rhs: x1 + x2 + x3 + x4 = 1
        )
    ]

    def __init__(
        self,
        total_volume: float,
        num_restarts: int = 10,
        raw_samples: int = 64,
    ) -> None:
        self.total_volume = total_volume
        self.num_restarts = num_restarts
        self.raw_samples = raw_samples

        self._bounds = torch.zeros(2, self.N_DIMS)
        self._bounds[1] = 1.0

        self._train_X: list[list[float]] = []  # normalised inputs
        self._train_Y: list[float] = []         # negated Delta E 2000

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(self, volumes: list[float], delta_e_2000: float) -> None:
        """
        Record a new observation.

        Args:
            volumes: [R_vol, G_vol, B_vol, water_vol] in µL from the last protocol run.
            delta_e_2000: Measured Delta E 2000 for those volumes.
        """
        if len(volumes) == 3:
            # Backward compatibility with older RGB-only observations.
            inferred_water = self.total_volume - sum(float(v) for v in volumes)
            volumes = [*volumes, inferred_water]
        if len(volumes) != self.N_DIMS:
            raise ValueError(
                f"Expected {self.N_DIMS} volumes [R,G,B,water], got {len(volumes)}"
            )
        self._train_X.append([v / self.total_volume for v in volumes])
        self._train_Y.append(-delta_e_2000)

    def suggest(self, method: str = "bo") -> SuggestionResult:
        """
        Suggest the next (R_vol, G_vol, B_vol, water_vol) in uL.

        BO mode uses BoTorch ``optimize_acqf()``. The method argument is accepted
        so colour-mixing BO and LLM optimizers expose the same public interface.

        Returns:
            SuggestionResult with validated volumes and no LLM reasoning.

        Raises:
            RuntimeError: If called before any observations have been recorded.
            ValueError: If method is not ``"bo"``.
        """
        if not self._train_X:
            raise RuntimeError("No observations recorded. Call observe() first.")

        method = method.lower().strip()
        if method != "bo":
            raise ValueError(f"Unsupported suggestion method for BO optimizer: {method}")

        return self._suggest_bo()

    def _suggest_bo(self) -> SuggestionResult:
        """BO suggestion using BoTorch ``optimize_acqf()``."""
        train_X = torch.tensor(self._train_X, dtype=torch.double)
        train_Y = torch.tensor(self._train_Y, dtype=torch.double).unsqueeze(-1)

        model = self._fit_model(train_X, train_Y)
        acquisition = self._build_acquisition(model, train_Y)

        candidate, _ = optimize_acqf(
            acq_function=acquisition,
            bounds=self._bounds,
            q=1,
            num_restarts=self.num_restarts,
            raw_samples=self.raw_samples,
            equality_constraints=self._EQUALITY_CONSTRAINTS,
        )

        volumes = self._denormalise_and_constrain(candidate)
        return SuggestionResult(volumes=volumes, optimizer="BO")

    @property
    def n_observations(self) -> int:
        """Number of observations recorded so far."""
        return len(self._train_X)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fit_model(self, train_X: torch.Tensor, train_Y: torch.Tensor) -> SingleTaskGP:
        """
        Fit a SingleTaskGP surrogate on all observations.

        Args:
            train_X: Normalised input tensor, shape (n, 4).
            train_Y: Negated Delta E 2000 tensor, shape (n, 1).

        Returns:
            Fitted SingleTaskGP.
        """
        model = SingleTaskGP(train_X, train_Y)
        mll = ExactMarginalLogLikelihood(model.likelihood, model)
        fit_gpytorch_mll(mll)
        return model

    def _denormalise_and_constrain(self, candidate: torch.Tensor) -> list[float]:
        """
        Convert a normalised candidate back to µL.

        The equality constraint x1 + x2 + x3 + x4 = 1 is already enforced by
        optimize_acqf, so the candidate should sum to 1 in normalised space.
        The rescaling step below is a numerical safety clip only.

        Args:
            candidate: Optimised candidate, shape (1, 4), values in [0, 1]
                       satisfying x1 + x2 + x3 + x4 = 1.

        Returns:
            [R_vol, G_vol, B_vol, water_vol] in µL summing to total_volume.
        """
        volumes = candidate.squeeze() * self.total_volume
        # Safety clip: re-normalise if floating-point drift breaks the sum
        total = volumes.sum().item()
        if abs(total - self.total_volume) > 1e-3:
            volumes = volumes / total * self.total_volume
        return volumes.tolist()

    @abstractmethod
    def _build_acquisition(self, model: SingleTaskGP, train_Y: torch.Tensor):
        """Build and return the acquisition function for this optimizer variant."""


# ---------------------------------------------------------------------------
# Bayesian Optimization — Expected Improvement
# ---------------------------------------------------------------------------

class SOCM_BOEI(SOCM_BO):
    """
    Bayesian Optimizer using Expected Improvement (LogEI) acquisition.

    Best for most cases — balances exploration and exploitation.
    Selects candidates most likely to improve over the current best observation.

    Args:
        total_volume (float): Total well volume in µL.
        xi (float): Exploration bonus added to the current best observed value
            before computing EI.  ``xi > 0`` encourages more exploration;
            ``xi = 0`` is pure exploitation-focused EI.  Default: ``0.01``.
        num_restarts (int): Restarts for acquisition optimisation. Default: 10.
        raw_samples (int): Raw samples for initialisation. Default: 64.

    Example:
        optimizer = SOCM_BOEI(total_volume=300.0, xi=0.01)
        for volumes, delta_e_2000 in x_init_results:
            optimizer.observe(volumes, delta_e_2000)
        next_volumes = optimizer.suggest().volumes
    """

    def __init__(
        self,
        total_volume: float,
        xi: float = 0.01,
        num_restarts: int = 10,
        raw_samples: int = 64,
    ) -> None:
        super().__init__(
            total_volume=total_volume,
            num_restarts=num_restarts,
            raw_samples=raw_samples,
        )
        self.xi = xi

    def _build_acquisition(
        self, model: SingleTaskGP, train_Y: torch.Tensor
    ) -> LogExpectedImprovement:
        """
        Build a LogExpectedImprovement acquisition function.

        ``xi`` is added to the current best so that EI targets improvement
        beyond ``best_f + xi``, controlling the exploration–exploitation trade-off.

        Args:
            model: Fitted SingleTaskGP surrogate.
            train_Y: Negated Delta E 2000 observations, shape (n, 1).

        Returns:
            LogExpectedImprovement acquisition function.
        """
        return LogExpectedImprovement(model=model, best_f=train_Y.max() + self.xi)


# ---------------------------------------------------------------------------
# Bayesian Optimization — Lower Confidence Bound
# ---------------------------------------------------------------------------

class SOCM_BOLCB(SOCM_BO):
    """
    Bayesian Optimizer using Lower Confidence Bound (UCB) acquisition.

    More explorative than EI — useful when the Delta E 2000 landscape is uncertain or noisy.
    Higher beta increases exploration; lower beta increases exploitation.

    Args:
        total_volume (float): Total well volume in µL.
        beta (float): Exploration weight. Default: 1.0.
        num_restarts (int): Restarts for acquisition optimisation. Default: 10.
        raw_samples (int): Raw samples for initialisation. Default: 64.

    Example:
        optimizer = SOCM_BOLCB(total_volume=300.0, beta=1.0)
        for volumes, delta_e_2000 in x_init_results:
            optimizer.observe(volumes, delta_e_2000)
        next_volumes = optimizer.suggest().volumes
    """

    def __init__(
        self,
        total_volume: float,
        beta: float = 1.0,
        num_restarts: int = 10,
        raw_samples: int = 64,
    ) -> None:
        super().__init__(total_volume, num_restarts, raw_samples)
        self.beta = beta

    def _build_acquisition(
        self, model: SingleTaskGP, train_Y: torch.Tensor
    ) -> UpperConfidenceBound:
        """
        Build an UpperConfidenceBound acquisition function.

        Args:
            model: Fitted SingleTaskGP surrogate.
            train_Y: Negated Delta E 2000 observations (unused — UCB does not need best_f).

        Returns:
            UpperConfidenceBound acquisition function.
        """
        return UpperConfidenceBound(model=model, beta=self.beta)


# ---------------------------------------------------------------------------
# Colour mixing — LLM (single objective: minimise Delta E 2000)
# ---------------------------------------------------------------------------

class SOCM_LLM:
    """
    Single-objective LLM optimizer for RGB colour mixing: minimise Delta E 2000 vs a
    target colour. Suggests the next ``(R_vol, G_vol, B_vol, water_vol)`` via OpenRouter.

    Args:
        model: OpenRouter model identifier (e.g. ``OPENROUTER_MODELS["gpt-4o"]``).
        target_colour: Target RGB ``(R, G, B)``, values 0–255.
        total_volume: Total well volume in µL; suggested volumes must sum to this.
        api_key: OpenRouter API key; falls back to ``OPENROUTER_API_KEY``.
        max_retries: Re-prompt attempts if JSON or sum constraint fails.

    Example:
        optimizer = SOCM_LLM(
            model=OPENROUTER_MODELS["gpt-4o"],
            target_colour=(180, 60, 40),
            total_volume=300.0,
        )
        for volumes, rgb, delta_e_2000 in x_init_results:
            optimizer.observe(volumes, rgb, delta_e_2000)
        next_volumes = optimizer.suggest().volumes
    """

    def __init__(
        self,
        model: str,
        target_colour: tuple[int, int, int],
        total_volume: float,
        api_key: str | None = None,
        max_retries: int = 6,
    ) -> None:
        self.model = model
        self.target_colour = target_colour
        self.total_volume = total_volume
        self.max_retries = max_retries

        base_url = os.environ.get("OPENROUTER_BASE_URL")
        if not base_url:
            raise EnvironmentError(
                "OPENROUTER_BASE_URL is not set. Add it to your local .env file."
            )

        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key or os.environ["OPENROUTER_API_KEY"],
            timeout=120.0,
        )

        # Each entry: {"iteration": int, "volumes": [R,G,B,water], "rgb": (R,G,B), "delta_e_2000": float}
        self._history: list[dict] = []
        self.last_reasoning: str | None = None

    def observe(
        self,
        volumes: list[float],
        mixed_rgb: tuple[int, int, int],
        delta_e_2000: float,
    ) -> None:
        """Record one iteration: volumes used, measured mixed RGB, and Delta E 2000."""
        if len(volumes) == 3:
            inferred_water = self.total_volume - sum(float(v) for v in volumes)
            volumes = [*volumes, inferred_water]
        if len(volumes) != 4:
            raise ValueError(f"Expected 4 volumes [R,G,B,water], got {len(volumes)}")
        self._history.append({
            "iteration": len(self._history) + 1,
            "volumes": volumes,
            "rgb": mixed_rgb,
            "delta_e_2000": delta_e_2000,
        })

    def suggest(self, method: str = "llm") -> SuggestionResult:
        """
        Ask the LLM for the next ``(R_vol, G_vol, B_vol, water_vol)`` in uL
        and return validated volumes plus report reasoning.
        """
        method = method.lower().strip()
        if method != "llm":
            raise ValueError(f"Unsupported suggestion method for LLM optimizer: {method}")
        return self._suggest_llm()

    def _suggest_llm(self) -> SuggestionResult:
        """LLM suggestion with validated numeric volumes plus report reasoning."""
        volumes, reasoning = self.suggest_with_reasoning()
        return SuggestionResult(
            volumes=volumes,
            optimizer="LLM",
            llm_reasoning=reasoning,
        )

    def suggest_with_reasoning(self) -> tuple[list[float], str]:
        """
        Ask for one strict JSON object containing numeric volumes and concise reasoning.

        Protocol generation still uses only the validated numeric volume fields;
        the reasoning field is recorded for reports and never drives liquid handling.
        """
        if not self._history:
            raise RuntimeError("No observations recorded. Call observe() first.")

        validation_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            prompt = self._build_prompt(validation_error=validation_error)
            try:
                raw = self._call_model(prompt)
                volumes, reasoning = self._parse_validate_and_reasoning(raw)
                self.last_reasoning = reasoning
                return volumes, reasoning
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                if attempt == self.max_retries:
                    raise ValueError(
                        f"LLM returned invalid volumes after {self.max_retries} attempts: {exc}"
                    ) from exc
                validation_error = str(exc)

    @property
    def n_observations(self) -> int:
        return len(self._history)

    def _build_prompt(self, *, validation_error: str | None = None) -> str:
        r_t, g_t, b_t = self.target_colour
        lines = [
            "# RGB colour mixing optimization (single objective: Delta E 2000)",
            "",
            "You are helping optimize an RGB colour mixing experiment.",
            f"- Target colour (R, G, B): ({r_t}, {g_t}, {b_t})",
            (
                f"- Total volume per well: {self.total_volume} µL "
                "(R_vol + G_vol + B_vol + water_vol must equal this)"
            ),
            "",
            "## History",
            "| Iteration | R_vol (µL) | G_vol (µL) | B_vol (µL) | water_vol (µL) | Mixed RGB | Delta E 2000 |",
            "|-----------|------------|------------|------------|----------------|-----------|--------------|",
        ]
        for e in self._history:
            r, g, b, w = e["volumes"]
            mr, mg, mb = e["rgb"]
            lines.append(
                f"| {e['iteration']} | {r:.1f} | {g:.1f} | {b:.1f} | {w:.1f} "
                f"| ({mr}, {mg}, {mb}) | {e['delta_e_2000']:.4f} |"
            )
        lines += [
            "",
            "## What to return",
            "Suggest the next (R_vol, G_vol, B_vol, water_vol) in µL that you expect will **reduce Delta E 2000**.",
            f"Volumes must sum to exactly {self.total_volume} µL (±1 µL).",
            "Include a concise reason for this numeric suggestion in the same JSON object.",
            "The reasoning is for the report only; the protocol will use only the validated volume fields.",
            "Reply with JSON only, no markdown fences or extra text:",
            (
                '{"R_vol": <number>, "G_vol": <number>, "B_vol": <number>, '
                '"water_vol": <number>, "reasoning": "<1-3 concise sentences>"}'
            ),
        ]
        if validation_error:
            lines += [
                "",
                "## Fix your previous reply",
                f"The last response was invalid: {validation_error}",
                "Reply again with one JSON object only; it must contain R_vol, "
                "G_vol, B_vol, water_vol, and reasoning. Volumes must sum to "
                f"{self.total_volume} µL (±1 µL).",
            ]
        return "\n".join(lines)

    def _build_reasoning_prompt(self, volumes: list[float]) -> str:
        if len(volumes) == 3:
            volumes = [*volumes, self.total_volume - sum(float(v) for v in volumes)]
        r, g, b, w = volumes
        lines = [   
            "# RGB colour mixing optimization reasoning",
            "",
            "Explain concisely why this validated next mix was suggested.",
            f"- Target colour (R, G, B): {self.target_colour}",
            f"- Suggested volumes (R, G, B, water uL): ({r:.4g}, {g:.4g}, {b:.4g}, {w:.4g})",
            "",
            "Use the experiment history below. Mention the colour-direction logic and Delta E 2000 trend.",
            "Keep the answer to 1-3 concise sentences for a markdown report.",
            "",
            "## History",
        ]
        for e in self._history:
            history_volumes = tuple(round(float(v), 4) for v in e["volumes"])
            lines.append(
                f"- Iteration {e['iteration']}: volumes={history_volumes}, "
                f"mixed_rgb={e['rgb']}, delta_e_2000={float(e['delta_e_2000']):.4f}"
            )
        return "\n".join(lines)

    def explain_suggestion(self, volumes: list[float]) -> str:
        """Return concise LLM reasoning for a validated numeric suggestion."""
        try:
            reasoning = self._call_model(self._build_reasoning_prompt(volumes)).strip()
        except Exception as exc:
            reasoning = f"Reasoning unavailable: {exc}"
        self.last_reasoning = reasoning
        return reasoning

    def _call_model(self, prompt: str) -> str:
        """
        Send a prompt to the OpenRouter model and return the raw response text.

        Args:
            prompt: Full prompt string.

        Returns:
            Raw text content from the model response.
        """
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return _response_content_to_text(response.choices[0].message.content)

    def _parse_and_validate(self, response: str) -> list[float]:
        """
        Parse the model's JSON response and validate the volume constraint.

        Args:
            response: Raw model response, expected to contain JSON.

        Returns:
            [R_vol, G_vol, B_vol, water_vol] in µL.

        Raises:
            json.JSONDecodeError: If the response is not valid JSON.
            KeyError: If required keys are missing.
            ValueError: If volumes do not sum to total_volume (±1 µL tolerance).
        """
        cleaned = _extract_first_json_object_text(response)
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError(
                "Expected a JSON object with R_vol, G_vol, B_vol, and water_vol."
            )
        return self._validate_llm_suggestion(
            [data["R_vol"], data["G_vol"], data["B_vol"], data["water_vol"]]
        )

    def _parse_validate_and_reasoning(self, response: str) -> tuple[list[float], str]:
        """
        Parse one JSON response containing both volumes and report reasoning.

        Returns:
            ``([R_vol, G_vol, B_vol, water_vol], reasoning)``. Only the volume
            fields are used for protocol generation; reasoning is report text.
        """
        cleaned = _extract_first_json_object_text(response)
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError(
                "Expected a JSON object with R_vol, G_vol, B_vol, water_vol, and reasoning."
            )

        volumes = self._validate_llm_suggestion(
            [data["R_vol"], data["G_vol"], data["B_vol"], data["water_vol"]]
        )
        reasoning = str(data.get("reasoning", "")).strip()
        if not reasoning:
            raise ValueError("LLM response must include a non-empty reasoning field.")
        return volumes, reasoning

    def _validate_llm_suggestion(self, suggestion: list[float]) -> list[float]:
        """
        Validate LLM output and return constrained RGBy volumes in uL.

        The LLM may provide ratios or raw volumes. Either form is normalised and
        rescaled to ``self.total_volume`` after basic numeric safety checks.
        """
        if suggestion is None:
            raise ValueError("LLM response does not contain a numeric suggestion.")
        if len(suggestion) != 4:
            raise ValueError(
                f"LLM suggestion must contain 4 values: R, G, B, water. Got {suggestion}"
            )

        values = [float(x) for x in suggestion]
        if any(not math.isfinite(x) for x in values):
            raise ValueError(f"LLM suggestion contains non-finite values: {values}")
        if any(x < 0 for x in values):
            raise ValueError(f"LLM suggestion contains negative values: {values}")

        total = sum(values)
        if total <= 0:
            raise ValueError(f"LLM suggestion sum must be positive. Got {values}")

        ratios = [x / total for x in values]
        return [x * self.total_volume for x in ratios]


LLMOptimizer = SOCM_LLM


# ---------------------------------------------------------------------------
# Viscosity optimization — LLM (single objective)
# ---------------------------------------------------------------------------

class SOVH_LLM:
    """
    Single-objective LLM optimizer for viscosity / transfer tuning via OpenRouter.
    Minimise one scalar score (e.g. absolute transfer error), optionally using the
    structured **volume + flowrate** prompt when ``param_bounds`` is only ``volume``.

    **Single-parameter ``volume`` (recommended for aspiration-volume tuning):**
    Uses a structured prompt: per-iteration results (mass, actual volume, signed
    error), full **history** of prior iterations, constant **flowrate**, and
    explicit instructions to use **signed error** (positive → increase volume,
    negative → decrease). Call :meth:`observe` with the optional measurement
    fields so each history block matches the experiment report.

    **Multiple parameters (still single objective):** Generic prompt with bounds
    and JSON for all names; one primary metric ``absolute_error``.

    Args:
        model: OpenRouter model id (e.g. ``OPENROUTER_MODELS["gpt-4o"]``).
        param_bounds: ``(name, min, max)`` per tunable parameter.
        api_key: OpenRouter API key; falls back to ``OPENROUTER_API_KEY``.
        max_retries: Re-prompt attempts on invalid JSON or out-of-range values.
        sample_name: Optional label included in the prompt (e.g. glycerol sample id).
        target_volume_ul: Target transfer volume (µL) for the experiment (shown in prompt).
        flowrate_display: Constant flow rate description for all iterations, e.g.
            ``\"50 µL/s\"`` or ``\"default\"``. Shown as fixed while volume varies.

    Example (volume-only):
        opt = SOVH_LLM(
            model=OPENROUTER_MODELS["gpt-4o"],
            param_bounds=[("volume", 10.0, 200.0)],
            target_volume_ul=100.0,
            flowrate_display="50 µL/s",
        )
        opt.observe(
            {"volume": 80.0},
            absolute_error=5.0,
            signed_error_ul=-5.0,
            relative_mass_change_mg=4.95,
            relative_volume_change_uL=95.0,
        )
        nxt = opt.suggest()  # {\"volume\": ...}
    """

    def __init__(
        self,
        model: str,
        param_bounds: list[tuple[str, float, float]],
        api_key: str | None = None,
        max_retries: int = 3,
        sample_name: str | None = None,
        target_volume_ul: float | None = None,
        flowrate_display: str | None = None,
    ) -> None:
        if not param_bounds:
            raise ValueError("param_bounds must contain at least one parameter.")
        self._names = [p[0] for p in param_bounds]
        if len(set(self._names)) != len(self._names):
            raise ValueError("Parameter names in param_bounds must be unique.")

        self._bounds = {p[0]: (float(p[1]), float(p[2])) for p in param_bounds}
        for lo, hi in self._bounds.values():
            if hi <= lo:
                raise ValueError("Each parameter requires max > min.")
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1.")

        self.model = model
        self.max_retries = max_retries
        self.sample_name = sample_name
        self.target_volume_ul = target_volume_ul
        self.flowrate_display = flowrate_display if flowrate_display is not None else "N/A"

        self._volume_transfer_prompt = len(self._names) == 1 and self._names[0] == "volume"

        base_url = os.environ.get("OPENROUTER_BASE_URL")
        if not base_url:
            raise EnvironmentError(
                "OPENROUTER_BASE_URL is not set. Add it to your local .env file."
            )

        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key or os.environ["OPENROUTER_API_KEY"],
            timeout=120.0,
        )

        self._history: list[dict[str, Any]] = []

    def observe(
        self,
        params: dict[str, float],
        absolute_error: float,
        *,
        signed_error_ul: float | None = None,
        relative_mass_change_mg: float | None = None,
        relative_volume_change_uL: float | None = None,
        error_interpretation: str | None = None,
    ) -> None:
        """
        Record one iteration: parameters used and measured errors.

        Args:
            params: Parameter values (physical units) for this run. For volume
                mode, include ``\"volume\"`` (µL).
            absolute_error: |measured − target| in µL.
            signed_error_ul: Signed error in µL (actual − target). Strongly
                recommended for volume mode; drives the LLM adjustment rules.
            relative_mass_change_mg: Optional gravimetric mass change (mg) for the prompt.
            relative_volume_change_uL: Optional measured delivered volume (µL).
            error_interpretation: Optional short text; if omitted, a default line
                is derived from the sign of ``signed_error_ul`` when present.
        """
        row: dict[str, Any] = {
            "iteration": len(self._history) + 1,
            "params": dict(params),
            "absolute_error": float(absolute_error),
        }
        if signed_error_ul is not None:
            row["signed_error_ul"] = float(signed_error_ul)
        if relative_mass_change_mg is not None:
            row["relative_mass_change_mg"] = float(relative_mass_change_mg)
        if relative_volume_change_uL is not None:
            row["relative_volume_change_uL"] = float(relative_volume_change_uL)
        if error_interpretation is not None:
            row["error_interpretation"] = error_interpretation
        self._history.append(row)

    def suggest(self) -> dict[str, float]:
        """
        Ask the LLM for the next parameter dict.

        Returns:
            ``{name: value}`` with each value in ``[min, max]`` (± relative tolerance).

        Raises:
            RuntimeError: If there are no observations yet.
            ValueError: If the model returns invalid parameters after all retries.
        """
        if not self._history:
            raise RuntimeError("No observations recorded. Call observe() first.")

        validation_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            prompt = self._build_prompt(validation_error=validation_error)
            try:
                raw = self._call_model(prompt)
                return self._parse_and_validate(raw)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                if attempt == self.max_retries:
                    raise ValueError(
                        f"LLM returned invalid parameters after {self.max_retries} attempts: {exc}"
                    ) from exc
                validation_error = str(exc)

    @property
    def n_observations(self) -> int:
        return len(self._history)

    @staticmethod
    def _fmt_num(v: Any, decimals: int = 2, suffix: str = "") -> str:
        if v is None or (isinstance(v, float) and v != v):  # NaN
            return "N/A"
        try:
            return f"{float(v):.{decimals}f}{suffix}"
        except (TypeError, ValueError):
            return "N/A"

    @staticmethod
    def _default_error_interpretation(signed_ul: float | None) -> str:
        """Interpret ``signed_error = actual_volume - target_volume`` (µL)."""
        if signed_ul is None:
            return "Signed error not reported for this iteration."
        if signed_ul < 0:
            return (
                "Under-delivery (actual < target): signed error negative."
            )
        if signed_ul > 0:
            return (
                "Over-delivery (actual > target): signed error positive."
            )
        return "At target within reported precision."

    def _format_iteration_report(self, e: dict[str, Any]) -> list[str]:
        """One block matching the experiment report for a single iteration."""
        p = e["params"]
        vol = p.get("volume", "N/A")
        vol_str = self._fmt_num(vol, 2) if isinstance(vol, (int, float)) else str(vol)
        se = e.get("signed_error_ul")
        signed_str = self._fmt_num(se, 2) if se is not None else "N/A"
        tgt = self.target_volume_ul
        target_str = self._fmt_num(tgt, 2) if tgt is not None else "N/A"
        mass = e.get("relative_mass_change_mg")
        act_vol = e.get("relative_volume_change_uL")
        err_txt = e.get("error_interpretation")
        if err_txt is None:
            err_txt = self._default_error_interpretation(
                float(se) if se is not None else None
            )
        return [
            f"Parameters: volume={vol_str} µL, flowrate={self.flowrate_display} "
            f"(constant for all iterations)",
            "Results:",
            f"  - Mass change: {self._fmt_num(mass, 2)} mg",
            f"  - Target volume: {target_str} µL (goal to achieve)",
            f"  - Actual volume: {self._fmt_num(act_vol, 2)} µL",
            f"  - Signed error: {signed_str} µL (actual − target)",
            f"  - {err_txt}",
        ]

    def _build_prompt(self, *, validation_error: str | None = None) -> str:
        """Single user message: volume-transfer template or generic multi-parameter prompt."""
        if self._volume_transfer_prompt:
            return self._build_prompt_volume_transfer(validation_error=validation_error)
        return self._build_prompt_generic(validation_error=validation_error)

    def _build_prompt_volume_transfer(self, *, validation_error: str | None = None) -> str:
        """
        Prompt: current experiment (latest iteration), prior iterations as history,
        signed-error rules, next volume only (JSON ``{\"volume\": ...}``).
        """
        assert self._history
        current = self._history[-1]
        prior = self._history[:-1]

        cp = current["params"]
        cur_vol = cp.get("volume", "N/A")
        cur_vol_str = self._fmt_num(cur_vol, 2) if isinstance(cur_vol, (int, float)) else str(cur_vol)
        se = current.get("signed_error_ul")
        signed_str = self._fmt_num(se, 2) if se is not None else "N/A"
        tgt = self.target_volume_ul
        target_vol_str = self._fmt_num(tgt, 2) if tgt is not None else "N/A"

        history_lines: list[str] = []
        if not prior:
            history_lines.append("No prior iterations (this is the first completed run).")
        else:
            history_lines.append("Prior iterations (oldest first):")
            for e in prior:
                history_lines.append("")
                history_lines.append(f"--- Iteration {e['iteration']} ---")
                history_lines.extend(self._format_iteration_report(e))

        history_text = "\n".join(history_lines)

        current_block = "\n".join(self._format_iteration_report(current))

        lo, hi = self._bounds["volume"]
        lines = [
            "# Viscosity / aspiration volume optimization",
            "",
            "You tune **aspiration/setpoint volume** (µL) while **flow rate stays fixed**.",
            "Use the iteration history and **signed error** to propose the next volume to test.",
        ]
        if self.sample_name:
            lines.append(f"Sample: {self.sample_name}")
        lines += [
            "",
            "## Current experiment (latest completed run)",
            current_block,
            "",
            "## History",
            history_text,
            "",
            "## Task",
            "Based on this data, suggest the **next volume** to test. "
            f"The flow rate ({self.flowrate_display}) will remain constant.",
            "",
            "IMPORTANT: Use **signed error = actual volume − target volume** (µL):",
            "- If signed error is **negative** (under-delivery): suggest a **higher** aspirate/setpoint volume.",
            "- If signed error is **positive** (over-delivery): suggest a **lower** aspirate/setpoint volume.",
            "- Larger |signed error| usually warrants a larger step change (subject to bounds and viscosity).",
            "- Consider viscosity: viscous fluids may need different step sizes than Newtonian fluids.",
            "",
            f"Current volume used: {cur_vol_str} µL",
            f"Target volume: {target_vol_str} µL",
            f"Signed error (latest): {signed_str} µL",
            "",
            f"Suggest the **next volume** only, within [{lo}, {hi}] µL.",
            "Reply with JSON only, no markdown fences or extra text:",
            '{"volume": <number>}',
        ]
        if validation_error:
            lines += [
                "",
                "## Fix your previous reply",
                f"The last response was invalid: {validation_error}",
                f"Reply again with one JSON object only: {{\"volume\": <number>}} with volume in [{lo}, {hi}].",
            ]
        return "\n".join(lines)

    def _build_prompt_generic(self, *, validation_error: str | None = None) -> str:
        """Multi-parameter prompt: bounds, history, JSON for all tunable names."""
        lines = [
            "# Viscosity / transfer optimization (Opentrons)",
            "",
            "You are helping optimize liquid handling for viscous fluids. "
            "Tune the parameters to reduce absolute transfer error (µL).",
            "",
            "## Context",
        ]
        if self.sample_name:
            lines.append(f"- Sample: {self.sample_name}")
        if self.target_volume_ul is not None:
            lines.append(f"- Target transfer volume: {self.target_volume_ul} µL")
        if self.flowrate_display and self.flowrate_display != "N/A":
            lines.append(f"- Flow rate (constant if applicable): {self.flowrate_display}")
        lines += [
            "",
            "## Parameters (stay within min/max for each)",
        ]
        for name, (lo, hi) in self._bounds.items():
            lines.append(f"- {name}: [{lo}, {hi}]")
        lines += ["", "## History"]
        for e in self._history:
            p = e["params"]
            parts = [f"{k}={p[k]:.6g}" for k in self._names if k in p]
            line = f"- Iteration {e['iteration']}: " + ", ".join(parts)
            line += f" → abs_error={e['absolute_error']:.4f} µL"
            if "signed_error_ul" in e:
                line += f" (signed={e['signed_error_ul']:.4f} µL)"
            lines.append(line)
        example_keys = ", ".join(f'"{n}": <number>' for n in self._names)
        lines += [
            "",
            "## What to return",
            "Suggest the next parameter values, one per name above, each within its min/max.",
            "Reply with JSON only, no markdown fences or extra text:",
            "{" + example_keys + "}",
        ]
        if validation_error:
            lines += [
                "",
                "## Fix your previous reply",
                f"The last response was invalid: {validation_error}",
                "Reply again with one JSON object only; every parameter name must appear with a numeric value in range.",
            ]
        return "\n".join(lines)

    def _call_model(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return _response_content_to_text(response.choices[0].message.content)

    def _parse_and_validate(self, response: str) -> dict[str, float]:
        text = _extract_first_json_object_text(response)
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object mapping parameter names to floats.")

        out: dict[str, float] = {}
        for name in self._names:
            if name not in data:
                raise KeyError(f"Missing key {name!r}.")
            v = float(data[name])
            lo, hi = self._bounds[name]
            span = hi - lo
            tol = max(1e-6, 1e-6 * abs(span))
            if v < lo - tol or v > hi + tol:
                raise ValueError(
                    f"{name}={v} is outside [{lo}, {hi}]."
                )
            out[name] = min(hi, max(lo, v))
        return out


ViscosityLLMOptimizer = SOVH_LLM