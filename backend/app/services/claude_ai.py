import anthropic
import httpx
import base64
import re
import json
from typing import Optional
from app.core.config import get_settings

settings = get_settings()


def get_claude_client():
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def suggest_recipes(
    query: str,
    pantry_items: list[str] = None,
    max_calories: int = None,
    existing_recipes: list[dict] = None
) -> list[dict]:
    """Use Claude to suggest recipes based on complex queries"""
    
    client = get_claude_client()
    
    context_parts = []
    
    if pantry_items:
        context_parts.append(f"Zutaten die verfügbar sind: {', '.join(pantry_items)}")
    
    if max_calories:
        context_parts.append(f"Maximale Kalorien pro Portion: {max_calories} kcal")
    
    if existing_recipes:
        titles = [r.get("title", "") for r in existing_recipes[:5]]
        context_parts.append(f"Diese Rezepte wurden bereits gefunden: {', '.join(titles)}")
    
    context = "\n".join(context_parts) if context_parts else ""
    
    prompt = f"""Du bist ein Ernährungsberater und Rezept-Experte. 

{context}

Anfrage des Nutzers: {query}

Erstelle 10 passende Rezeptvorschläge. Antworte NUR mit einem JSON Array, ohne zusätzlichen Text.

Format für jedes Rezept:
{{
    "title": "Name des Gerichts",
    "calories": 450,
    "ready_in_minutes": 30,
    "servings": 2,
    "ingredients": ["200g Zutat 1", "100g Zutat 2"],
    "instructions": ["Schritt 1", "Schritt 2", "Schritt 3"]
}}

Antworte NUR mit dem JSON Array:"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text.strip()
        
        # Try to parse JSON from response
        # Sometimes Claude adds markdown code blocks
        json_match = re.search(r'\[[\s\S]*\]', response_text)
        if json_match:
            recipes = json.loads(json_match.group())
        else:
            recipes = json.loads(response_text)
        
        # Add metadata
        for recipe in recipes:
            recipe["source"] = "claude"
            recipe["external_id"] = None
            recipe["image_url"] = None
            recipe["source_url"] = None
        
        return recipes
        
    except Exception as e:
        print(f"Claude API error: {e}")
        return []


async def parse_instagram_recipe(instagram_url: str) -> Optional[dict]:
    """Extract recipe from Instagram post - tries oEmbed first, falls back to Claude"""
    
    # Extract shortcode from URL
    match = re.search(r'instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)', instagram_url)
    if not match:
        return None
    
    shortcode = match.group(1)
    caption_text = ""
    thumbnail_url = None
    
    # Try to get caption and image via Instagram's oEmbed API
    try:
        async with httpx.AsyncClient(follow_redirects=True) as http_client:
            # oEmbed endpoint - add access_token parameter (public access)
            oembed_url = f"https://graph.facebook.com/v18.0/instagram_oembed?url={instagram_url}&access_token=public"
            response = await http_client.get(oembed_url, timeout=10)
            
            if response.status_code == 200 and response.text:
                oembed_data = response.json()
                caption_text = oembed_data.get("title", "")
                thumbnail_url = oembed_data.get("thumbnail_url")
                print(f"Instagram oEmbed success: {caption_text[:50]}...")
            else:
                print(f"Instagram oEmbed failed: {response.status_code}")
    except Exception as e:
        print(f"Instagram oEmbed error: {e}")
    
    # If oEmbed failed, ask Claude to create a recipe based on the URL
    # Claude knows many popular Instagram food accounts and recipes
    if not caption_text:
        print("Falling back to Claude for Instagram recipe...")
        return await create_recipe_from_instagram_url(instagram_url, shortcode)
    
    # If we have caption text, use Claude to parse it into a recipe
    if caption_text and len(caption_text) > 50:
        recipe = await parse_caption_to_recipe(caption_text, instagram_url, thumbnail_url)
        if recipe:
            return recipe
    
    # Fallback: If caption is too short, try to analyze the image
    if thumbnail_url:
        try:
            async with httpx.AsyncClient() as http_client:
                img_response = await http_client.get(thumbnail_url, timeout=10)
                if img_response.status_code == 200:
                    image_data = base64.b64encode(img_response.content).decode("utf-8")
                    content_type = img_response.headers.get("content-type", "image/jpeg")
                    media_type = "image/png" if "png" in content_type else "image/jpeg"
                    
                    return await analyze_food_image(
                        image_data, 
                        media_type, 
                        instagram_url,
                        caption_text
                    )
        except Exception as e:
            print(f"Instagram image fetch error: {e}")
    
    # Last fallback
    return await create_recipe_from_instagram_url(instagram_url, shortcode)


async def create_recipe_from_instagram_url(url: str, shortcode: str = "") -> Optional[dict]:
    """Create recipe based on Instagram URL using Claude's knowledge"""
    
    client = get_claude_client()
    
    prompt = f"""Ein Nutzer möchte ein Rezept von diesem Instagram-Post importieren: {url}

Da ich den Instagram-Inhalt nicht direkt abrufen kann, erstelle bitte ein passendes Rezept.

Wenn du den Account oder Post kennst, erstelle das spezifische Rezept.
Wenn nicht, erstelle ein beliebtes, leckeres Rezept das zu einem Food-Instagram-Post passen würde.

Antworte NUR mit einem JSON Objekt:
{{
    "title": "Name des Gerichts",
    "calories": 450,
    "ready_in_minutes": 30,
    "servings": 2,
    "ingredients": ["200g Zutat 1", "100g Zutat 2", "..."],
    "instructions": ["Schritt 1 der Zubereitung", "Schritt 2", "Schritt 3", "..."]
}}

Wichtig: 
- Realistische Kalorienangabe pro Portion
- Vollständige Zutatenliste mit Mengenangaben
- Detaillierte Zubereitungsschritte

Antworte NUR mit dem JSON:"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text.strip()
        
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            recipe = json.loads(json_match.group())
        else:
            recipe = json.loads(response_text)
        
        recipe["source"] = "instagram"
        recipe["external_id"] = None
        recipe["image_url"] = None
        recipe["source_url"] = url
        
        return recipe
        
    except Exception as e:
        print(f"Claude Instagram fallback error: {e}")
        return None


async def parse_caption_to_recipe(caption: str, source_url: str, image_url: str = None) -> Optional[dict]:
    """Parse Instagram caption text into structured recipe using Claude"""
    
    client = get_claude_client()
    
    prompt = f"""Analysiere diesen Instagram-Post und extrahiere das Rezept daraus.

Instagram Caption:
---
{caption}
---

Extrahiere folgende Informationen und erstelle ein strukturiertes Rezept.
Falls Mengenangaben fehlen, schätze realistische Mengen.
Falls die Zubereitungsschritte nicht nummeriert sind, strukturiere sie logisch.

Antworte NUR mit einem JSON Objekt:
{{
    "title": "Name des Gerichts",
    "calories": 450,
    "ready_in_minutes": 30,
    "servings": 2,
    "ingredients": ["200g Zutat 1", "100g Zutat 2"],
    "instructions": ["Schritt 1 der Zubereitung", "Schritt 2", "Schritt 3"]
}}

Falls der Text kein Rezept enthält, antworte mit: {{"error": "Kein Rezept gefunden"}}

Antworte NUR mit dem JSON:"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text.strip()
        
        # Parse JSON
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            recipe = json.loads(json_match.group())
        else:
            recipe = json.loads(response_text)
        
        # Check for error response
        if "error" in recipe:
            print(f"No recipe in caption: {recipe['error']}")
            return None
        
        recipe["source"] = "instagram"
        recipe["external_id"] = None
        recipe["image_url"] = image_url
        recipe["source_url"] = source_url
        
        return recipe
        
    except Exception as e:
        print(f"Claude caption parsing error: {e}")
        return None


async def analyze_food_image(
    image_base64: str, 
    media_type: str, 
    source_url: str,
    caption: str = ""
) -> Optional[dict]:
    """Use Claude vision to analyze food image and create recipe"""
    
    client = get_claude_client()
    
    prompt = f"""Analysiere dieses Bild eines Gerichts und erstelle ein vollständiges Rezept.

{f'Bildunterschrift/Titel: {caption}' if caption else ''}

Antworte NUR mit einem JSON Objekt im folgenden Format:
{{
    "title": "Name des Gerichts",
    "calories": 450,
    "ready_in_minutes": 30,
    "servings": 2,
    "ingredients": ["200g Zutat 1", "100g Zutat 2"],
    "instructions": ["Schritt 1 der Zubereitung", "Schritt 2", "Schritt 3"]
}}

Schätze die Kalorien pro Portion realistisch. Sei bei den Zutaten spezifisch mit Mengenangaben.
Antworte NUR mit dem JSON:"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ],
                }
            ],
        )
        
        response_text = message.content[0].text.strip()
        
        # Parse JSON
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            recipe = json.loads(json_match.group())
        else:
            recipe = json.loads(response_text)
        
        recipe["source"] = "instagram"
        recipe["external_id"] = None
        recipe["image_url"] = None  # We don't store Instagram images
        recipe["source_url"] = source_url
        
        return recipe
        
    except Exception as e:
        print(f"Claude vision error: {e}")
        return None



