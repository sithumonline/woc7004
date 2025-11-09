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
	# Start energy tracking (run this in separate terminal for clearer logs) then run k6_db
	$(COMPOSE_CMD) exec -e K6_SERVICE=k6_db web python codecarbon/energy_run.py & \
	$(COMPOSE_CMD) run --rm k6_db

energy-redis:
	$(COMPOSE_CMD) exec -e K6_SERVICE=k6_redis web python codecarbon/energy_run.py & \
	$(COMPOSE_CMD) run --rm k6_redis

which-compose:
	@echo Using compose runner: $(COMPOSE_CMD)
