import httpx
from typing import Optional
from app.core.config import get_settings

settings = get_settings()

SPOONACULAR_BASE_URL = "https://api.spoonacular.com"

# Cache for search results (simple in-memory, resets on restart)
# In production you might want Redis or DB caching
_search_cache = {}


async def search_recipes(
    query: str = "",
    ingredients: list[str] = None,
    max_calories: int = None,
    max_ready_time: int = None,
    number: int = 10,
    offset: int = 0  # For "load more" pagination
) -> list[dict]:
    """
    Search recipes from Spoonacular API
    
    NOTE: Free tier = 50 points/day
    - complexSearch = 1 point
    - findByIngredients = 1 point  
    - getRecipeInformation = 1 point per recipe
    
    So a search for 10 recipes costs ~11 points = ~4 searches/day
    """
    
    # Check cache first (include offset in key)
    cache_key = f"{query}_{ingredients}_{max_calories}_{number}_{offset}"
    if cache_key in _search_cache:
        print(f"Spoonacular cache hit: {cache_key}")
        return _search_cache[cache_key]
    
    async with httpx.AsyncClient() as client:
        params = {
            "apiKey": settings.spoonacular_api_key,
            "number": number,
            "addRecipeInformation": True,
            "addRecipeNutrition": True,
            "fillIngredients": True,
        }
        
        if ingredients:
            # Search by ingredients
            params["ingredients"] = ",".join(ingredients)
            params["ranking"] = 2  # Maximize used ingredients
            url = f"{SPOONACULAR_BASE_URL}/recipes/findByIngredients"
            
            response = await client.get(url, params=params)
            if response.status_code != 200:
                print(f"Spoonacular error: {response.status_code}")
                return []
            
            recipes = response.json()
            
            # Get full recipe info for each (costs 1 point per recipe!)
            detailed_recipes = []
            for recipe in recipes[:number]:
                detail = await get_recipe_details(recipe["id"])
                if detail:
                    detailed_recipes.append(detail)
            
            # Cache results
            _search_cache[cache_key] = detailed_recipes
            return detailed_recipes
        else:
            # Search by query
            params["query"] = query
            params["offset"] = offset  # Pagination
            if max_calories:
                params["maxCalories"] = max_calories
            if max_ready_time:
                params["maxReadyTime"] = max_ready_time
            
            url = f"{SPOONACULAR_BASE_URL}/recipes/complexSearch"
            
            response = await client.get(url, params=params)
            if response.status_code != 200:
                print(f"Spoonacular error: {response.status_code}")
                return []
            
            data = response.json()
            
            # Get full recipe info for each
            detailed_recipes = []
            for recipe in data.get("results", []):
                detail = await get_recipe_details(recipe["id"])
                if detail:
                    detailed_recipes.append(detail)
            
            # Cache results
            _search_cache[cache_key] = detailed_recipes
            return detailed_recipes


async def get_recipe_details(recipe_id: int) -> Optional[dict]:
    """Get detailed recipe information (costs 1 point)"""
    
    # Check cache
    cache_key = f"detail_{recipe_id}"
    if cache_key in _search_cache:
        return _search_cache[cache_key]
    
    async with httpx.AsyncClient() as client:
        params = {
            "apiKey": settings.spoonacular_api_key,
            "includeNutrition": True,
        }
        
        url = f"{SPOONACULAR_BASE_URL}/recipes/{recipe_id}/information"
        
        response = await client.get(url, params=params)
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        # Extract calories from nutrition info
        calories = 0
        if "nutrition" in data and "nutrients" in data["nutrition"]:
            for nutrient in data["nutrition"]["nutrients"]:
                if nutrient["name"] == "Calories":
                    calories = int(nutrient["amount"])
                    break
        
        # Parse ingredients
        ingredients = []
        for ing in data.get("extendedIngredients", []):
            ingredients.append(ing.get("original", ing.get("name", "")))
        
        # Parse instructions
        instructions = []
        if data.get("analyzedInstructions"):
            for instruction_group in data["analyzedInstructions"]:
                for step in instruction_group.get("steps", []):
                    instructions.append(step.get("step", ""))
        
        result = {
            "external_id": str(data["id"]),
            "source": "spoonacular",
            "title": data.get("title", ""),
            "image_url": data.get("image", ""),
            "calories": calories,
            "ready_in_minutes": data.get("readyInMinutes", 0),
            "servings": data.get("servings", 2),
            "ingredients": ingredients,
            "instructions": instructions,
            "source_url": data.get("sourceUrl", ""),
        }
        
        # Cache result
        _search_cache[cache_key] = result
        return result


def clear_cache():
    """Clear the search cache"""
    global _search_cache
    _search_cache = {}
