import pandas as pd

from fleetmind.api.schemas import MachineReading
from fleetmind.config import (
    HIGH_PRIORITY_THRESHOLD,
    REVIEW_THRESHOLD,
)
from fleetmind.data.split import FEATURES


def to_model_frame(reading: MachineReading) -> pd.DataFrame:
    """Convert API input into the model's expected features."""

    values = {
        "Type": reading.machine_type,
        "Air temperature [K]": reading.air_temperature_k,
        "Process temperature [K]": (reading.process_temperature_k),
        "Rotational speed [rpm]": (reading.rotational_speed_rpm),
        "Torque [Nm]": reading.torque_nm,
        "Tool wear [min]": reading.tool_wear_min,
    }

    return pd.DataFrame([values], columns=FEATURES)


def classify_alert(score: float) -> str:
    """Assign an alert tier using frozen thresholds."""

    if score >= HIGH_PRIORITY_THRESHOLD:
        return "high_priority"

    if score >= REVIEW_THRESHOLD:
        return "review"

    return "no_alert"
