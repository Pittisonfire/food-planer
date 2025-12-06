from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import date, timedelta

from app.core.database import get_db
from app.models.models import PantryItem, Recipe, MealPlan, ShoppingItem, TasteProfile, RecurringMeal
from app.services import claude_ai

router = APIRouter()


# ============ Pydantic Schemas ============

class RecipeSearch(BaseModel):
    query: str = ""
    ingredients: list[str] = []
    max_calories: Optional[int] = None
    offset: int = 0  # For "load more" pagination


class RecipeTextImport(BaseModel):
    text: str  # Raw recipe text to parse


class MealPlanCreate(BaseModel):
    recipe_id: int
    date: date
    meal_type: str = "main"


class MealPlanMove(BaseModel):
    new_date: date


class ShoppingItemCreate(BaseModel):
    name: str


# ============ Recipe Endpoints ============

@router.get("/recipes")
async def get_saved_recipes(db: Session = Depends(get_db)):
    """Get all saved recipes, favorites first"""
    recipes = db.query(Recipe).order_by(Recipe.is_favorite.desc(), Recipe.created_at.desc()).all()
    return recipes


@router.get("/recipes/favorites")
async def get_favorite_recipes(db: Session = Depends(get_db)):
    """Get only favorite recipes"""
    recipes = db.query(Recipe).filter(Recipe.is_favorite == True).order_by(Recipe.created_at.desc()).all()
    return recipes


@router.put("/recipes/{recipe_id}/favorite")
async def toggle_favorite(recipe_id: int, db: Session = Depends(get_db)):
    """Toggle favorite status of a recipe"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    
    recipe.is_favorite = not recipe.is_favorite
    db.commit()
    db.refresh(recipe)
    return recipe


@router.post("/recipes/search")
async def search_recipes(search: RecipeSearch, db: Session = Depends(get_db)):
    """Search recipes using Claude AI"""
    
    # Always use Claude AI for recipe suggestions
    recipes = await claude_ai.suggest_recipes(
        query=search.query,
        pantry_items=search.ingredients if search.ingredients else None,
        max_calories=search.max_calories,
        offset=search.offset
    )
    
    return recipes


@router.post("/recipes/instagram")
async def import_from_text(data: RecipeTextImport, db: Session = Depends(get_db)):
    """Import recipe from pasted text (Instagram, etc.)"""
    
    recipe_data = await claude_ai.parse_recipe_text(data.text)
    
    if not recipe_data:
        raise HTTPException(status_code=400, detail="Konnte Rezept nicht aus Text extrahieren")
    
    # Save to database
    recipe = Recipe(
        external_id=recipe_data.get("external_id"),
        source=recipe_data.get("source", "import"),
        title=recipe_data.get("title", "Importiertes Rezept"),
        image_url=recipe_data.get("image_url"),
        calories=recipe_data.get("calories"),
        ready_in_minutes=recipe_data.get("ready_in_minutes"),
        servings=recipe_data.get("servings", 2),
        ingredients=recipe_data.get("ingredients", []),
        instructions=recipe_data.get("instructions", []),
        source_url=recipe_data.get("source_url")
    )
    
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    
    return recipe


@router.post("/recipes/save")
async def save_recipe(recipe_data: dict, db: Session = Depends(get_db)):
    """Save a recipe to the database"""
    
    # Check if already exists (by external_id)
    if recipe_data.get("external_id"):
        existing = db.query(Recipe).filter(
            Recipe.external_id == recipe_data["external_id"]
        ).first()
        if existing:
            return existing
    
    recipe = Recipe(
        external_id=recipe_data.get("external_id"),
        source=recipe_data.get("source", "spoonacular"),
        title=recipe_data.get("title", ""),
        image_url=recipe_data.get("image_url"),
        calories=recipe_data.get("calories"),
        ready_in_minutes=recipe_data.get("ready_in_minutes"),
        servings=recipe_data.get("servings", 2),
        ingredients=recipe_data.get("ingredients", []),
        instructions=recipe_data.get("instructions", []),
        source_url=recipe_data.get("source_url")
    )
    
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    
    return recipe


@router.delete("/recipes/{recipe_id}")
async def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Delete a saved recipe"""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    
    # Also delete from meal plans
    db.query(MealPlan).filter(MealPlan.recipe_id == recipe_id).delete()
    db.delete(recipe)
    db.commit()
    
    return {"status": "deleted"}


# ============ Pantry Endpoints ============

@router.get("/pantry")
async def get_pantry(db: Session = Depends(get_db)):
    """Get all pantry items"""
    items = db.query(PantryItem).order_by(PantryItem.name).all()
    return items


@router.post("/pantry")
async def add_pantry_item(name: str, db: Session = Depends(get_db)):
    """Add item to pantry"""
    item = PantryItem(name=name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/pantry/{item_id}")
async def remove_pantry_item(item_id: int, db: Session = Depends(get_db)):
    """Remove item from pantry"""
    item = db.query(PantryItem).filter(PantryItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "deleted"}


# ============ Meal Plan Endpoints ============

@router.get("/mealplan")
async def get_meal_plan(
    start_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """Get meal plan for two weeks"""
    if not start_date:
        # Default to current week (Monday)
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
    
    # Two weeks instead of one
    end_date = start_date + timedelta(days=13)
    
    plans = db.query(MealPlan).filter(
        MealPlan.date >= start_date,
        MealPlan.date <= end_date
    ).all()
    
    # Get recipe details for each plan
    result = []
    for plan in plans:
        recipe = db.query(Recipe).filter(Recipe.id == plan.recipe_id).first()
        if recipe:
            result.append({
                "id": plan.id,
                "date": plan.date.isoformat(),
                "meal_type": plan.meal_type,
                "recipe": {
                    "id": recipe.id,
                    "title": recipe.title,
                    "image_url": recipe.image_url,
                    "calories": recipe.calories,
                    "ready_in_minutes": recipe.ready_in_minutes,
                    "ingredients": recipe.ingredients,
                    "instructions": recipe.instructions,
                    "source": recipe.source
                }
            })
    
    return result


@router.post("/mealplan")
async def add_to_meal_plan(data: MealPlanCreate, db: Session = Depends(get_db)):
    """Add recipe to meal plan"""
    
    # Check if recipe exists
    recipe = db.query(Recipe).filter(Recipe.id == data.recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    
    plan = MealPlan(
        recipe_id=data.recipe_id,
        date=data.date,
        meal_type=data.meal_type
    )
    
    db.add(plan)
    db.commit()
    db.refresh(plan)
    
    return {
        "id": plan.id,
        "date": plan.date.isoformat(),
        "meal_type": plan.meal_type,
        "recipe": {
            "id": recipe.id,
            "title": recipe.title,
            "calories": recipe.calories
        }
    }


@router.put("/mealplan/{plan_id}/move")
async def move_meal(plan_id: int, data: MealPlanMove, db: Session = Depends(get_db)):
    """Move meal to different day"""
    plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    
    plan.date = data.new_date
    db.commit()
    
    return {"status": "moved", "new_date": data.new_date.isoformat()}


class MealTypeChange(BaseModel):
    meal_type: str


@router.put("/mealplan/{plan_id}/type")
async def change_meal_type(plan_id: int, data: MealTypeChange, db: Session = Depends(get_db)):
    """Change meal type (breakfast, lunch, dinner, snack)"""
    plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    
    plan.meal_type = data.meal_type
    db.commit()
    
    return {"status": "updated", "meal_type": data.meal_type}


@router.delete("/mealplan/{plan_id}")
async def remove_from_meal_plan(plan_id: int, db: Session = Depends(get_db)):
    """Remove from meal plan"""
    plan = db.query(MealPlan).filter(MealPlan.id == plan_id).first()
    if plan:
        db.delete(plan)
        db.commit()
    return {"status": "deleted"}


# ============ Shopping List Endpoints ============

@router.get("/shopping")
async def get_shopping_list(db: Session = Depends(get_db)):
    """Get shopping list"""
    items = db.query(ShoppingItem).order_by(ShoppingItem.checked, ShoppingItem.name).all()
    return items


class ShoppingGenerateRequest(BaseModel):
    dates: list[str] = []  # List of date strings (YYYY-MM-DD)


@router.post("/shopping/generate")
async def generate_shopping_list(
    request: ShoppingGenerateRequest = None,
    db: Session = Depends(get_db)
):
    """Generate shopping list from meal plan for specific dates, excluding pantry items"""
    
    # If no dates provided, use current and next week
    if not request or not request.dates:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())  # Monday
        end_date = start_date + timedelta(days=13)  # Two weeks
        
        plans = db.query(MealPlan).filter(
            MealPlan.date >= start_date,
            MealPlan.date <= end_date
        ).all()
    else:
        # Convert string dates to date objects
        date_objects = [date.fromisoformat(d) for d in request.dates]
        plans = db.query(MealPlan).filter(MealPlan.date.in_(date_objects)).all()
    
    # Collect all ingredients
    all_ingredients = set()
    for plan in plans:
        recipe = db.query(Recipe).filter(Recipe.id == plan.recipe_id).first()
        if recipe and recipe.ingredients:
            for ingredient in recipe.ingredients:
                all_ingredients.add(ingredient)
    
    # Get pantry items to exclude
    pantry_items = db.query(PantryItem).all()
    pantry_names = [p.name.lower() for p in pantry_items]
    
    # Filter out ingredients that match pantry items
    def is_in_pantry(ingredient: str) -> bool:
        ingredient_lower = ingredient.lower()
        for pantry_name in pantry_names:
            # Check if pantry item is contained in ingredient or vice versa
            if pantry_name in ingredient_lower or ingredient_lower in pantry_name:
                return True
        return False
    
    filtered_ingredients = [ing for ing in all_ingredients if not is_in_pantry(ing)]
    
    # Clear existing shopping list
    db.query(ShoppingItem).delete()
    
    # Add new items
    for ingredient in sorted(filtered_ingredients):
        item = ShoppingItem(name=ingredient)
        db.add(item)
    
    db.commit()
    
    items = db.query(ShoppingItem).order_by(ShoppingItem.name).all()
    return items


@router.post("/shopping")
async def add_shopping_item(data: ShoppingItemCreate, db: Session = Depends(get_db)):
    """Add item to shopping list"""
    item = ShoppingItem(name=data.name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/shopping/{item_id}/toggle")
async def toggle_shopping_item(item_id: int, db: Session = Depends(get_db)):
    """Toggle checked status"""
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item nicht gefunden")
    
    item.checked = not item.checked
    db.commit()
    
    return item


@router.delete("/shopping/{item_id}")
async def delete_shopping_item(item_id: int, db: Session = Depends(get_db)):
    """Delete shopping item"""
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "deleted"}


@router.delete("/shopping")
async def clear_shopping_list(db: Session = Depends(get_db)):
    """Clear entire shopping list"""
    db.query(ShoppingItem).delete()
    db.commit()
    return {"status": "cleared"}


# ============ Taste Profile Endpoints ============

@router.get("/taste-profile")
async def get_taste_profile(db: Session = Depends(get_db)):
    """Get the current taste profile"""
    profile = db.query(TasteProfile).first()
    if not profile:
        return {
            "profile_data": {
                "favorite_cuisines": [],
                "favorite_ingredients": [],
                "possible_dislikes": [],
                "time_preference": "mittel",
                "diet_tendency": "flexitarisch",
                "summary": "Noch kein Profil erstellt - füge Favoriten hinzu oder koche mehr Rezepte!"
            }
        }
    return {"profile_data": profile.profile_data}


@router.post("/taste-profile/analyze")
async def analyze_taste_profile(db: Session = Depends(get_db)):
    """Analyze taste profile from recipe history"""
    
    # Get favorite recipes
    favorites = db.query(Recipe).filter(Recipe.is_favorite == True).all()
    favorite_dicts = [
        {"title": r.title, "ingredients": r.ingredients or []}
        for r in favorites
    ]
    
    # Get cooked recipes (from meal plan)
    from sqlalchemy import desc
    meal_plans = db.query(MealPlan).order_by(desc(MealPlan.date)).limit(50).all()
    recipe_ids = [mp.recipe_id for mp in meal_plans]
    cooked_recipes = db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all() if recipe_ids else []
    cooked_dicts = [
        {"title": r.title, "ingredients": r.ingredients or []}
        for r in cooked_recipes
    ]
    
    # Analyze with Claude
    profile_data = await claude_ai.analyze_taste_profile(favorite_dicts, cooked_dicts)
    
    # Save or update profile
    profile = db.query(TasteProfile).first()
    if profile:
        profile.profile_data = profile_data
    else:
        profile = TasteProfile(profile_data=profile_data)
        db.add(profile)
    
    db.commit()
    
    return {"profile_data": profile_data}


class AutoPlanRequest(BaseModel):
    days: int = 7
    start_date: Optional[date] = None


@router.post("/mealplan/auto-generate")
async def auto_generate_mealplan(request: AutoPlanRequest, db: Session = Depends(get_db)):
    """Auto-generate a meal plan based on taste profile"""
    
    # Get taste profile
    profile = db.query(TasteProfile).first()
    profile_data = profile.profile_data if profile else {}
    
    # Get existing plan for the period (to avoid duplicates)
    start = request.start_date or date.today()
    end = start + timedelta(days=request.days)
    existing_plans = db.query(MealPlan).filter(
        MealPlan.date >= start,
        MealPlan.date < end
    ).all()
    
    existing_recipe_ids = [mp.recipe_id for mp in existing_plans]
    existing_recipes = db.query(Recipe).filter(Recipe.id.in_(existing_recipe_ids)).all() if existing_recipe_ids else []
    existing_dicts = [{"title": r.title} for r in existing_recipes]
    
    # Get pantry items
    pantry = db.query(PantryItem).all()
    pantry_items = [p.name for p in pantry]
    
    # Generate recipes with Claude
    recipes = await claude_ai.generate_week_plan(
        taste_profile=profile_data,
        days=request.days,
        existing_plan=existing_dicts,
        pantry_items=pantry_items
    )
    
    if not recipes:
        raise HTTPException(status_code=500, detail="Konnte keinen Plan generieren")
    
    # Save recipes and create meal plans
    created_plans = []
    current_date = start
    
    for recipe_data in recipes:
        # Skip days that already have meals
        while current_date < end:
            day_has_meal = any(mp.date == current_date for mp in existing_plans)
            if not day_has_meal:
                break
            current_date += timedelta(days=1)
        
        if current_date >= end:
            break
        
        # Create recipe
        recipe = Recipe(
            title=recipe_data.get("title", "Unbekannt"),
            calories=recipe_data.get("calories"),
            ready_in_minutes=recipe_data.get("ready_in_minutes"),
            servings=recipe_data.get("servings", 2),
            ingredients=recipe_data.get("ingredients", []),
            instructions=recipe_data.get("instructions", []),
            source="claude",
            taste_score=recipe_data.get("taste_score"),
            tags=recipe_data.get("tags", [])
        )
        db.add(recipe)
        db.flush()  # Get the ID
        
        # Create meal plan entry
        meal_plan = MealPlan(
            recipe_id=recipe.id,
            date=current_date,
            meal_type="lunch"  # Default to lunch
        )
        db.add(meal_plan)
        
        created_plans.append({
            "date": current_date.isoformat(),
            "recipe": recipe_data
        })
        
        current_date += timedelta(days=1)
    
    db.commit()
    
    return {
        "status": "created",
        "plans": created_plans,
        "profile_used": profile_data
    }


# ============ Recurring Meals Endpoints ============

class RecurringMealCreate(BaseModel):
    weekday: int  # 0=Monday, 6=Sunday
    meal_type: str = "dinner"
    recipe_id: Optional[int] = None
    title: Optional[str] = None


@router.get("/recurring-meals")
async def get_recurring_meals(db: Session = Depends(get_db)):
    """Get all recurring meal rules"""
    meals = db.query(RecurringMeal).order_by(RecurringMeal.weekday).all()
    result = []
    for meal in meals:
        recipe = None
        if meal.recipe_id:
            recipe = db.query(Recipe).filter(Recipe.id == meal.recipe_id).first()
        result.append({
            "id": meal.id,
            "weekday": meal.weekday,
            "meal_type": meal.meal_type,
            "recipe_id": meal.recipe_id,
            "title": meal.title or (recipe.title if recipe else None),
            "recipe": {
                "id": recipe.id,
                "title": recipe.title,
                "image_url": recipe.image_url
            } if recipe else None
        })
    return result


@router.post("/recurring-meals")
async def create_recurring_meal(data: RecurringMealCreate, db: Session = Depends(get_db)):
    """Create a new recurring meal rule"""
    meal = RecurringMeal(
        weekday=data.weekday,
        meal_type=data.meal_type,
        recipe_id=data.recipe_id,
        title=data.title
    )
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return meal


@router.delete("/recurring-meals/{meal_id}")
async def delete_recurring_meal(meal_id: int, db: Session = Depends(get_db)):
    """Delete a recurring meal rule"""
    meal = db.query(RecurringMeal).filter(RecurringMeal.id == meal_id).first()
    if meal:
        db.delete(meal)
        db.commit()
    return {"status": "deleted"}


@router.post("/recurring-meals/apply")
async def apply_recurring_meals(db: Session = Depends(get_db)):
    """Apply recurring meal rules to current and next week"""
    recurring = db.query(RecurringMeal).all()
    if not recurring:
        return {"status": "no_rules", "applied": 0}
    
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    
    applied = 0
    for week_offset in [0, 1]:  # This week and next week
        for rule in recurring:
            target_date = monday + timedelta(days=week_offset * 7 + rule.weekday)
            
            # Skip past dates
            if target_date < today:
                continue
            
            # Check if there's already a meal for this date/type
            existing = db.query(MealPlan).filter(
                MealPlan.date == target_date,
                MealPlan.meal_type == rule.meal_type
            ).first()
            
            if existing:
                continue
            
            # If rule has a recipe, add it
            if rule.recipe_id:
                plan = MealPlan(
                    recipe_id=rule.recipe_id,
                    date=target_date,
                    meal_type=rule.meal_type
                )
                db.add(plan)
                applied += 1
    
    db.commit()
    return {"status": "applied", "applied": applied}
