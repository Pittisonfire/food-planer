from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import date, timedelta

from app.core.database import get_db
from app.models.models import PantryItem, Recipe, MealPlan, ShoppingItem, TasteProfile, RecurringMeal, User, Household, IngredientCache
from app.services import claude_ai, auth

router = APIRouter()


# ============ Auth Dependency ============

async def get_current_household(request: Request, db: Session = Depends(get_db)) -> int:
    """Extract household_id from JWT token"""
    auth_header = request.headers.get("Authorization")
    
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    
    token = auth_header.replace("Bearer ", "")
    payload = auth.decode_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Ungültiger oder abgelaufener Token")
    
    return payload["household_id"]


# ============ Pydantic Schemas ============

class RecipeSearch(BaseModel):
    query: str = ""
    ingredients: list[str] = []
    max_calories: Optional[int] = None
    offset: int = 0  # For "load more" pagination


class RecipeTextImport(BaseModel):
    text: str  # Raw recipe text to parse
    source_url: Optional[str] = None  # Link to original video/post


class MealPlanCreate(BaseModel):
    recipe_id: int
    date: date
    meal_type: str = "main"


class MealPlanMove(BaseModel):
    new_date: date


class MealTypeChange(BaseModel):
    meal_type: str


class ShoppingItemCreate(BaseModel):
    name: str


class ShoppingGenerateRequest(BaseModel):
    dates: list[str] = []  # List of date strings (YYYY-MM-DD)


class AutoPlanRequest(BaseModel):
    days: int = 7
    start_date: Optional[date] = None
    meal_types: list[str] = ["lunch"]  # breakfast, lunch, dinner


class RecurringMealCreate(BaseModel):
    weekday: int  # 0=Monday, 6=Sunday
    meal_type: str = "dinner"
    recipe_id: Optional[int] = None
    title: Optional[str] = None


class TasteProfileUpdate(BaseModel):
    favorite_cuisines: list[str] = []
    favorite_ingredients: list[str] = []
    disliked_ingredients: list[str] = []
    time_preference: str = "mittel"  # schnell, mittel, aufwändig
    diet_tendency: str = "flexitarisch"


# ============ Recipe Endpoints ============

@router.get("/recipes")
async def get_saved_recipes(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Get all saved recipes, favorites first"""
    recipes = db.query(Recipe).filter(
        Recipe.household_id == household_id
    ).order_by(Recipe.is_favorite.desc(), Recipe.created_at.desc()).all()
    return recipes


@router.get("/recipes/favorites")
async def get_favorite_recipes(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Get only favorite recipes"""
    recipes = db.query(Recipe).filter(
        Recipe.household_id == household_id,
        Recipe.is_favorite == True
    ).order_by(Recipe.created_at.desc()).all()
    return recipes


@router.get("/recipes/{recipe_id}")
async def get_recipe_by_id(
    recipe_id: int,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Get a single recipe by ID"""
    recipe = db.query(Recipe).filter(
        Recipe.id == recipe_id,
        Recipe.household_id == household_id
    ).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    return recipe


@router.put("/recipes/{recipe_id}/favorite")
async def toggle_favorite(
    recipe_id: int,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Toggle favorite status of a recipe"""
    recipe = db.query(Recipe).filter(
        Recipe.id == recipe_id,
        Recipe.household_id == household_id
    ).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    
    recipe.is_favorite = not recipe.is_favorite
    db.commit()
    db.refresh(recipe)
    return recipe


@router.post("/recipes/search")
async def search_recipes(
    search: RecipeSearch,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Search recipes using Claude AI"""
    recipes = await claude_ai.suggest_recipes(
        query=search.query,
        pantry_items=search.ingredients if search.ingredients else None,
        max_calories=search.max_calories,
        offset=search.offset
    )
    return recipes


@router.post("/recipes/instagram")
async def import_from_text(
    data: RecipeTextImport,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Import recipe from pasted text (Instagram, etc.)"""
    recipe_data = await claude_ai.parse_recipe_text(data.text)
    
    if not recipe_data:
        raise HTTPException(status_code=400, detail="Konnte Rezept nicht aus Text extrahieren")
    
    # Use explicit source_url if provided, otherwise use parsed one
    source_url = data.source_url or recipe_data.get("source_url")
    
    # Save to database
    recipe = Recipe(
        household_id=household_id,
        external_id=recipe_data.get("external_id"),
        source=recipe_data.get("source", "import"),
        title=recipe_data.get("title", "Importiertes Rezept"),
        image_url=recipe_data.get("image_url"),
        calories=recipe_data.get("calories"),
        ready_in_minutes=recipe_data.get("ready_in_minutes"),
        servings=recipe_data.get("servings", 2),
        ingredients=recipe_data.get("ingredients", []),
        instructions=recipe_data.get("instructions", []),
        source_url=source_url
    )
    
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    
    return recipe


@router.post("/recipes/save")
async def save_recipe(
    recipe_data: dict,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Save a recipe to the database"""
    
    # Check if already exists (by external_id) for this household
    if recipe_data.get("external_id"):
        existing = db.query(Recipe).filter(
            Recipe.external_id == recipe_data["external_id"],
            Recipe.household_id == household_id
        ).first()
        if existing:
            return existing
    
    recipe = Recipe(
        household_id=household_id,
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
async def delete_recipe(
    recipe_id: int,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Delete a saved recipe"""
    recipe = db.query(Recipe).filter(
        Recipe.id == recipe_id,
        Recipe.household_id == household_id
    ).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    
    # Also delete from meal plans
    db.query(MealPlan).filter(
        MealPlan.recipe_id == recipe_id,
        MealPlan.household_id == household_id
    ).delete()
    db.delete(recipe)
    db.commit()
    
    return {"status": "deleted"}


# ============ Pantry Endpoints ============

@router.get("/pantry")
async def get_pantry(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Get all pantry items with planned status"""
    items = db.query(PantryItem).filter(
        PantryItem.household_id == household_id
    ).order_by(PantryItem.name).all()
    
    # Get upcoming meal plans (next 14 days)
    today = date.today()
    end_date = today + timedelta(days=14)
    
    plans = db.query(MealPlan).filter(
        MealPlan.household_id == household_id,
        MealPlan.date >= today,
        MealPlan.date <= end_date
    ).all()
    
    # Collect all ingredients from planned meals with dates
    planned_ingredients = {}
    for plan in plans:
        recipe = db.query(Recipe).filter(Recipe.id == plan.recipe_id).first()
        if recipe and recipe.ingredients:
            for ingredient in recipe.ingredients:
                ing_lower = ingredient.lower()
                if ing_lower not in planned_ingredients:
                    planned_ingredients[ing_lower] = []
                # Format date nicely
                day_name = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][plan.date.weekday()]
                planned_ingredients[ing_lower].append(f"{day_name} {plan.date.day}.{plan.date.month}")
    
    # Match pantry items with planned ingredients
    result = []
    for item in items:
        item_data = {
            "id": item.id,
            "name": item.name,
            "created_at": item.created_at,
            "planned_for": []
        }
        
        # Check if this pantry item is needed
        item_lower = item.name.lower()
        for ing, dates in planned_ingredients.items():
            if item_lower in ing or ing in item_lower:
                item_data["planned_for"] = dates[:5]  # Max 5 dates
                break
        
        result.append(item_data)
    
    return result


@router.post("/pantry")
async def add_pantry_item(
    name: str,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Add item to pantry"""
    item = PantryItem(household_id=household_id, name=name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/pantry/{item_id}")
async def remove_pantry_item(
    item_id: int,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Remove item from pantry"""
    item = db.query(PantryItem).filter(
        PantryItem.id == item_id,
        PantryItem.household_id == household_id
    ).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "deleted"}


# ============ Meal Plan Endpoints ============

@router.get("/mealplan")
async def get_meal_plan(
    start_date: Optional[date] = None,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Get meal plan for two weeks"""
    if not start_date:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
    
    end_date = start_date + timedelta(days=13)
    
    plans = db.query(MealPlan).filter(
        MealPlan.household_id == household_id,
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
async def add_to_meal_plan(
    data: MealPlanCreate,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Add recipe to meal plan"""
    recipe = db.query(Recipe).filter(
        Recipe.id == data.recipe_id,
        Recipe.household_id == household_id
    ).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    
    plan = MealPlan(
        household_id=household_id,
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
            "image_url": recipe.image_url,
            "calories": recipe.calories,
            "ready_in_minutes": recipe.ready_in_minutes,
            "ingredients": recipe.ingredients,
            "instructions": recipe.instructions
        }
    }


@router.put("/mealplan/{plan_id}")
async def move_meal_plan(
    plan_id: int,
    data: MealPlanMove,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Move a meal to a different date"""
    plan = db.query(MealPlan).filter(
        MealPlan.id == plan_id,
        MealPlan.household_id == household_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Meal plan nicht gefunden")
    
    plan.date = data.new_date
    db.commit()
    
    return {"status": "moved", "new_date": data.new_date.isoformat()}


@router.put("/mealplan/{plan_id}/type")
async def change_meal_type(
    plan_id: int,
    data: MealTypeChange,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Change meal type (breakfast, lunch, dinner, snack)"""
    plan = db.query(MealPlan).filter(
        MealPlan.id == plan_id,
        MealPlan.household_id == household_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Meal plan nicht gefunden")
    
    plan.meal_type = data.meal_type
    db.commit()
    
    return {"status": "updated", "meal_type": data.meal_type}


@router.delete("/mealplan/{plan_id}")
async def remove_from_meal_plan(
    plan_id: int,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Remove recipe from meal plan"""
    plan = db.query(MealPlan).filter(
        MealPlan.id == plan_id,
        MealPlan.household_id == household_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Meal plan nicht gefunden")
    
    db.delete(plan)
    db.commit()
    
    return {"status": "deleted"}


# ============ Shopping List Endpoints ============

@router.get("/shopping")
async def get_shopping_list(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Get shopping list"""
    items = db.query(ShoppingItem).filter(
        ShoppingItem.household_id == household_id
    ).order_by(ShoppingItem.checked, ShoppingItem.name).all()
    return [{"id": i.id, "name": i.name, "checked": i.checked, "category": i.category, "recipe_id": i.recipe_id, "recipe_title": i.recipe_title} for i in items]


def normalize_ingredient_key(ingredient: str) -> str:
    """Create a normalized key from an ingredient for cache lookup"""
    import re
    # Remove amounts, units and normalize
    cleaned = re.sub(r'^[\d.,/\s]+', '', ingredient)  # Remove leading numbers
    cleaned = re.sub(r'\b\d+[.,]?\d*\s*(g|kg|ml|l|EL|TL|Stück|Scheiben?|Zehen?|Tbs|tsp|cup|cups|cloves?|tablespoons?|teaspoons?)\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().lower()
    # Remove common prefixes
    cleaned = re.sub(r'^(etwa|ca\.?|circa|optional:?)\s*', '', cleaned, flags=re.IGNORECASE)
    return cleaned[:100]  # Limit length


@router.post("/shopping/generate")
async def generate_shopping_list(
    request: ShoppingGenerateRequest = None,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Generate smart shopping list from meal plan with AI processing and caching"""
    if not request or not request.dates:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=13)
        
        plans = db.query(MealPlan).filter(
            MealPlan.household_id == household_id,
            MealPlan.date >= start_date,
            MealPlan.date <= end_date
        ).all()
    else:
        date_objects = [date.fromisoformat(d) for d in request.dates]
        plans = db.query(MealPlan).filter(
            MealPlan.household_id == household_id,
            MealPlan.date.in_(date_objects)
        ).all()
    
    # Collect all ingredients WITH recipe info
    all_ingredients = []
    for plan in plans:
        recipe = db.query(Recipe).filter(Recipe.id == plan.recipe_id).first()
        if recipe and recipe.ingredients:
            for ingredient in recipe.ingredients:
                all_ingredients.append({
                    "ingredient": ingredient,
                    "recipe_id": recipe.id,
                    "recipe_title": recipe.title
                })
    
    if not all_ingredients:
        db.query(ShoppingItem).filter(ShoppingItem.household_id == household_id).delete()
        db.commit()
        return {
            "categories": [],
            "from_pantry": [],
            "basic_items": [],
            "items": []
        }
    
    # Get pantry items
    pantry_items = db.query(PantryItem).filter(
        PantryItem.household_id == household_id
    ).all()
    pantry_names = [p.name for p in pantry_items]
    pantry_lower = [p.lower() for p in pantry_names]
    
    # Load cache
    cache_entries = db.query(IngredientCache).filter(
        IngredientCache.household_id == household_id
    ).all()
    cache_dict = {c.ingredient_key: c for c in cache_entries}
    
    # Separate cached and uncached ingredients
    cached_items = []
    uncached_ingredients = []
    basic_items = []
    from_pantry = []
    
    # Track which ingredients we've seen (for deduplication)
    seen_keys = set()
    ingredient_counts = {}  # key -> {"ingredients": [...], "recipes": [{"id": x, "title": y}, ...]}
    
    for ing_data in all_ingredients:
        ing = ing_data["ingredient"]
        key = normalize_ingredient_key(ing)
        if not key:
            continue
            
        if key not in ingredient_counts:
            ingredient_counts[key] = {"ingredients": [], "recipes": {}}
        ingredient_counts[key]["ingredients"].append(ing)
        # Use dict to dedupe by recipe_id
        ingredient_counts[key]["recipes"][ing_data["recipe_id"]] = ing_data["recipe_title"]
    
    # Process each unique ingredient
    for key, data in ingredient_counts.items():
        original_list = data["ingredients"]
        # Convert to list of {id, title} dicts
        recipe_list = [{"id": rid, "title": rtitle} for rid, rtitle in data["recipes"].items()]
        recipe_titles = [r["title"] for r in recipe_list]
        
        # Check if in pantry
        in_pantry = any(p in key or key in p for p in pantry_lower)
        
        if key in cache_dict:
            # We have it cached
            cached = cache_dict[key]
            if cached.is_basic:
                basic_items.append({
                    "name": cached.display_name or key,
                    "category": cached.category,
                    "recipes": recipe_list
                })
            elif in_pantry:
                from_pantry.append({
                    "name": cached.display_name or key,
                    "amount": "",
                    "pantry_match": key,
                    "recipes": recipe_list
                })
            else:
                cached_items.append({
                    "name": cached.display_name or key,
                    "amount": "",
                    "category": cached.category,
                    "original_items": original_list,
                    "recipes": recipe_list
                })
        else:
            # Need to process with AI - store recipe info for later
            uncached_ingredients.append({
                "ingredient": original_list[0],
                "recipes": recipe_list
            })
    
    # Process uncached ingredients with AI (if any)
    new_items = []
    if uncached_ingredients:
        # Build a map of ingredient -> recipes for lookup after AI processing
        uncached_recipe_map = {}
        for uc in uncached_ingredients:
            key = normalize_ingredient_key(uc["ingredient"])
            if key:
                uncached_recipe_map[key] = uc["recipes"]
        
        def find_recipes_for_item(item_name: str) -> list:
            """Find recipes that match this item name (fuzzy matching)"""
            item_key = normalize_ingredient_key(item_name)
            # Direct match
            if item_key in uncached_recipe_map:
                return list(uncached_recipe_map[item_key])
            # Fuzzy match - check if any key contains or is contained in item_key
            for key, recipes in uncached_recipe_map.items():
                if len(key) >= 4 and len(item_key) >= 4:
                    if key in item_key or item_key in key:
                        return list(recipes)
                    # Also check first word match
                    if key.split()[0] == item_key.split()[0]:
                        return list(recipes)
            return []
        
        # Send just the ingredient strings to AI
        ingredient_strings = [uc["ingredient"] for uc in uncached_ingredients]
        smart_list = await claude_ai.process_shopping_list(ingredient_strings, pantry_names)
        
        # Save to cache and collect items
        for category in smart_list.get("categories", []):
            for item in category.get("items", []):
                key = normalize_ingredient_key(item.get("name", ""))
                if key and key not in cache_dict:
                    # Save to cache
                    cache_entry = IngredientCache(
                        household_id=household_id,
                        ingredient_key=key,
                        category=category.get("name", "Sonstiges"),
                        display_name=item.get("name"),
                        is_basic=False
                    )
                    db.add(cache_entry)
                
                # Try to find recipes for this item (with fuzzy matching)
                item_recipes = find_recipes_for_item(item.get("name", ""))
                
                new_items.append({
                    "name": item.get("name"),
                    "amount": item.get("amount", ""),
                    "category": category.get("name", "Sonstiges"),
                    "recipes": item_recipes
                })
        
        # Save basic items to cache
        for item in smart_list.get("basic_items", []):
            key = normalize_ingredient_key(item.get("name", ""))
            if key and key not in cache_dict:
                cache_entry = IngredientCache(
                    household_id=household_id,
                    ingredient_key=key,
                    category=item.get("category", "Gewürze & Öle"),
                    display_name=item.get("name"),
                    is_basic=True
                )
                db.add(cache_entry)
            
            # Try to find recipes for this basic item
            item_recipes = find_recipes_for_item(item.get("name", ""))
            basic_items.append({
                **item,
                "recipes": item_recipes
            })
        
        # Add from_pantry from AI
        from_pantry.extend(smart_list.get("from_pantry", []))
        
        db.commit()
    
    # Combine cached and new items
    all_shopping_items = cached_items + new_items
    
    # Group by category
    categorized = {}
    for item in all_shopping_items:
        category = item.get("category", "Sonstiges")
        if category not in categorized:
            categorized[category] = []
        categorized[category].append(item)
    
    # Define category order
    category_order = [
        "Obst & Gemüse", "Fleisch & Fisch", "Eier & Milchprodukte",
        "Backwaren", "Tiefkühl", "Konserven & Fertigprodukte",
        "Gewürze & Öle", "Getränke", "Sonstiges"
    ]
    
    sorted_categories = []
    for cat in category_order:
        if cat in categorized:
            sorted_categories.append({"name": cat, "items": categorized[cat]})
    
    # Clear and rebuild shopping items in DB
    db.query(ShoppingItem).filter(ShoppingItem.household_id == household_id).delete()
    
    for category in sorted_categories:
        for item in category.get("items", []):
            display_name = f"{item.get('amount', '')} {item.get('name', '')}".strip()
            recipes = item.get("recipes", [])
            # recipes is now list of {"id": x, "title": y}
            recipe_id = recipes[0]["id"] if recipes else None
            recipe_title = ", ".join(r["title"] for r in recipes) if recipes else None
            db_item = ShoppingItem(
                household_id=household_id,
                name=display_name,
                category=category.get("name", "Sonstiges"),
                recipe_id=recipe_id,
                recipe_title=recipe_title
            )
            db.add(db_item)
    
    db.commit()
    
    items = db.query(ShoppingItem).filter(
        ShoppingItem.household_id == household_id
    ).order_by(ShoppingItem.category, ShoppingItem.name).all()
    
    return {
        "categories": sorted_categories,
        "from_pantry": from_pantry,
        "basic_items": basic_items,
        "items": [{"id": i.id, "name": i.name, "checked": i.checked, "category": i.category, "recipe_id": i.recipe_id, "recipe_title": i.recipe_title} for i in items]
    }


@router.post("/shopping/offers")
async def search_offers(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Search for supermarket offers for items in shopping list"""
    
    # Get household for postal code
    household = db.query(Household).filter(Household.id == household_id).first()
    
    if not household or not household.postal_code:
        raise HTTPException(
            status_code=400, 
            detail="Bitte zuerst PLZ in den Haushalt-Einstellungen hinterlegen"
        )
    
    # Get current shopping items
    items = db.query(ShoppingItem).filter(
        ShoppingItem.household_id == household_id,
        ShoppingItem.checked == False
    ).all()
    
    if not items:
        return {"offers": [], "message": "Keine Artikel in der Einkaufsliste"}
    
    # Extract item names
    item_names = [item.name for item in items]
    
    # Get preferred supermarkets or use defaults
    if household.preferred_supermarkets:
        supermarkets = household.preferred_supermarkets.split(",")
    else:
        supermarkets = ["Lidl", "Aldi", "REWE", "Kaufland", "Edeka", "Netto", "Penny"]
    
    # Search for offers
    offers = await claude_ai.search_supermarket_offers(
        items=item_names,
        postal_code=household.postal_code,
        supermarkets=supermarkets,
        edeka_market_id=household.edeka_market_id
    )
    
    return {"offers": offers, "postal_code": household.postal_code}


@router.delete("/shopping/cache")
async def clear_ingredient_cache(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Clear ingredient cache to force re-sorting"""
    deleted = db.query(IngredientCache).filter(
        IngredientCache.household_id == household_id
    ).delete()
    db.commit()
    return {"deleted": deleted, "message": "Cache gelöscht - Liste wird neu sortiert"}


@router.post("/shopping")
async def add_shopping_item(
    data: ShoppingItemCreate,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Add item to shopping list"""
    item = ShoppingItem(household_id=household_id, name=data.name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/shopping/{item_id}/toggle")
async def toggle_shopping_item(
    item_id: int,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Toggle checked status"""
    item = db.query(ShoppingItem).filter(
        ShoppingItem.id == item_id,
        ShoppingItem.household_id == household_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item nicht gefunden")
    
    item.checked = not item.checked
    db.commit()
    
    return item


@router.delete("/shopping/{item_id}")
async def delete_shopping_item(
    item_id: int,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Delete shopping item"""
    item = db.query(ShoppingItem).filter(
        ShoppingItem.id == item_id,
        ShoppingItem.household_id == household_id
    ).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "deleted"}


@router.delete("/shopping")
async def clear_shopping_list(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Clear entire shopping list"""
    db.query(ShoppingItem).filter(ShoppingItem.household_id == household_id).delete()
    db.commit()
    return {"status": "cleared"}


# ============ Taste Profile Endpoints ============

@router.get("/taste-profile")
async def get_taste_profile(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Get the current taste profile"""
    profile = db.query(TasteProfile).filter(
        TasteProfile.household_id == household_id
    ).first()
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


@router.post("/taste-profile/update")
async def update_taste_profile(
    data: TasteProfileUpdate,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Manually update taste profile"""
    profile = db.query(TasteProfile).filter(
        TasteProfile.household_id == household_id
    ).first()
    
    profile_data = {
        "favorite_cuisines": data.favorite_cuisines,
        "favorite_ingredients": data.favorite_ingredients,
        "possible_dislikes": data.disliked_ingredients,
        "time_preference": data.time_preference,
        "diet_tendency": data.diet_tendency,
        "summary": f"Profil manuell erstellt. Lieblingszutaten: {', '.join(data.favorite_ingredients[:3]) if data.favorite_ingredients else 'Keine'}."
    }
    
    if profile:
        profile.profile_data = profile_data
    else:
        profile = TasteProfile(household_id=household_id, profile_data=profile_data)
        db.add(profile)
    
    db.commit()
    return {"profile_data": profile_data}


@router.post("/taste-profile/analyze")
async def analyze_taste_profile(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Analyze taste profile from recipe history"""
    from sqlalchemy import desc
    
    # Get favorite recipes
    favorites = db.query(Recipe).filter(
        Recipe.household_id == household_id,
        Recipe.is_favorite == True
    ).all()
    favorite_dicts = [
        {"title": r.title, "ingredients": r.ingredients or []}
        for r in favorites
    ]
    
    # Get cooked recipes (from meal plan)
    meal_plans = db.query(MealPlan).filter(
        MealPlan.household_id == household_id
    ).order_by(desc(MealPlan.date)).limit(50).all()
    recipe_ids = [mp.recipe_id for mp in meal_plans]
    cooked_recipes = db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all() if recipe_ids else []
    cooked_dicts = [
        {"title": r.title, "ingredients": r.ingredients or []}
        for r in cooked_recipes
    ]
    
    # Analyze with Claude
    profile_data = await claude_ai.analyze_taste_profile(favorite_dicts, cooked_dicts)
    
    # Save or update profile
    profile = db.query(TasteProfile).filter(
        TasteProfile.household_id == household_id
    ).first()
    if profile:
        profile.profile_data = profile_data
    else:
        profile = TasteProfile(household_id=household_id, profile_data=profile_data)
        db.add(profile)
    
    db.commit()
    
    return {"profile_data": profile_data}


@router.post("/mealplan/auto-generate")
async def auto_generate_mealplan(
    request: AutoPlanRequest,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Auto-generate a meal plan based on taste profile"""
    
    # Get taste profile
    profile = db.query(TasteProfile).filter(
        TasteProfile.household_id == household_id
    ).first()
    profile_data = profile.profile_data if profile else {}
    
    # Get existing plan for the period
    start = request.start_date or date.today()
    end = start + timedelta(days=request.days)
    existing_plans = db.query(MealPlan).filter(
        MealPlan.household_id == household_id,
        MealPlan.date >= start,
        MealPlan.date < end
    ).all()
    
    existing_recipe_ids = [mp.recipe_id for mp in existing_plans]
    existing_recipes = db.query(Recipe).filter(Recipe.id.in_(existing_recipe_ids)).all() if existing_recipe_ids else []
    existing_dicts = [{"title": r.title} for r in existing_recipes]
    
    # Get pantry items
    pantry = db.query(PantryItem).filter(
        PantryItem.household_id == household_id
    ).all()
    pantry_items = [p.name for p in pantry]
    
    # Calculate total recipes needed
    total_recipes_needed = request.days * len(request.meal_types)
    
    # Generate recipes with Claude
    recipes = await claude_ai.generate_week_plan(
        taste_profile=profile_data,
        days=total_recipes_needed,
        existing_plan=existing_dicts,
        pantry_items=pantry_items,
        meal_types=request.meal_types
    )
    
    if not recipes:
        raise HTTPException(status_code=500, detail="Konnte keinen Plan generieren")
    
    # Save recipes and create meal plans
    created_plans = []
    recipe_index = 0
    
    for day_offset in range(request.days):
        current_date = start + timedelta(days=day_offset)
        
        for meal_type in request.meal_types:
            slot_has_meal = any(
                mp.date == current_date and mp.meal_type == meal_type 
                for mp in existing_plans
            )
            
            if slot_has_meal or recipe_index >= len(recipes):
                continue
            
            recipe_data = recipes[recipe_index]
            recipe_index += 1
            
            # Create recipe
            recipe = Recipe(
                household_id=household_id,
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
            db.flush()
            
            # Create meal plan entry
            meal_plan = MealPlan(
                household_id=household_id,
                recipe_id=recipe.id,
                date=current_date,
                meal_type=meal_type
            )
            db.add(meal_plan)
            
            created_plans.append({
                "date": current_date.isoformat(),
                "meal_type": meal_type,
                "recipe": recipe_data
            })
    
    db.commit()
    
    return {
        "status": "created",
        "plans": created_plans,
        "profile_used": profile_data
    }


# ============ Recurring Meals Endpoints ============

@router.get("/recurring-meals")
async def get_recurring_meals(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Get all recurring meal rules"""
    meals = db.query(RecurringMeal).filter(
        RecurringMeal.household_id == household_id
    ).order_by(RecurringMeal.weekday).all()
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
async def create_recurring_meal(
    data: RecurringMealCreate,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Create a new recurring meal rule"""
    meal = RecurringMeal(
        household_id=household_id,
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
async def delete_recurring_meal(
    meal_id: int,
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Delete a recurring meal rule"""
    meal = db.query(RecurringMeal).filter(
        RecurringMeal.id == meal_id,
        RecurringMeal.household_id == household_id
    ).first()
    if meal:
        db.delete(meal)
        db.commit()
    return {"status": "deleted"}


@router.post("/recurring-meals/apply")
async def apply_recurring_meals(
    household_id: int = Depends(get_current_household),
    db: Session = Depends(get_db)
):
    """Apply recurring meal rules to current and next week"""
    recurring = db.query(RecurringMeal).filter(
        RecurringMeal.household_id == household_id
    ).all()
    if not recurring:
        return {"status": "no_rules", "applied": 0}
    
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    
    applied = 0
    for week_offset in [0, 1]:
        for rule in recurring:
            target_date = monday + timedelta(days=week_offset * 7 + rule.weekday)
            
            if target_date < today:
                continue
            
            existing = db.query(MealPlan).filter(
                MealPlan.household_id == household_id,
                MealPlan.date == target_date,
                MealPlan.meal_type == rule.meal_type
            ).first()
            
            if existing:
                continue
            
            if rule.recipe_id:
                plan = MealPlan(
                    household_id=household_id,
                    recipe_id=rule.recipe_id,
                    date=target_date,
                    meal_type=rule.meal_type
                )
                db.add(plan)
                applied += 1
    
    db.commit()
    return {"status": "applied", "applied": applied}


@router.get("/edeka/markets")
async def search_edeka_markets(query: str):
    """Search for Edeka markets by PLZ or city name - fetches many markets and sorts by distance"""
    import httpx
    import math
    
    # First, get coordinates for the query using Nominatim
    target_lat, target_lon = None, None
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as geo_client:
            geo_response = await geo_client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": f"{query}, Germany", "format": "json", "limit": 1},
                headers={"User-Agent": "FoodPlanner/1.0"}
            )
            if geo_response.status_code == 200:
                geo_data = geo_response.json()
                if geo_data:
                    target_lat = float(geo_data[0].get('lat', 0))
                    target_lon = float(geo_data[0].get('lon', 0))
                    print(f"Geocoded '{query}' to ({target_lat}, {target_lon})")
    except Exception as e:
        print(f"Geocoding error: {e}")
    
    if not target_lat or not target_lon:
        return {"markets": [], "error": "Konnte PLZ/Stadt nicht finden"}
    
    def haversine_distance(lat1, lon1, lat2, lon2):
        """Calculate distance in km between two points"""
        R = 6371  # Earth's radius in km
        lat1, lat2 = math.radians(lat1), math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c
    
    try:
        all_markets = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Fetch multiple pages to get more markets
            for page in range(5):  # Get up to 500 markets
                response = await client.get(
                    "https://www.edeka.de/api/marketsearch/markets",
                    params={"size": 100, "page": page}
                )
                
                if response.status_code != 200:
                    break
                
                data = response.json()
                markets_on_page = data.get('markets', [])
                
                if not markets_on_page:
                    break
                
                for m in markets_on_page:
                    # Only include EDEKA markets (not nah&gut etc.)
                    if m.get('distributionChannelType') != 'EDEKA':
                        continue
                    
                    contact = m.get('contact', {})
                    address = contact.get('address', {})
                    city = address.get('city', {})
                    coords = m.get('coordinates', {})
                    
                    market_lat = float(coords.get('lat', 0)) if coords.get('lat') else 0
                    market_lon = float(coords.get('lon', 0)) if coords.get('lon') else 0
                    
                    if not market_lat or not market_lon:
                        continue
                    
                    distance = haversine_distance(target_lat, target_lon, market_lat, market_lon)
                    
                    all_markets.append({
                        "id": m.get('id'),
                        "name": m.get('name'),
                        "street": address.get('street', ''),
                        "zipCode": city.get('zipCode', ''),
                        "city": city.get('name', ''),
                        "fullAddress": f"{address.get('street', '')}, {city.get('zipCode', '')} {city.get('name', '')}",
                        "distance": round(distance, 1)
                    })
        
        # Sort by distance and return closest 20
        all_markets.sort(key=lambda x: x['distance'])
        nearby_markets = [m for m in all_markets if m['distance'] < 50][:20]
        
        print(f"Found {len(nearby_markets)} EDEKA markets within 50km of {query}")
        return {"markets": nearby_markets}
            
    except Exception as e:
        print(f"Edeka market search error: {e}")
        import traceback
        traceback.print_exc()
        return {"markets": []}
