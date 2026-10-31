#!/usr/bin/env bash
# Mac/Linux/WSL 用
set -e
git submodule update --init --depth 1
python3 -m venv .venv && . .venv/bin/activate
pip install -U pip && pip install -r requirements.txt
[ -f requirements-agent.txt ] && pip install -r requirements-agent.txt || true
grep -q '^playwright' requirements.txt && python -m playwright install chromium || true
[ -f .env ] || cp .env.example .env
echo "done: source .venv/bin/activate"
