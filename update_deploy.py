#!/usr/bin/env python3
"""Update deploy.sh with migrate-db command"""

content = """#!/bin/bash
# deploy.sh - Simple deployment script for college Linux machine
# Usage: ./deploy.sh [start|stop|restart|logs|update|status|migrate-db]

set -e

COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_env() {
    if [ ! -f "$ENV_FILE" ]; then
        log_warn ".env file not found. Creating from .env.example..."
        cp .env.example .env
        log_warn "Please edit .env with your configuration before starting!"
        log_warn "At minimum, change JWT_SECRET_KEY to a secure random value."
        exit 1
    fi
}

start_services() {
    check_env
    log_info "Starting Timetable Generator services..."
    docker compose -f "$COMPOSE_FILE" up -d --build
    log_info "Services started! Access the app at:"
    log_info "  Frontend: http://localhost"
    log_info "  Backend API: http://localhost:8000"
    log_info "  API Docs: http://localhost:8000/docs"
}

stop_services() {
    log_info "Stopping Timetable Generator services..."
    docker compose -f "$COMPOSE_FILE" down
    log_info "Services stopped."
}

restart_services() {
    log_info "Restarting Timetable Generator services..."
    docker compose -f "$COMPOSE_FILE" restart
    log_info "Services restarted."
}

show_logs() {
    docker compose -f "$COMPOSE_FILE" logs -f --tail=100
}

update_services() {
    log_info "Updating Timetable Generator..."
    docker compose -f "$COMPOSE_FILE" pull
    docker compose -f "$COMPOSE_FILE" up -d --build
    log_info "Update complete!"
}

show_status() {
    docker compose -f "$COMPOSE_FILE" ps
}

migrate_db() {
    log_info "Regenerating PostgreSQL dump from SQLite..."
    if [ ! -f "backend/timetable.db" ]; then
        log_error "backend/timetable.db not found!"
        exit 1
    fi
    python migrate_sqlite_to_postgres.py backend/timetable.db backend/init_postgres.sql
    log_info "Database migration complete. Restart services to apply: ./deploy.sh restart"
}

case "$1" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    logs)
        show_logs
        ;;
    update)
        update_services
        ;;
    status)
        show_status
        ;;
    migrate-db)
        migrate_db
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|logs|update|status|migrate-db}"
        echo ""
        echo "Commands:"
        echo "  start       - Start all services (builds images on first run)"
        echo "  stop        - Stop all services"
        echo "  restart     - Restart all services"
        echo "  logs        - Show live logs from all services"
        echo "  update      - Pull latest images and rebuild"
        echo "  status      - Show service status"
        echo "  migrate-db  - Regenerate PostgreSQL dump from SQLite database"
        exit 1
        ;;
esac
"""

with open('deploy.sh', 'w') as f:
    f.write(content)
print('deploy.sh updated')