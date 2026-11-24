"""Measure PostgreSQL connection and query latency."""

from time import perf_counter

from sqlalchemy import func, select, text

from fleetmind.db.database import SessionLocal
from fleetmind.db.models import PredictionHistory


def main():
    print("=== FLEETMIND DATABASE BENCHMARK ===")

    for iteration in range(1, 4):
        start = perf_counter()

        with SessionLocal() as session:
            session_created = perf_counter()

            session.execute(text("SELECT 1")).scalar_one()
            connection_ready = perf_counter()

            total = session.scalar(select(func.count(PredictionHistory.id)))
            count_finished = perf_counter()

            average_score = session.scalar(
                select(func.avg(PredictionHistory.failure_score))
            )
            average_finished = perf_counter()

            session.execute(
                select(
                    PredictionHistory.alert_level,
                    func.count(PredictionHistory.id),
                ).group_by(PredictionHistory.alert_level)
            ).all()
            grouping_finished = perf_counter()

        print(f"\nRun {iteration}")
        print(f"Session creation: {(session_created - start) * 1000:.2f} ms")
        print(
            f"Connection acquisition + SELECT 1: "
            f"{(connection_ready - session_created) * 1000:.2f} ms"
        )
        print(f"COUNT query: {(count_finished - connection_ready) * 1000:.2f} ms")
        print(f"AVG query: {(average_finished - count_finished) * 1000:.2f} ms")
        print(f"GROUP BY query: {(grouping_finished - average_finished) * 1000:.2f} ms")
        print(f"Total predictions: {total}")
        print(f"Average score: {average_score}")


if __name__ == "__main__":
    main()
