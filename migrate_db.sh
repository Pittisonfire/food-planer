#!/bin/bash
# Database Migration Script for Multi-Tenant Update
# Run this AFTER deploying the new code

echo "=== Food Planer Database Migration ==="
echo "This will add multi-tenant support to the database."
echo ""

# Database credentials
DB_USER="foodplaner_user"
DB_PASS="foodplaner_password"
DB_NAME="foodplaner"

# Run migrations
docker compose exec -T db psql -U $DB_USER -d $DB_NAME << 'EOF'

-- Create households table
CREATE TABLE IF NOT EXISTS households (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    invite_code VARCHAR(20) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    household_id INTEGER NOT NULL REFERENCES households(id),
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add household_id to existing tables (if not exists)
DO $$
BEGIN
    -- pantry_items
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pantry_items' AND column_name='household_id') THEN
        ALTER TABLE pantry_items ADD COLUMN household_id INTEGER;
    END IF;
    
    -- recipes
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='recipes' AND column_name='household_id') THEN
        ALTER TABLE recipes ADD COLUMN household_id INTEGER;
    END IF;
    
    -- meal_plans
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='meal_plans' AND column_name='household_id') THEN
        ALTER TABLE meal_plans ADD COLUMN household_id INTEGER;
    END IF;
    
    -- shopping_items
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='shopping_items' AND column_name='household_id') THEN
        ALTER TABLE shopping_items ADD COLUMN household_id INTEGER;
    END IF;
    
    -- recurring_meals
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='recurring_meals' AND column_name='household_id') THEN
        ALTER TABLE recurring_meals ADD COLUMN household_id INTEGER;
    END IF;
    
    -- taste_profile
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='taste_profile' AND column_name='household_id') THEN
        ALTER TABLE taste_profile ADD COLUMN household_id INTEGER;
    END IF;
END $$;

-- Create Peters household
INSERT INTO households (id, name, invite_code) 
VALUES (1, 'Peters Haushalt', 'PETER2024')
ON CONFLICT (id) DO NOTHING;

-- Update existing data to use Peters household
UPDATE pantry_items SET household_id = 1 WHERE household_id IS NULL;
UPDATE recipes SET household_id = 1 WHERE household_id IS NULL;
UPDATE meal_plans SET household_id = 1 WHERE household_id IS NULL;
UPDATE shopping_items SET household_id = 1 WHERE household_id IS NULL;
UPDATE recurring_meals SET household_id = 1 WHERE household_id IS NULL;
UPDATE taste_profile SET household_id = 1 WHERE household_id IS NULL;

-- Make household_id NOT NULL after data is migrated
ALTER TABLE pantry_items ALTER COLUMN household_id SET NOT NULL;
ALTER TABLE recipes ALTER COLUMN household_id SET NOT NULL;
ALTER TABLE meal_plans ALTER COLUMN household_id SET NOT NULL;
ALTER TABLE shopping_items ALTER COLUMN household_id SET NOT NULL;
ALTER TABLE recurring_meals ALTER COLUMN household_id SET NOT NULL;
ALTER TABLE taste_profile ALTER COLUMN household_id SET NOT NULL;

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_pantry_items_household ON pantry_items(household_id);
CREATE INDEX IF NOT EXISTS idx_recipes_household ON recipes(household_id);
CREATE INDEX IF NOT EXISTS idx_meal_plans_household ON meal_plans(household_id);
CREATE INDEX IF NOT EXISTS idx_shopping_items_household ON shopping_items(household_id);
CREATE INDEX IF NOT EXISTS idx_recurring_meals_household ON recurring_meals(household_id);
CREATE INDEX IF NOT EXISTS idx_taste_profile_household ON taste_profile(household_id);
CREATE INDEX IF NOT EXISTS idx_users_household ON users(household_id);

-- Reset sequence for households
SELECT setval('households_id_seq', (SELECT MAX(id) FROM households));

COMMIT;

EOF

echo ""
echo "Migration complete!"
echo ""
echo "=================================================="
echo "NEXT STEPS:"
echo "=================================================="
echo ""
echo "1. Create your admin user by running:"
echo ""
echo "   docker compose exec backend python -c \""
echo "   from app.services.auth import create_user, hash_password"
echo "   from app.core.database import SessionLocal"
echo "   db = SessionLocal()"
echo "   from app.models.models import User"
echo "   user = User(username='peter', password_hash=hash_password('DEIN_PASSWORT'), display_name='Peter', household_id=1, is_admin=True)"
echo "   db.add(user)"
echo "   db.commit()"
echo "   print('User created!')"
echo "   \""
echo ""
echo "2. Your invite code is: PETER2024"
echo "   Share this with Vera so she can register."
echo ""
echo "3. To create a new household for someone else:"
echo "   docker compose exec db psql -U $DB_USER -d $DB_NAME -c \\"
echo "   \"INSERT INTO households (name, invite_code) VALUES ('Anderer Haushalt', 'CODE1234');\""
echo ""
