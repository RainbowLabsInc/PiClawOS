import asyncio
import time

def sync_read():
    try:
        # Mocking sysfs read for benchmark environments if file is missing
        return int(open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8").read().strip()) / 1000
    except Exception:
        return 45.0

def _read_sysfs():
    try:
        return int(open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8").read().strip()) / 1000
    except Exception:
        return 45.0

async def async_read():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _read_sysfs)

async def measure_event_loop_latency(duration=2.0):
    """Measures the max delay between event loop cycles."""
    max_latency = 0
    start_time = time.perf_counter()
    while time.perf_counter() - start_time < duration:
        t0 = time.perf_counter()
        await asyncio.sleep(0)
        t1 = time.perf_counter()
        latency = t1 - t0
        if latency > max_latency:
            max_latency = latency
    return max_latency

async def load_test(func, is_async, duration=2.0):
    """Runs the function as fast as possible for the given duration."""
    start_time = time.perf_counter()
    count = 0
    while time.perf_counter() - start_time < duration:
        if is_async:
            await func()
        else:
            func()
            await asyncio.sleep(0) # yield to event loop so latency task can run
        count += 1
    return count

async def run_benchmark():
    print("Running Baseline Benchmark (Sync Read)...")
    latency_task = asyncio.create_task(measure_event_loop_latency(duration=2.0))
    load_task = asyncio.create_task(load_test(sync_read, is_async=False, duration=2.0))

    sync_max_latency = await latency_task
    sync_ops = await load_task

    print("Running Optimized Benchmark (Async Read)...")
    latency_task = asyncio.create_task(measure_event_loop_latency(duration=2.0))
    load_task = asyncio.create_task(load_test(async_read, is_async=True, duration=2.0))

    async_max_latency = await latency_task
    async_ops = await load_task

    print("\n--- Benchmark Results ---")
    print(f"Sync (Baseline): {sync_ops / 2.0:.2f} ops/sec, Max Latency: {sync_max_latency * 1000:.2f} ms")
    print(f"Async (Optimized): {async_ops / 2.0:.2f} ops/sec, Max Latency: {async_max_latency * 1000:.2f} ms")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
