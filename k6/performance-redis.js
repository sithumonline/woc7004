import http from "k6/http";
import { sleep, check } from "k6";
import { Counter, Trend } from "k6/metrics";

// Metrics
let reqsRedis = new Counter("redis_reqs");
let latRedis = new Trend("redis_latency", true);

// Configuration
const NUM_FIXED_URLS = 50000;
const BASE_URL = "http://web:8080/api/links";
const AUTH_HEADER = {
  headers: { Authorization: "CHANGEME", "Content-Type": "application/json" },
};

function getFixedURL() {
  const id = Math.floor(Math.random() * NUM_FIXED_URLS) + 1;
  return `https://example.com/${id}`;
}

export let options = {
  scenarios: {
    redis_cache: {
      executor: "per-vu-iterations",
      vus: 10,
      iterations: 5000,
      exec: "redisCache",
    },
  },
  thresholds: {
    redis_latency: ["p(90)<50", "p(95)<100"],
  },
};

export function redisCache() {
  const url = getFixedURL();
  const res = http.post(
    `${BASE_URL}/redis`,
    JSON.stringify({ original_url: url }),
    AUTH_HEADER
  );

  reqsRedis.add(1);
  latRedis.add(res.timings.duration);

  check(res, { "status 200": (r) => r.status === 200 });
  sleep(0.01);
}

export function handleSummary(data) {
  const redis = data.metrics["redis_latency"]?.values || {};
  const redisReqs = data.metrics["redis_reqs"]?.values.count || 0;

  const csvLines = [
    "Metric,DB-only,Redis Cache,Diff (% faster),Description",
    `Total User Requests,0,${redisReqs},-,Total number of requests in Redis-only run`,
    `Avg Latency (ms),-,${
      redis.avg?.toFixed(2) || "N/A"
    },-,Average time per request (Redis-only)`,
    `Median Latency (ms),-,${
      redis.med?.toFixed(2) || "N/A"
    },-,Median time per request (Redis-only)`,
    `p(90) Latency (ms),-,${
      redis["p(90)"]?.toFixed(2) || "N/A"
    },-,90th percentile latency (Redis-only)`,
    `p(95) Latency (ms),-,${
      redis["p(95)"]?.toFixed(2) || "N/A"
    },-,95th percentile latency (Redis-only)`,
  ];

  const csvContent = csvLines.join("\n");
  console.log("\n===== REDIS-ONLY PERFORMANCE SUMMARY (CSV) =====\n");
  console.log(csvContent);

  return {
    "/results/redis_only_summary.csv": csvContent,
  };
}
