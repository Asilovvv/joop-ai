#!/bin/bash
# Runs the scripted evaluation (24 cases) with the key from .env.
# Double-click in Finder; results go to eval/results.json.
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate || { echo "Сначала запустите start.command"; read -r -p "Enter, чтобы закрыть."; exit 1; }
python -m eval.run_eval business.example.yaml eval/cases.yaml
read -r -p "Готово. Нажмите Enter, чтобы закрыть."
