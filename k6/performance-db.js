import http from "k6/http";
import { sleep, check } from "k6";
import { Counter, Trend } from "k6/metrics";

// Metrics
let reqsDB = new Counter("db_reqs");
let latDB = new Trend("db_latency", true);

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
    db_only: {
      executor: "per-vu-iterations",
      vus: 10,
      iterations: 5000,
      exec: "dbOnly",
    },
  },
  thresholds: {
    db_latency: ["p(90)<200", "p(95)<250"],
  },
};

export function dbOnly() {
  const url = getFixedURL();
  const res = http.post(
    `${BASE_URL}/by_long`,
    JSON.stringify({ original_url: url }),
    AUTH_HEADER
  );

  reqsDB.add(1);
  latDB.add(res.timings.duration);

  check(res, { "status 200": (r) => r.status === 200 });
  sleep(0.01);
}

export function handleSummary(data) {
  const db = data.metrics["db_latency"]?.values || {};
  const dbReqs = data.metrics["db_reqs"]?.values.count || 0;

  const csvLines = [
    "Metric,DB-only,Redis Cache,Diff (% faster),Description",
    `Total User Requests,${dbReqs},0,-,Total number of requests in DB-only run`,
    `Avg Latency (ms),${
      db.avg?.toFixed(2) || "N/A"
    },-,-,Average time per request (DB-only)`,
    `Median Latency (ms),${
      db.med?.toFixed(2) || "N/A"
    },-,-,Median time per request (DB-only)`,
    `p(90) Latency (ms),${
      db["p(90)"]?.toFixed(2) || "N/A"
    },-,-,90th percentile latency (DB-only)`,
    `p(95) Latency (ms),${
      db["p(95)"]?.toFixed(2) || "N/A"
    },-,-,95th percentile latency (DB-only)`,
  ];

  const csvContent = csvLines.join("\n");
  console.log("\n===== DB-ONLY PERFORMANCE SUMMARY (CSV) =====\n");
  console.log(csvContent);

  return {
    "/results/db_only_summary.csv": csvContent,
  };
}
