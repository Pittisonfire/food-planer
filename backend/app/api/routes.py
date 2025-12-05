from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import date, timedelta

from app.core.database import get_db
from app.models.models import PantryItem, Recipe, MealPlan, ShoppingItem
from app.services import spoonacular, claude_ai

router = APIRouter()


# ============ Pydantic Schemas ============

class RecipeSearch(BaseModel):
    query: str = ""
    ingredients: list[str] = []
    max_calories: Optional[int] = None
    use_claude: bool = False
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
    """Get all saved recipes"""
    recipes = db.query(Recipe).order_by(Recipe.created_at.desc()).all()
    return recipes


@router.post("/recipes/search")
async def search_recipes(search: RecipeSearch, db: Session = Depends(get_db)):
    """Search recipes from Spoonacular or Claude"""
    
    if search.use_claude:
        # Use Claude for smart suggestions
        recipes = await claude_ai.suggest_recipes(
            query=search.query,
            pantry_items=search.ingredients if search.ingredients else None,
            max_calories=search.max_calories,
            offset=search.offset
        )
    elif search.ingredients:
        # Search by ingredients via Spoonacular
        recipes = await spoonacular.search_recipes(
            ingredients=search.ingredients,
            max_calories=search.max_calories,
            offset=search.offset
        )
    else:
        # Search by query via Spoonacular
        recipes = await spoonacular.search_recipes(
            query=search.query,
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
    """Get meal plan for the week"""
    if not start_date:
        # Default to current week (Monday)
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
    
    end_date = start_date + timedelta(days=6)
    
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


@router.post("/shopping/generate")
async def generate_shopping_list(
    start_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """Generate shopping list from meal plan"""
    
    if not start_date:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
    
    end_date = start_date + timedelta(days=6)
    
    # Get all meals for the week
    plans = db.query(MealPlan).filter(
        MealPlan.date >= start_date,
        MealPlan.date <= end_date
    ).all()
    
    # Collect all ingredients
    all_ingredients = set()
    for plan in plans:
        recipe = db.query(Recipe).filter(Recipe.id == plan.recipe_id).first()
        if recipe and recipe.ingredients:
            for ingredient in recipe.ingredients:
                all_ingredients.add(ingredient)
    
    # Clear existing shopping list
    db.query(ShoppingItem).delete()
    
    # Add new items
    for ingredient in sorted(all_ingredients):
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
