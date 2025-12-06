from sqlalchemy import Column, Integer, String, Text, Boolean, Float, Date, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class PantryItem(Base):
    __tablename__ = "pantry_items"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Recipe(Base):
    __tablename__ = "recipes"
    
    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(100), nullable=True)  # Spoonacular ID
    source = Column(String(50), default="spoonacular")  # spoonacular, claude, instagram
    title = Column(String(500), nullable=False)
    image_url = Column(Text, nullable=True)
    calories = Column(Integer, nullable=True)
    ready_in_minutes = Column(Integer, nullable=True)
    servings = Column(Integer, default=2)
    ingredients = Column(JSON, default=list)  # List of ingredient strings
    instructions = Column(JSON, default=list)  # List of instruction steps
    source_url = Column(Text, nullable=True)  # Original URL (Instagram, etc.)
    is_favorite = Column(Boolean, default=False)
    taste_score = Column(Integer, nullable=True)  # AI-calculated match score 0-100
    tags = Column(JSON, default=list)  # Tags like: vegetarisch, schnell, italienisch
    created_at = Column(DateTime, server_default=func.now())


class MealPlan(Base):
    __tablename__ = "meal_plans"
    
    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    meal_type = Column(String(50), default="main")  # breakfast, lunch, dinner, snack
    created_at = Column(DateTime, server_default=func.now())


class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(500), nullable=False)
    checked = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class TasteProfile(Base):
    """Stores the user's learned taste preferences"""
    __tablename__ = "taste_profile"
    
    id = Column(Integer, primary_key=True, index=True)
    profile_data = Column(JSON, default=dict)  # Learned preferences
    # Example: {
    #   "liked_cuisines": ["italienisch", "asiatisch"],
    #   "disliked_ingredients": ["Fisch", "Pilze"],
    #   "preferred_time": "schnell",  # under 30 min
    #   "diet_preferences": ["vegetarisch"],
    #   "favorite_ingredients": ["Pasta", "Hähnchen", "Reis"]
    # }
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
