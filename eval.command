#!/bin/bash
# Runs both scripted evaluations (beauty salon and dental clinic) with the key from .env.
# Double-click in Finder; results go to eval/results.json and eval/results_dental.json.
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate || { echo "Сначала запустите start.command"; read -r -p "Enter, чтобы закрыть."; exit 1; }
echo "1/2: салон красоты (24 диалога)"
python -m eval.run_eval business.example.yaml eval/cases.yaml eval/results.json
echo
echo "2/2: стоматология (14 диалогов)"
python -m eval.run_eval business.dental.example.yaml eval/cases_dental.yaml eval/results_dental.json
read -r -p "Готово. Нажмите Enter, чтобы закрыть."
