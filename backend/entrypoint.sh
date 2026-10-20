#!/bin/bash
# Entrypoint script for backend container
# Handles database initialization and migrations

set -e

echo "Starting Timetable Generator Backend..."

# Wait for database to be ready (if using PostgreSQL)
if [[ "$DATABASE_URL" == postgresql* ]]; then
    echo "Waiting for PostgreSQL to be ready..."
    # Extract host and port from DATABASE_URL
    # Format: postgresql://user:pass@host:port/dbname
    DB_HOST=$(echo $DATABASE_URL | sed -n 's/.*@\([^:]*\):.*/\1/p')
    DB_PORT=$(echo $DATABASE_URL | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
    
    if [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
        until pg_isready -h "$DB_HOST" -p "$DB_PORT" -q; do
            echo "PostgreSQL is unavailable - sleeping"
            sleep 2
        done
        echo "PostgreSQL is ready!"
    fi
    
    # Run Alembic migrations
    echo "Running database migrations..."
    alembic upgrade head
else
    echo "Using SQLite - tables will be created automatically on startup"
fi

# Start the application
echo "Starting FastAPI server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2