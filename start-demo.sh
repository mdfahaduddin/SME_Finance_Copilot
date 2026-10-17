#!/usr/bin/env sh
# One-command local demo of SME Finance Copilot (macOS / Linux). Needs Docker running.
# Usage: ./start-demo.sh      (optional: DEMO_PORT=8090 ./start-demo.sh)
set -e
cd "$(dirname "$0")"
PORT="${DEMO_PORT:-8080}"
export DEMO_PORT="$PORT"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker, then try again."
  exit 1
fi

echo "Building and starting SME Finance Copilot. The first run takes a few minutes..."
docker compose -f docker-compose.demo.yml up --build -d

echo "Waiting for the app to answer..."
i=0
until curl -s -f -o /dev/null "http://localhost:$PORT/api/ready"; do
  i=$((i + 1))
  if [ "$i" -ge 90 ]; then
    echo "The app did not answer in time. Check the logs: docker compose -f docker-compose.demo.yml logs"
    exit 1
  fi
  sleep 2
done

URL="http://localhost:$PORT"
echo
echo "  ============================================================"
echo "    SME Finance Copilot is ready:  $URL"
echo "    Sign in with a demo account: Owner, Accountant or Viewer"
echo "  ============================================================"
echo "    Logs:  docker compose -f docker-compose.demo.yml logs -f"
echo "    Stop:  docker compose -f docker-compose.demo.yml down"
echo
(open "$URL" || xdg-open "$URL") >/dev/null 2>&1 || true
