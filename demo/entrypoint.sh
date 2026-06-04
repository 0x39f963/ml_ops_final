set -eu

health_port="${DEMO_HEALTH_INTERNAL_PORT:-8502}"
ui_port="${DEMO_INTERNAL_PORT:-8501}"

uvicorn health:app --host 0.0.0.0 --port "$health_port" &
health_pid="$!"

cleanup() {
  kill "$health_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port "$ui_port" \
  --server.headless true \
  --browser.gatherUsageStats false
