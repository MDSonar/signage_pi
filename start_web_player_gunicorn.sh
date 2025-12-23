#!/bin/bash
# Start Web Player with Gunicorn (Production Mode)

cd "$(dirname "$0")"

echo "=========================================="
echo "Starting Web Player with Gunicorn"
echo "=========================================="

# Configuration
WORKERS=2              # gthread: fewer workers, more threads
THREADS=8              # Threads per worker for IO-bound workloads
BIND="0.0.0.0:8080"
TIMEOUT=120            # 2 minutes (videos can be large)
LOG_LEVEL="info"
WORKER_CLASS="gthread" # Threads suit many concurrent TVs
KEEP_ALIVE=75          # TCP keep-alive seconds
BACKLOG=2048           # Pending connection queue size
WORKER_TMP_DIR="/dev/shm"  # Faster temp dir in RAM

# Start gunicorn
exec gunicorn \
    --workers $WORKERS \
    --threads $THREADS \
    --worker-class $WORKER_CLASS \
    --bind $BIND \
    --timeout $TIMEOUT \
    --keep-alive $KEEP_ALIVE \
    --backlog $BACKLOG \
    --worker-tmp-dir $WORKER_TMP_DIR \
    --log-level $LOG_LEVEL \
    --access-logfile ~/signage/logs/web_player_access.log \
    --error-logfile ~/signage/logs/web_player_error.log \
    --pid ~/signage/web_player_gunicorn.pid \
    web_player:app
