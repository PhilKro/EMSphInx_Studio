from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


STEP_SIZE_QUANTUM_UM = Decimal("0.0001")
BEAM_VOLTAGE_QUANTUM_KV = Decimal("0.1")


def normalize_step_size_um(value):
    """Round Oxford scan spacing to 0.0001 micrometres."""
    return float(
        Decimal(str(value)).quantize(STEP_SIZE_QUANTUM_UM, rounding=ROUND_HALF_UP)
    )


def format_step_size_um(value):
    """Return normalized scan spacing without binary-float noise."""
    normalized = Decimal(str(value)).quantize(
        STEP_SIZE_QUANTUM_UM, rounding=ROUND_HALF_UP
    )
    return format(normalized, "f")


def normalize_beam_voltage_kv(value):
    """Round Oxford accelerating voltage to the nearest 0.1 kV."""
    try:
        return float(
            Decimal(str(value)).quantize(
                BEAM_VOLTAGE_QUANTUM_KV, rounding=ROUND_HALF_UP
            )
        )
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Beam voltage must be numeric") from exc


def format_beam_voltage_kv(value):
    """Return normalized voltage with exactly one decimal place."""
    return f"{normalize_beam_voltage_kv(value):.1f}"


def beam_voltage_lookup_labels(value):
    """Return decimal and legacy integer labels used by SHT filenames."""
    decimal_label = format_beam_voltage_kv(value)
    compact_label = f"{normalize_beam_voltage_kv(value):g}"
    return tuple(dict.fromkeys((decimal_label, compact_label)))
