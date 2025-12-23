#!/bin/bash
# Start Web Player with Gunicorn (Production Mode)

cd "$(dirname "$0")"

echo "=========================================="
echo "Starting Web Player with Gunicorn"
echo "=========================================="

# Configuration
WORKERS=4              # More workers for high-concurrency TV streaming
BIND="0.0.0.0:8080"
TIMEOUT=120            # 2 minutes (videos can be large)
LOG_LEVEL="info"
WORKER_CLASS="sync"    # Use 'gevent' or 'eventlet' for even more connections

# Start gunicorn
exec gunicorn \
    --workers $WORKERS \
    --bind $BIND \
    --timeout $TIMEOUT \
    --log-level $LOG_LEVEL \
    --access-logfile ~/signage/logs/web_player_access.log \
    --error-logfile ~/signage/logs/web_player_error.log \
    --pid ~/signage/web_player_gunicorn.pid \
    --worker-class $WORKER_CLASS \
    web_player:app
