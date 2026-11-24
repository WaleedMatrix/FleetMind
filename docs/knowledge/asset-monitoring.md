# Registered asset monitoring

The asset registry stores an explicit asset ID, display name, machine type, and optional location and description. The ID and machine type stay fixed after registration. Inference accepts an optional existing asset ID. The registered machine type must match the input type.

## Monitoring history

An asset's sensor history, score trend, and alert counts use readings explicitly assigned to that asset. Unassigned predictions remain in the dashboard audit log without being attributed to a machine. A registered asset with no readings has no monitoring history. Model alerts alone do not establish asset operating status.
