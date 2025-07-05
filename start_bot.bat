@echo off
cd /d "%~dp0"
echo Запускаем Docker контейнер medkitbot...

docker start medkitbot 2>nul || (
    echo Контейнер не найден, создаём и запускаем...
    docker run -d --name medkitbot --env-file .env medkitbot
)

echo Бот запущен.
pause
