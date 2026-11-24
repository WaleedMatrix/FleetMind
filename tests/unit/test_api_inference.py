from fleetmind.api.inference import (
    classify_alert,
    to_model_frame,
)
from fleetmind.api.schemas import MachineReading
from fleetmind.data.split import FEATURES


def test_sensor_readings_map_to_model_features():
    reading = MachineReading(
        machine_type="L",
        air_temperature_k=300.0,
        process_temperature_k=310.0,
        rotational_speed_rpm=1500,
        torque_nm=40.0,
        tool_wear_min=120,
    )

    frame = to_model_frame(reading)

    assert frame.shape == (1, 6)
    assert frame.columns.tolist() == FEATURES
    assert frame.iloc[0]["Type"] == "L"
    assert frame.iloc[0]["Torque [Nm]"] == 40.0


def test_alert_classification():
    assert classify_alert(0.10) == "no_alert"
    assert classify_alert(0.30) == "review"
    assert classify_alert(0.50) == "review"
    assert classify_alert(0.60) == "high_priority"
    assert classify_alert(0.90) == "high_priority"
