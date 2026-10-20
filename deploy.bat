@echo off
REM deploy.bat - Simple deployment script for Windows
REM Usage: deploy.bat [start|stop|restart|logs|update|status]

set COMPOSE_FILE=docker-compose.yml
set ENV_FILE=.env

:check_env
if not exist "%ENV_FILE%" (
    echo [WARN] .env file not found. Creating from .env.example...
    copy .env.example .env
    echo [WARN] Please edit .env with your configuration before starting!
    echo [WARN] At minimum, change JWT_SECRET_KEY to a secure random value.
    exit /b 1
)
goto :%1

:start
echo [INFO] Starting Timetable Generator services...
docker compose -f "%COMPOSE_FILE%" up -d --build
echo [INFO] Services started! Access the app at:
echo [INFO]   Frontend: http://localhost
echo [INFO]   Backend API: http://localhost:8000
echo [INFO]   API Docs: http://localhost:8000/docs
goto :eof

:stop
echo [INFO] Stopping Timetable Generator services...
docker compose -f "%COMPOSE_FILE%" down
echo [INFO] Services stopped.
goto :eof

:restart
echo [INFO] Restarting Timetable Generator services...
docker compose -f "%COMPOSE_FILE%" restart
echo [INFO] Services restarted.
goto :eof

:logs
docker compose -f "%COMPOSE_FILE%" logs -f --tail=100
goto :eof

:update
echo [INFO] Updating Timetable Generator...
docker compose -f "%COMPOSE_FILE%" pull
docker compose -f "%COMPOSE_FILE%" up -d --build
echo [INFO] Update complete!
goto :eof

:status
docker compose -f "%COMPOSE_FILE%" ps
goto :eof

:help
echo Usage: %0 {start^|stop^|restart^|logs^|update^|status}
echo.
echo Commands:
echo   start   - Start all services (builds images on first run)
echo   stop    - Stop all services
echo   restart - Restart all services
echo   logs    - Show live logs from all services
echo   update  - Pull latest images and rebuild
echo   status  - Show service status
exit /b 1