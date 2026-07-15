from telemetry_lab.simulator import FaultType, TelemetrySample, run_scenario


def main() -> None:
    samples = (
        TelemetrySample("charger-1", 72.5, 1000),
        TelemetrySample("charger-2", 110.0, 1100),
    )
    print(run_scenario(samples, FaultType.CORRUPT))


if __name__ == "__main__":
    main()
