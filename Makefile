COMPOSE_FILE = docker-compose.yml

# Detect available compose runner: prefer podman-compose if present, else docker compose
PODMAN_COMPOSE_BIN := $(shell command -v podman-compose 2>/dev/null)
ifeq ($(PODMAN_COMPOSE_BIN),)
	COMPOSE_CMD := docker compose
else
	COMPOSE_CMD := podman-compose
endif

.PHONY: setup up migrate seed

# Full first-time setup (build + up + migrate)
setup:
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) down -v
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) up -d --build

	$(COMPOSE_CMD) exec web flask db downgrade base
	$(COMPOSE_CMD) exec web flask db upgrade

	$(COMPOSE_CMD) exec web python seed_redis.py
	@echo "✅ setup complete!"

loadtest:
	$(COMPOSE_CMD) run --rm k6

energy-baseline:
	$(COMPOSE_CMD) exec web python codecarbon/baseline_energy.py

energy-db:
	# Run DB-only k6 with integrated CodeCarbon tracking
	$(COMPOSE_CMD) exec web flask carbon start --scenario k6_db --force
	$(COMPOSE_CMD) run --rm k6_db
	$(COMPOSE_CMD) exec web flask carbon stop \
		--summary-csv /usr/src/app/k6/results/db_only_summary.csv \
		--write-json /usr/src/app/k6/results/energy_result_k6_db.json \
		--reason loadtest-db

energy-redis:
	$(COMPOSE_CMD) exec web flask carbon start --scenario k6_redis --force
	$(COMPOSE_CMD) run --rm k6_redis
	$(COMPOSE_CMD) exec web flask carbon stop \
		--summary-csv /usr/src/app/k6/results/redis_only_summary.csv \
		--write-json /usr/src/app/k6/results/energy_result_k6_redis.json \
		--reason loadtest-redis

energy-compare:
	# Compare DB vs Redis with baseline and write a CSV + JSON summary
	$(COMPOSE_CMD) exec web python codecarbon/compare_energy.py

which-compose:
	@echo Using compose runner: $(COMPOSE_CMD)
