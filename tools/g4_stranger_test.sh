#!/usr/bin/env bash
# Gate G4: the stranger test. From a clean clone (fresh venv, no state),
# reproduce the G3 closed loop using only commands a README reader would run.
# Produces a full transcript (run under `bash -x`, tee'd by the caller).
#
# Environment assumptions (the "bring your own" parts a stranger has anyway):
#   * a reachable CARLA server (here: the custom all-maps build on :3001,
#     hence the in-image client wheel step from the README's custom-build note)
#   * an AlpaSim checkout at $ALPASIM with its own env (uv)
set -euxo pipefail

SOURCE_REPO=${SOURCE_REPO:-/tmp/alpasim-carla-public-audit/alpasim-carla}
CLONE=${CLONE:-/tmp/alpasim-carla-public-audit/alpasim-carla-stranger}
ALPASIM=${ALPASIM:-/tmp/alpasim-carla-public-audit/alpamayo-carla-sim2real/src/alpasim}
CARLA_PORT=${CARLA_PORT:-3001}
BRIDGE_PORT=${BRIDGE_PORT:-50052}
HOST_IP=$(hostname -I | awk '{print $1}')

# --- 1. clean clone + fresh venv ------------------------------------------
rm -rf "$CLONE"
git clone "$SOURCE_REPO" "$CLONE"
cd "$CLONE"
python3.10 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[dev]"

# --- 2. simulator-free test suite (no carla installed yet) -----------------
.venv/bin/pytest tests/ -m "not carla" -q

# --- 3. CARLA client wheel (README "custom CARLA builds" note) -------------
CID=$(docker create carla-build-allmaps:5-28-skyfix)
rm -rf /tmp/carla-dist-g4 && mkdir -p /tmp/carla-dist-g4
docker cp "$CID":/workspace/PythonAPI/carla/dist/. /tmp/carla-dist-g4
docker rm "$CID"
.venv/bin/pip install --quiet /tmp/carla-dist-g4/carla-0.9.16-cp310-cp310-linux_x86_64.whl

# --- 4. start the bridge from the clone ------------------------------------
pkill -f "alpasim-carla serve --port $BRIDGE_PORT" 2>/dev/null || true
nohup .venv/bin/alpasim-carla serve --port "$BRIDGE_PORT" \
  --scenes-dir scenes/g3 --backend carla \
  --carla-host 127.0.0.1 --carla-port "$CARLA_PORT" \
  --allow-pinhole-approximation > bridge.log 2>&1 < /dev/null &
for _ in $(seq 1 30); do
  ss -tln | grep -q ":$BRIDGE_PORT " && break
  sleep 1
done
ss -tln | grep ":$BRIDGE_PORT "

# --- 5. run AlpaSim against it (README quickstart command + run_method=NONE
#        compose pattern) ----------------------------------------------------
cd "$ALPASIM"
~/.local/bin/uv run --no-sync alpasim_wizard \
  --config-dir "$CLONE/configs_pkg/alpasim_carla_configs/configs" \
  deploy=local topology=1gpu driver=alpamayo1_5 renderer=carla \
  "wizard.external_services.renderer=[\"$HOST_IP:$BRIDGE_PORT\"]" \
  wizard.run_method=NONE \
  "wizard.log_dir=$CLONE/g4run" \
  wizard.baseport=17800 wizard.timeout=7200 \
  "services.driver.gpus=[1]" "services.runtime.gpus=[1]" \
  runtime.endpoints.renderer.n_concurrent_rollouts=1 \
  runtime.endpoints.driver.n_concurrent_rollouts=1 \
  runtime.endpoints.physics.n_concurrent_rollouts=1 \
  runtime.endpoints.controller.n_concurrent_rollouts=1 \
  runtime.endpoints.trafficsim.n_concurrent_rollouts=1 \
  runtime.endpoints.physics.skip=true \
  runtime.simulation_config.physics_update_mode=NONE \
  runtime.simulation_config.n_rollouts=1 \
  runtime.simulation_config.n_sim_steps=200 \
  runtime.simulation_config.control_timestep_us=100000 \
  runtime.simulation_config.force_gt_duration_us=2000000 \
  wizard.description=alpasim-carla-g4-stranger

cd "$CLONE/g4run"
timeout 3600 docker compose -f docker-compose.yaml --project-name alpasim-carla-g4 \
  up --no-build --exit-code-from runtime-0 --remove-orphans
docker compose -f docker-compose.yaml --project-name alpasim-carla-g4 \
  down -v --remove-orphans

# --- 6. validate the rollout the same way G3 was validated -----------------
cd "$CLONE"
.venv/bin/python tools/validate_rollout.py --run-dir g4run --out-dir g4out \
  --min-displacement 10
cat g4out/g3_summary.json

# --- teardown ---------------------------------------------------------------
pkill -f "alpasim-carla serve --port $BRIDGE_PORT" || true
echo "G4_STRANGER_TEST_PASS"
