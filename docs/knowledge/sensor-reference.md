# Sensor and feature terminology

Machine type is the categorical input L, M, or H. It is distinct from the registered asset identifier. The fitted model encodes machine type using categorical indicators.

## Temperatures and thermal gap

Air temperature and process temperature are both recorded in kelvins (K). Thermal gap is a derived feature calculated as process temperature minus air temperature. It is not a separately measured sensor channel. Keep the original temperature values and units for review.

## Speed, torque, and tool wear

Rotational speed is measured in revolutions per minute (RPM). Torque is measured in newton-metres (N·m). Tool wear is recorded in minutes in this dataset and inference form. The value is a model input, not a validated remaining lifetime or an equipment-specific replacement limit.
