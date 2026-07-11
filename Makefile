# Paritran developer entry points (SPEC sections 11, 17, 20).
COMPOSE ?= docker compose
PORTS   := 8090 8081 5433 9090 3001

.PHONY: bootstrap up down logs test preflight

bootstrap:
	./scripts/bootstrap_env.sh

up: bootstrap
	$(COMPOSE) up -d --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

test:
	./scripts/ci_local.sh

# Demo-day preflight (SPEC section 20): ports free or held by our own Docker stack,
# host Ollama answering, compose file valid.
preflight:
	@ok=1; \
	for p in $(PORTS); do \
		pids="$$(lsof -nP -iTCP:$$p -sTCP:LISTEN -t 2>/dev/null || true)"; \
		if [ -z "$$pids" ]; then \
			echo "port $$p: free"; \
		else \
			owners="$$(ps -o comm= -p $$pids 2>/dev/null | sort -u | tr '\n' ' ')"; \
			case "$$owners" in \
				*[Dd]ocker*|*[Oo]rb[Ss]tack*|*vpnkit*) echo "port $$p: ours ($$owners)";; \
				*) echo "port $$p: BUSY ($$owners)"; ok=0;; \
			esac; \
		fi; \
	done; \
	if ollama list >/dev/null 2>&1; then echo "ollama: reachable"; else echo "ollama: NOT reachable (ollama list failed)"; ok=0; fi; \
	if $(COMPOSE) config -q; then echo "compose config: valid"; else echo "compose config: INVALID"; ok=0; fi; \
	[ "$$ok" = "1" ] && echo "preflight: PASS" || { echo "preflight: FAIL"; exit 1; }
