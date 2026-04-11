#!/bin/bash
set -e

echo "=== MetaGatherer setup ==="

# 1. PostgreSQL
echo ""
echo "--- PostgreSQL ---"
brew install postgresql@16
brew services start postgresql@16
sleep 2  # wait for pg to be ready
createdb metagatherer || echo "Database 'metagatherer' already exists, skipping."

# 2. Python virtual environment
echo ""
echo "--- Python virtual environment ---"
python3 -m venv .venv
source .venv/bin/activate

# 3. Python dependencies
echo ""
echo "--- Python dependencies ---"
pip install --upgrade pip
pip install -r requirements.txt

# 4. Database migrations
echo ""
echo "--- Running migrations ---"
alembic upgrade head

# 5. Seed archetypes
echo ""
echo "--- Seeding archetypes ---"
python3 -m utils.seed

echo ""
echo "=== Setup complete ==="
echo "Activate venv with: source .venv/bin/activate"
echo "Then run: python3 main.py"
