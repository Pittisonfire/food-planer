from sqlalchemy import Column, Integer, String, Text, Boolean, Float, Date, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Household(Base):
    """A household/family that shares recipes and meal plans"""
    __tablename__ = "households"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)  # e.g. "Familie Müller"
    invite_code = Column(String(20), unique=True, nullable=True)  # For inviting others
    postal_code = Column(String(10), nullable=True)  # PLZ for local offers
    preferred_supermarkets = Column(Text, nullable=True)  # Comma-separated: "Lidl,REWE,Aldi"
    edeka_market_id = Column(Integer, nullable=True)  # Specific Edeka market for local offers
    edeka_market_name = Column(String(255), nullable=True)  # Display name of the market
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    users = relationship("User", back_populates="household")


class User(Base):
    """A user who belongs to a household"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    is_admin = Column(Boolean, default=False)  # Admin of the household
    daily_calorie_target = Column(Integer, default=1800)  # Personal calorie goal
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    household = relationship("Household", back_populates="users")


class PantryItem(Base):
    __tablename__ = "pantry_items"
    
    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Recipe(Base):
    __tablename__ = "recipes"
    
    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False, index=True)
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
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False, index=True)
    recipe_id = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    meal_type = Column(String(50), default="main")  # breakfast, lunch, dinner, snack
    created_at = Column(DateTime, server_default=func.now())


class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    
    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False, index=True)
    name = Column(String(500), nullable=False)
    category = Column(String(100), default="Sonstiges")  # Category for grouping
    checked = Column(Boolean, default=False)
    recipe_id = Column(Integer, nullable=True)  # Which recipe this ingredient is for
    recipe_title = Column(String(255), nullable=True)  # Recipe name for display
    created_at = Column(DateTime, server_default=func.now())


class RecurringMeal(Base):
    """Stores recurring meal rules like 'Friday is always Pizza'"""
    __tablename__ = "recurring_meals"
    
    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False, index=True)
    weekday = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    meal_type = Column(String(50), default="dinner")  # breakfast, lunch, dinner, snack
    recipe_id = Column(Integer, nullable=True)  # Link to a specific recipe
    title = Column(String(255), nullable=True)  # Or just a text like "Pizza"
    created_at = Column(DateTime, server_default=func.now())


class TasteProfile(Base):
    """Stores the user's learned taste preferences"""
    __tablename__ = "taste_profile"
    
    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False, index=True)
    profile_data = Column(JSON, default=dict)  # Learned preferences
    # Example: {
    #   "liked_cuisines": ["italienisch", "asiatisch"],
    #   "disliked_ingredients": ["Fisch", "Pilze"],
    #   "preferred_time": "schnell",  # under 30 min
    #   "diet_preferences": ["vegetarisch"],
    #   "favorite_ingredients": ["Pasta", "Hähnchen", "Reis"]
    # }
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class IngredientCache(Base):
    """Cache for categorized ingredients to avoid re-processing"""
    __tablename__ = "ingredient_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False, index=True)
    ingredient_key = Column(String(255), nullable=False, index=True)  # Normalized ingredient name
    category = Column(String(100), nullable=False)  # Category it belongs to
    display_name = Column(String(500))  # How to display (with amount)
    is_basic = Column(Boolean, default=False)  # Is it a basic ingredient (salt, pepper, etc.)
    created_at = Column(DateTime, server_default=func.now())
