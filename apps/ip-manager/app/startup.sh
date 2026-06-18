#!/bin/bash

echo "Setting up database..."

# Initialise migrations folder if it doesn't exist
if [ ! -d "migrations" ]; then
    echo "Initialising migrations..."
    flask db init
fi

# Clear stale alembic version if migrations folder is fresh
python3 -c "
from app import create_app, db
from sqlalchemy import text
app = create_app()
with app.app_context():
    try:
        with db.engine.connect() as conn:
            conn.execute(text('DELETE FROM alembic_version'))
            conn.commit()
        print('Cleared alembic version table')
    except Exception as e:
        print(f'Note: {e}')
"

# Generate and apply migrations
echo "Running migrations..."
flask db migrate -m "auto" 2>/dev/null || true
flask db upgrade

echo "Starting application..."
gunicorn --bind=0.0.0.0:8000 run:app
