import time
import pytest
from piclaw.metrics import MetricsDB, MetricPoint

def test_query_range_performance(tmp_path):
    db = MetricsDB(path=tmp_path / "perf.db", retention_s=3600)

    # Generate data
    num_metrics = 50
    num_points = 100

    start_time = time.time()
    points = []
    ts_base = int(time.time()) - 3600
    for i in range(num_metrics):
        metric_name = f"metric_{i}"
        for j in range(num_points):
            points.append(MetricPoint(metric_name, float(j), ts=ts_base + j))

    db.write_many(points)

    metric_names = [f"metric_{i}" for i in range(num_metrics)]

    # Test resolution > 0
    t0 = time.time()
    for _ in range(10):
        db.query_range(metric_names, since_s=3600, resolution=60)
    t1 = time.time()

    # Test resolution == 0
    t2 = time.time()
    for _ in range(10):
        db.query_range(metric_names, since_s=3600, resolution=0)
    t3 = time.time()

    print(f"Time for resolution=60: {t1 - t0:.4f}s")
    print(f"Time for resolution=0: {t3 - t2:.4f}s")
