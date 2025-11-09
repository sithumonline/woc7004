# Performance & Energy Testing: Redis vs Database

This project provides a simple setup to compare the performance of Redis caching against a database, including optional energy usage measurement using CodeCarbon.

## Prerequisites

- Docker or Podman (Compose is auto-detected by `make`)
- Make
- K6 runs inside a container (no local install required)

## Setup

Run the following command to set up the environment:

```bash
make setup
```

**What this does:**

- Starts PostgreSQL and Redis using Docker.
- Seeds Redis with initial data and URLs to simulate cached content.
- Prepares the database with necessary records.
- Ensures that both the database and Redis are ready for performance testing.

This setup ensures that the load tests can simulate realistic conditions where some requests can be served from Redis (cache) while others hit the database.

## Load Testing (Latency/Throughput)

After setup, run the performance tests with:

```bash
make loadtest
```

**What this does:**

- Runs K6 load tests that simulate multiple virtual users (VUs) making requests.
- Compares performance between requests served from Redis (cache) and requests served directly from the database.
- Uses the `per-vu-iterations` executor to simulate multiple requests per user.
- Collects metrics like response times, throughput (requests per second), and error rates.

This allows you to measure the performance difference between cached and non-cached requests under simulated load.

Note: The K6 scripts send an Authorization header of `CHANGEME`. Set `API_KEY=CHANGEME` in your `.env` file (or update the scripts/env to match).

## Results

Test results are stored in:

```bash
k6/results
```

You can analyze these results to see:

- How much faster Redis responds compared to the database.
- Whether caching reduces errors under load.
- Throughput improvements with Redis.

## Energy Benchmarking (DB-only vs Redis)

We provide make targets to collect energy consumption (via CodeCarbon) while running the two K6 scenarios separately. The Makefile auto-detects whether to use `podman-compose` or `docker compose`.

1. Baseline (idle) energy over a short fixed duration

```bash
make energy-baseline
```

2. DB-only scenario energy

```bash
make energy-db
```

3. Redis-only scenario energy

```bash
make energy-redis
```

Where it saves outputs (host paths):

- `k6/results/baseline_energy.json`
- `k6/results/db_only_summary.csv`
- `k6/results/redis_only_summary.csv`
- `k6/results/energy_result_k6_db.json`
- `k6/results/energy_result_k6_redis.json`

Quick per-request energy calculation (adjusted by baseline):

```python
import json, pathlib
r = pathlib.Path("k6/results")
with open(r/"baseline_energy.json") as f: baseline = json.load(f)
with open(r/"energy_result_k6_db.json") as f: db = json.load(f)
with open(r/"energy_result_k6_redis.json") as f: redis = json.load(f)

b_kwh = baseline.get("baseline_energy_kwh") or 0
def adjusted_wh_per_req(data):
	kwh = data.get("total_energy_kwh") or 0
	reqs = data.get("total_requests") or 1
	workload_kwh = max(kwh - b_kwh, 0)
	return workload_kwh * 1000 / reqs

print("DB-only adjusted Wh/req:", adjusted_wh_per_req(db))
print("Redis-only adjusted Wh/req:", adjusted_wh_per_req(redis))
```

Compose runner detection:

```bash
make which-compose
```

### EC2/Linux permission tip for K6 results

If K6 logs an error like: `permission denied` when writing `/results/*.csv`, ensure the host directory is writable by the container user. For example:

```bash
mkdir -p k6/results
sudo chown 1000:1000 k6/results    # or: chmod 0777 k6/results
```

Alternatively, switch the `/results` mount to a named volume in `docker-compose.yml`.

## Project Structure

- `Makefile` – Contains commands for setup (`make setup`) and load testing (`make loadtest`)
- `k6/` – Contains K6 load test scripts and results
- `db/` – Database setup and seed scripts
- `redis/` – Redis seed scripts
- `codecarbon/` – Energy measurement scripts (copied into the web image during `make setup`)

## Notes

- Make sure Docker is running before executing `make setup`.
- K6 scripts can be customized in the `k6/` folder if needed.
- The load test uses the `per-vu-iterations` executor to simulate realistic concurrent load. Adjust the number of VUs and iterations in the scripts to match your testing requirements.

## Example Usage

```bash
# Setup environment
make setup

# Run performance tests
make loadtest

# Check results
ls k6/results

# Baseline + energy for DB and Redis
make energy-baseline
make energy-db
make energy-redis
```

## Summary

This project allows you to quickly compare database queries versus cached data in Redis under simulated load conditions. By analyzing the results (latency + energy), you can:

- Identify performance bottlenecks
- Measure the impact of caching on response times
- Optimize your application for better scalability and energy efficiency
