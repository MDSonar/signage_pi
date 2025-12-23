#!/bin/bash
# Start Dashboard with Gunicorn (Production Mode)

cd "$(dirname "$0")"

echo "=========================================="
echo "Starting Dashboard with Gunicorn"
echo "=========================================="

# Configuration
WORKERS=2              # Fewer workers for dashboard (admin UI)
BIND="0.0.0.0:5000"
TIMEOUT=300            # 5 minutes for large uploads
LOG_LEVEL="info"

# Start gunicorn
exec gunicorn \
    --workers $WORKERS \
    --bind $BIND \
    --timeout $TIMEOUT \
    --log-level $LOG_LEVEL \
    --access-logfile ~/signage/logs/dashboard_access.log \
    --error-logfile ~/signage/logs/dashboard_error.log \
    --pid ~/signage/dashboard_gunicorn.pid \
    dashboard:app
