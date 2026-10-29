#!/bin/bash
# Runs both scripted evaluations (beauty salon and dental clinic) with the key from .env.
# Double-click in Finder; results go to eval/results.json and eval/results_dental.json.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || { read -r -p "Не удалось установить зависимости. Enter, чтобы закрыть."; exit 1; }
fi
source .venv/bin/activate
echo "1/2: салон красоты"
python -m eval.run_eval business.example.yaml eval/cases.yaml eval/results.json
echo
echo "2/2: стоматология"
python -m eval.run_eval business.dental.example.yaml eval/cases_dental.yaml eval/results_dental.json
read -r -p "Готово. Нажмите Enter, чтобы закрыть."
