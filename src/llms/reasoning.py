"""
Unified reasoning effort mapper.

Maps abstract levels ("low", "medium", "high") to provider-specific parameters.
Detection-based: checks which reasoning keys exist in the model's parameters/extra_body
from models.json, then adjusts values for those specific keys.
"""

REASONING_LEVELS = ("low", "medium", "high")

# Anthropic thinking budgets per level
_ANTHROPIC_BUDGETS = {"low": 5000, "medium": 10000, "high": 32000}

# Gemini numeric thinking budgets per level (for thinking_budget pattern)
_GEMINI_BUDGETS = {"low": 1024, "medium": 8192, "high": 32768}


def apply_reasoning_effort(
    level: str,
    parameters: dict,
    extra_body: dict,
) -> tuple[dict, dict]:
    """Apply reasoning effort override to model parameters.

    Detects which reasoning pattern the model uses by checking existing keys
    in parameters and extra_body, then adjusts their values.

    Args:
        level: One of "low", "medium", "high".
        parameters: Model parameters dict (will be mutated).
        extra_body: Extra body dict (will be mutated).

    Returns:
        Tuple of (parameters, extra_body) — same objects, mutated in place.
    """
    if level not in REASONING_LEVELS:
        return parameters, extra_body

    # --- parameters-based patterns ---

    # OpenAI: parameters.reasoning.effort
    if "reasoning" in parameters:
        if isinstance(parameters["reasoning"], dict):
            parameters["reasoning"]["effort"] = level
        else:
            parameters["reasoning"] = {"effort": level}

    # Anthropic adaptive: control via output_config.effort
    elif "output_config" in parameters or (
        "thinking" in parameters
        and isinstance(parameters["thinking"], dict)
        and parameters["thinking"].get("type") == "adaptive"
    ):
        parameters.setdefault("output_config", {})["effort"] = level

    # Anthropic enabled: control via budget_tokens
    elif "thinking" in parameters:
        if isinstance(parameters["thinking"], dict):
            parameters["thinking"]["budget_tokens"] = _ANTHROPIC_BUDGETS[level]
        else:
            parameters["thinking"] = {
                "type": "enabled",
                "budget_tokens": _ANTHROPIC_BUDGETS[level],
            }

    # Gemini 3.x: parameters.thinking_level
    elif "thinking_level" in parameters:
        parameters["thinking_level"] = level

    # Gemini 2.x: parameters.thinking_budget (numeric)
    elif "thinking_budget" in parameters:
        parameters["thinking_budget"] = _GEMINI_BUDGETS[level]

    # vLLM / Groq / Cerebras: parameters.reasoning_effort
    elif "reasoning_effort" in parameters:
        parameters["reasoning_effort"] = level

    # --- extra_body patterns ---

    # Volcengine / Doubao: extra_body.thinking.type
    if "thinking" in extra_body:
        if isinstance(extra_body["thinking"], dict):
            extra_body["thinking"]["type"] = "disabled" if level == "low" else "enabled"
        else:
            extra_body["thinking"] = {
                "type": "disabled" if level == "low" else "enabled"
            }

    # Dashscope / Qwen: extra_body.enable_thinking
    if "enable_thinking" in extra_body:
        extra_body["enable_thinking"] = level != "low"

    return parameters, extra_body
