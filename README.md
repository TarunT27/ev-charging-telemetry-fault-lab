# EV Charging Telemetry Fault-Injection Lab

Small diagnostics prototype for applying repeatable faults to EV charging telemetry.

## Included now

- Immutable telemetry samples
- Timeout, delay, and corrupted-value faults
- Basic telemetry validation and scenario counters
- Unit/integration-style tests and a minimal Docker image

This is an initial prototype. Later work will add TCP streams, recorded datasets, and richer diagnostics reports.

## Run

```bash
python main.py
python -m unittest discover -s tests -p "test_*.py"
```
