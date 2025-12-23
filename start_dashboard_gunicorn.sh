#!/bin/bash
# Start Dashboard with Gunicorn (Production Mode)

cd "$(dirname "$0")"

echo "=========================================="
echo "Starting Dashboard with Gunicorn"
echo "=========================================="

# Configuration
WORKERS=2              # Dashboard is light; threads handle concurrency
THREADS=4              # Threads per worker
BIND="0.0.0.0:5000"
TIMEOUT=300            # 5 minutes for large uploads
LOG_LEVEL="info"
WORKER_CLASS="gthread"
KEEP_ALIVE=75
BACKLOG=512
WORKER_TMP_DIR="/dev/shm"

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
    --access-logfile ~/signage/logs/dashboard_access.log \
    --error-logfile ~/signage/logs/dashboard_error.log \
    --pid ~/signage/dashboard_gunicorn.pid \
    dashboard:app
