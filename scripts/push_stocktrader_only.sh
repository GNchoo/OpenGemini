#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# stock_trader 디렉토리만 분리 브랜치로 생성 후 원격 main에 푸시
BRANCH="stocktrader-split"
git subtree split --prefix=stock_trader -b "$BRANCH" >/dev/null
git push stock "$BRANCH":main --force-with-lease
git branch -D "$BRANCH" >/dev/null

echo "Pushed stock_trader subtree to stock/main"
