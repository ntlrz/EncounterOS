from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CombatMetric:
    field: str
    max_field: str
    label: str
    source: str = "fallback"
    show_on_overlay: bool = True


HP_METRIC = CombatMetric("hp", "hpMax", "HP", "fallback")
SYSTEM_METRICS = {
    "drawsteel": CombatMetric("stamina", "staminaMax", "Stamina", "system"),
    "5e": CombatMetric("hp", "hpMax", "HP", "system"),
    "dnd5e": CombatMetric("hp", "hpMax", "HP", "system"),
    "dungeonsdragons5e": CombatMetric("hp", "hpMax", "HP", "system"),
    "callofcthulhu": CombatMetric("hp", "hpMax", "HP", "system"),
    "coc": CombatMetric("hp", "hpMax", "HP", "system"),
}


def normalize_system_name(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _explicit_metric(document: Mapping[str, Any]) -> CombatMetric | None:
    display = _as_mapping(document.get("combat_display"))
    primary = _as_mapping(display.get("primary"))
    if not primary:
        metric = _as_mapping(document.get("combat_metric"))
        primary = _as_mapping(metric.get("primary")) or metric
    field = primary.get("field")
    if not isinstance(field, str) or not field.strip():
        return None
    max_field = primary.get("max_field")
    label = primary.get("label")
    field = field.strip()
    if not isinstance(max_field, str) or not max_field.strip():
        max_field = f"{field}Max"
    if not isinstance(label, str) or not label.strip():
        label = field
    return CombatMetric(field, max_field.strip(), label.strip(), "explicit")


def _secondary_metric_metadata(document: Mapping[str, Any]) -> Mapping[str, Any]:
    display = _as_mapping(document.get("combat_display"))
    secondary = _as_mapping(display.get("secondary"))
    if not secondary:
        metric = _as_mapping(document.get("combat_metric"))
        secondary = _as_mapping(metric.get("secondary"))
    return secondary


def _explicit_secondary_metric(
    document: Mapping[str, Any],
    primary: CombatMetric | None = None,
) -> CombatMetric | None:
    secondary = _secondary_metric_metadata(document)
    field = secondary.get("field")
    if not isinstance(field, str) or not field.strip():
        return None
    max_field = secondary.get("max_field")
    label = secondary.get("label")
    show_on_overlay = secondary.get("show_on_overlay", True)
    field = field.strip()
    if not isinstance(max_field, str) or not max_field.strip():
        return None
    max_field = max_field.strip()
    if field == max_field:
        return None
    if primary and (field == primary.field or field == primary.max_field or max_field == primary.max_field):
        return None
    if show_on_overlay is not True and show_on_overlay is not False:
        return None
    if not isinstance(label, str) or not label.strip():
        label = field
    return CombatMetric(field, max_field, label.strip(), "explicit", show_on_overlay)


def resolve_combat_metric(
    combatant: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> CombatMetric:
    context = context or {}
    explicit = _explicit_metric(combatant) or _explicit_metric(context)
    if explicit:
        return explicit

    for value in (combatant.get("system"), context.get("system")):
        key = normalize_system_name(value)
        if key in SYSTEM_METRICS:
            return SYSTEM_METRICS[key]

    if "stamina" in combatant and "hp" not in combatant:
        return CombatMetric("stamina", "staminaMax", "Stamina", "inferred")
    if "staminaMax" in combatant and "stamina" in combatant:
        return CombatMetric("stamina", "staminaMax", "Stamina", "inferred")
    if "hp" in combatant or "hpMax" in combatant:
        return HP_METRIC
    return HP_METRIC


def resolve_secondary_combat_metric(
    combatant: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> CombatMetric | None:
    context = context or {}
    primary = resolve_combat_metric(combatant, context)
    return _explicit_secondary_metric(combatant, primary) or _explicit_secondary_metric(context, primary)


def secondary_metric_warning(
    combatant: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> str | None:
    context = context or {}
    source = combatant if _secondary_metric_metadata(combatant) else context
    secondary = _secondary_metric_metadata(source)
    if not secondary:
        return None
    if resolve_secondary_combat_metric(combatant, context):
        return None
    name = combatant.get("name") or combatant.get("id") or "combatant"
    return f"Ignored invalid secondary combat metric metadata for {name}."


def metric_conflict_warning(combatant: Mapping[str, Any], metric: CombatMetric) -> str | None:
    if (
        metric.field == "stamina"
        and "stamina" in combatant
        and ("hp" in combatant or "hpMax" in combatant)
    ):
        name = combatant.get("name") or combatant.get("id") or "combatant"
        return (
            f"Legacy combat metric conflict for {name}: Stamina is authoritative; "
            "retained hp/hpMax fields were left unchanged."
        )
    return None


def coerce_metric_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def metric_values(combatant: Mapping[str, Any], metric: CombatMetric | None = None) -> tuple[int, int]:
    metric = metric or resolve_combat_metric(combatant)
    current = max(0, coerce_metric_int(combatant.get(metric.field), 0))
    maximum = combatant.get(metric.max_field)
    if maximum is None:
        maximum = current if current > 0 else 1
    maximum = max(1, coerce_metric_int(maximum, 1))
    return min(current, maximum), maximum


def initialize_live_metric_fields(
    combatant: dict[str, Any],
    metric: CombatMetric | None = None,
    context: Mapping[str, Any] | None = None,
) -> CombatMetric:
    metric = metric or resolve_combat_metric(combatant, context)
    current = combatant.get(metric.field)
    if current is None:
        current = 1
        combatant[metric.field] = current
    current = max(1, coerce_metric_int(current, 1))
    if combatant.get(metric.max_field) is None:
        combatant[metric.max_field] = current
    return metric
