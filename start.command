#!/bin/bash
# One-click launcher for macOS: double-click in Finder.
# First run: creates a virtual environment, installs dependencies,
# asks for the bot token and API key, then starts the bot.
cd "$(dirname "$0")" || exit 1

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "Нужен Python 3.10 или новее: https://www.python.org/downloads/"
  read -r -p "Нажмите Enter, чтобы закрыть."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Создаю окружение..."
  python3 -m venv .venv || exit 1
fi
source .venv/bin/activate

echo "Проверяю зависимости..."
pip install -q -r requirements.txt || { read -r -p "Ошибка установки. Enter, чтобы закрыть."; exit 1; }

if [ ! -f .env ]; then
  python -m joop.setup || exit 1
fi

echo "Бот запущен. Остановить: Ctrl+C или закрыть окно."
python -m joop
