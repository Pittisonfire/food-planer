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
    existing_recipes: list[dict] = None,
    offset: int = 0
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
    
    # Add variation instruction for "load more"
    variation_instruction = ""
    if offset > 0:
        context_parts.append(f"Der Nutzer hat bereits {offset} Rezepte gesehen und möchte ANDERE Vorschläge.")
        variation_instruction = f"\n\nWICHTIG: Gib komplett ANDERE Rezepte als bei den vorherigen {offset} Vorschlägen. Sei kreativ und variiere stark!"
    
    context = "\n".join(context_parts) if context_parts else ""
    
    prompt = f"""Du bist ein Ernährungsberater und Rezept-Experte. 

{context}

Anfrage des Nutzers: {query}{variation_instruction}

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


async def parse_recipe_text(text: str) -> Optional[dict]:
    """Parse raw recipe text (from Instagram, etc.) into structured recipe"""
    
    client = get_claude_client()
    
    prompt = f"""Analysiere diesen Text und extrahiere ein vollständiges Rezept daraus.

Text:
---
{text}
---

Erstelle ein strukturiertes Rezept mit:
1. Einem klaren, appetitlichen Titel
2. Geschätzte Kalorien PRO PORTION (realistisch berechnen!)
3. Zubereitungszeit in Minuten
4. Anzahl Portionen (aus dem Text oder schätzen)
5. Vollständige Zutatenliste MIT Mengenangaben
6. Klare, nummerierte Zubereitungsschritte

Bei den Zutaten:
- Übernimm die Mengenangaben aus dem Text
- Falls Mengen fehlen, ergänze realistische Angaben
- Formatiere einheitlich (z.B. "400g Hackfleisch", "1 Ei", "2 TL Paprika edelsüß")

Bei der Zubereitung:
- Formuliere klare, vollständige Sätze
- Jeder Schritt sollte eine Aktion beschreiben
- Übernimm wichtige Details wie Temperaturen und Zeiten

Antworte NUR mit einem JSON Objekt:
{{
    "title": "Appetitlicher Name des Gerichts",
    "calories": 450,
    "ready_in_minutes": 30,
    "servings": 4,
    "ingredients": ["400g Hackfleisch", "1 Ei", "2 TL Paprika edelsüß", "..."],
    "instructions": ["Schritt 1 als vollständiger Satz.", "Schritt 2 als vollständiger Satz.", "..."]
}}

Antworte NUR mit dem JSON:"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
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
        
        recipe["source"] = "import"
        recipe["external_id"] = None
        recipe["image_url"] = None
        recipe["source_url"] = None
        
        return recipe
        
    except Exception as e:
        print(f"Claude text parsing error: {e}")
        return None


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


async def analyze_taste_profile(favorite_recipes: list[dict], cooked_recipes: list[dict]) -> dict:
    """Analyze user's taste preferences from their recipe history"""
    
    client = get_claude_client()
    
    # Prepare recipe summaries
    fav_summaries = []
    for r in favorite_recipes[:20]:  # Limit to recent 20
        fav_summaries.append(f"- {r.get('title', 'Unknown')} (Zutaten: {', '.join(r.get('ingredients', [])[:5])})")
    
    cooked_summaries = []
    for r in cooked_recipes[:30]:  # Limit to recent 30
        cooked_summaries.append(f"- {r.get('title', 'Unknown')}")
    
    prompt = f"""Analysiere die Essgewohnheiten des Nutzers basierend auf seinen Rezepten.

FAVORISIERTE REZEPTE:
{chr(10).join(fav_summaries) if fav_summaries else "Keine Favoriten"}

GEKOCHTE REZEPTE (letzten Wochen):
{chr(10).join(cooked_summaries) if cooked_summaries else "Keine gekochten Rezepte"}

Erstelle ein Geschmacksprofil. Identifiziere:
1. Bevorzugte Küchen/Cuisines (italienisch, asiatisch, deutsch, etc.)
2. Häufig verwendete Zutaten die der Nutzer mag
3. Zutaten die NICHT vorkommen (mögliche Abneigungen)
4. Zeitpräferenz (schnelle vs. aufwändige Rezepte)
5. Ernährungsweise (viel Fleisch, vegetarisch tendierend, etc.)

Antworte NUR mit einem JSON Objekt:
{{
    "favorite_cuisines": ["italienisch", "asiatisch"],
    "favorite_ingredients": ["Pasta", "Hähnchen", "Reis", "Paprika"],
    "possible_dislikes": ["Fisch", "Meeresfrüchte"],
    "time_preference": "schnell",
    "diet_tendency": "flexitarisch",
    "summary": "Kurze Beschreibung des Geschmacksprofils in 1-2 Sätzen"
}}

Antworte NUR mit dem JSON:"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text.strip()
        
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            profile = json.loads(json_match.group())
        else:
            profile = json.loads(response_text)
        
        return profile
        
    except Exception as e:
        print(f"Taste profile analysis error: {e}")
        return {
            "favorite_cuisines": [],
            "favorite_ingredients": [],
            "possible_dislikes": [],
            "time_preference": "mittel",
            "diet_tendency": "flexitarisch",
            "summary": "Noch nicht genug Daten für ein Profil"
        }


async def generate_week_plan(
    taste_profile: dict,
    days: int = 7,
    existing_plan: list[dict] = None,
    pantry_items: list[str] = None,
    meal_types: list[str] = None
) -> list[dict]:
    """Generate a full week of recipes based on taste profile"""
    
    client = get_claude_client()
    
    # Build context from taste profile
    profile_parts = []
    
    if taste_profile.get("favorite_cuisines"):
        profile_parts.append(f"Bevorzugte Küchen: {', '.join(taste_profile['favorite_cuisines'])}")
    
    if taste_profile.get("favorite_ingredients"):
        profile_parts.append(f"Lieblingszutaten: {', '.join(taste_profile['favorite_ingredients'])}")
    
    if taste_profile.get("possible_dislikes"):
        profile_parts.append(f"MEIDEN: {', '.join(taste_profile['possible_dislikes'])}")
    
    if taste_profile.get("time_preference"):
        time_map = {"schnell": "unter 30 Minuten", "mittel": "30-45 Minuten", "aufwändig": "auch länger"}
        profile_parts.append(f"Zeit: {time_map.get(taste_profile['time_preference'], 'flexibel')}")
    
    if taste_profile.get("diet_tendency"):
        profile_parts.append(f"Ernährung: {taste_profile['diet_tendency']}")
    
    profile_context = "\n".join(profile_parts) if profile_parts else "Keine besonderen Präferenzen"
    
    # Existing plan context
    existing_context = ""
    if existing_plan:
        titles = [r.get('title', '') for r in existing_plan if r.get('title')]
        if titles:
            existing_context = f"\nBereits geplant (NICHT wiederholen): {', '.join(titles[:10])}"
    
    # Pantry context
    pantry_context = ""
    if pantry_items:
        pantry_context = f"\nVerfügbare Zutaten im Vorrat: {', '.join(pantry_items[:15])}"
    
    # Build specific meal type instructions
    meal_types = meal_types or ["lunch"]
    
    meal_type_instructions = {
        "breakfast": """FRÜHSTÜCK - WICHTIG: Nur typische Frühstücksgerichte!
Erlaubt: Porridge, Overnight Oats, Müsli mit Joghurt, Rührei, Spiegelei, Omelette, 
Smoothie Bowl, Pancakes, French Toast, Avocado-Toast, Quark mit Früchten, Granola.
VERBOTEN für Frühstück: Pasta, Reis, Fleischgerichte, Aufläufe, Pfannengerichte mit Knoblauch/Zwiebeln.
Kalorien: 200-400 kcal, Zeit: max 15 Minuten""",
        "lunch": """MITTAGESSEN - Ausgewogene Hauptmahlzeit
Erlaubt: Salate, Bowls, Sandwiches, leichte Pasta, Suppen, Wraps, Reis-Gerichte.
Kalorien: 400-600 kcal, Zeit: 20-40 Minuten""",
        "dinner": """ABENDESSEN - Sättigende Hauptmahlzeit  
Erlaubt: Alle herzhaften Gerichte, Aufläufe, Fleisch/Fisch mit Beilagen, Pasta, Curries.
Kalorien: 500-800 kcal, Zeit: 30-60 Minuten"""
    }
    
    # Calculate how many recipes per meal type
    num_days = days // len(meal_types) if meal_types else days
    
    prompt = f"""Erstelle einen Essensplan basierend auf diesem Geschmacksprofil:

GESCHMACKSPROFIL:
{profile_context}
{existing_context}
{pantry_context}

WICHTIG - Erstelle Rezepte für diese Mahlzeiten:
"""
    
    for mt in meal_types:
        instruction = meal_type_instructions.get(mt, "Hauptmahlzeit")
        prompt += f"\n{instruction}\n"
    
    prompt += f"""

Erstelle insgesamt {days} Rezepte. Die Rezepte müssen ABWECHSELND für die verschiedenen Mahlzeiten sein.
{"Bei " + str(len(meal_types)) + " Mahlzeiten-Typen bedeutet das: " + ", ".join([f"Rezept {i+1}={meal_types[i % len(meal_types)]}" for i in range(min(6, days))]) + "..." if len(meal_types) > 1 else ""}

KRITISCH: Frühstücksrezepte MÜSSEN echte Frühstücksgerichte sein (Eier, Müsli, Porridge, Toast, Smoothies)!
Keine Pasta, kein Reis, kein Knoblauch, keine Zwiebeln zum Frühstück!

Antworte NUR mit einem JSON Array von {days} Rezepten:
[
    {{
        "title": "Name des Gerichts",
        "meal_type": "breakfast/lunch/dinner",
        "calories": 450,
        "ready_in_minutes": 30,
        "servings": 2,
        "ingredients": ["200g Zutat 1", "100g Zutat 2"],
        "instructions": ["Schritt 1", "Schritt 2"],
        "tags": ["schnell", "italienisch"],
        "taste_score": 95
    }},
    ...
]

Antworte NUR mit dem JSON Array:"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=6000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text.strip()
        
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
        print(f"Week plan generation error: {e}")
        return []


async def calculate_taste_score(recipe: dict, taste_profile: dict) -> int:
    """Calculate how well a recipe matches the user's taste profile"""
    
    client = get_claude_client()
    
    prompt = f"""Bewerte wie gut dieses Rezept zum Geschmacksprofil passt.

REZEPT:
Titel: {recipe.get('title', 'Unknown')}
Zutaten: {', '.join(recipe.get('ingredients', [])[:10])}
Zeit: {recipe.get('ready_in_minutes', '?')} Minuten

GESCHMACKSPROFIL:
Bevorzugte Küchen: {', '.join(taste_profile.get('favorite_cuisines', []))}
Lieblingszutaten: {', '.join(taste_profile.get('favorite_ingredients', []))}
Meiden: {', '.join(taste_profile.get('possible_dislikes', []))}
Zeitpräferenz: {taste_profile.get('time_preference', 'flexibel')}
Ernährung: {taste_profile.get('diet_tendency', 'flexibel')}

Gib einen Score von 0-100 zurück.
- 90-100: Perfekt passend
- 70-89: Gut passend
- 50-69: Okay
- 30-49: Weniger passend
- 0-29: Passt nicht zum Profil

Antworte NUR mit einer Zahl (0-100):"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text.strip()
        score = int(re.search(r'\d+', response_text).group())
        return min(100, max(0, score))
        
    except Exception as e:
        print(f"Taste score calculation error: {e}")
        return 50  # Default neutral score


async def process_shopping_list(
    ingredients: list[str],
    pantry_items: list[str] = None
) -> dict:
    """Process ingredients into a smart shopping list with categories, merged quantities, and pantry matching"""
    
    client = get_claude_client()
    
    pantry_context = ""
    if pantry_items:
        pantry_context = f"\nVORRAT (was der Nutzer zuhause hat):\n{chr(10).join(f'- {item}' for item in pantry_items)}\n"
    
    prompt = f"""Du bist ein intelligenter Einkaufsassistent. Verarbeite diese Zutatenliste.

ZUTATEN AUS REZEPTEN:
{chr(10).join(f'- {ing}' for ing in ingredients)}
{pantry_context}

AUFGABEN:
1. ÜBERSETZE alle Zutaten ins Deutsche (z.B. "chicken breast" → "Hähnchenbrust", "garlic" → "Knoblauch")
2. Fasse gleiche Zutaten mit Mengen zusammen (z.B. "200g Hähnchen" + "300g Hähnchen" = "500g Hähnchenbrust")
3. Normalisiere Einheiten (1000g → 1kg, 1000ml → 1l)
4. Ordne jede Zutat einer Kategorie zu - sei präzise, nicht alles ist "Sonstiges"!
5. Identifiziere Basis-Zutaten die man typischerweise zuhause hat
6. Prüfe welche Zutaten im Vorrat sind

KATEGORIEN (nutze genau diese, sei präzise bei der Zuordnung):
- "Obst & Gemüse" (Tomaten, Gurken, Paprika, Zwiebeln, Knoblauch, Kräuter, Salat, etc.)
- "Fleisch & Fisch" (Hackfleisch, Hähnchen, Lachs, Thunfisch, Speck, etc.)
- "Eier & Milchprodukte" (Eier, Milch, Sahne, Käse, Joghurt, Butter, etc.)
- "Backwaren" (Brot, Brötchen, Wraps, Tortillas, etc.)
- "Tiefkühl" (Tiefkühlgemüse, Tiefkühlpizza, etc.)
- "Konserven & Fertigprodukte" (Dosentomaten, Kokosmilch, Brühe, Tomatenmark, etc.)
- "Gewürze & Öle" (Salz, Pfeffer, Olivenöl, Gewürze, Saucen, Essig, etc.)
- "Getränke" (Wein, Säfte, etc.)
- "Sonstiges" (NUR wenn nichts anderes passt: Pasta, Reis, Nudeln, etc.)

BASIS-ZUTATEN (typischerweise im Haushalt vorhanden):
Salz, Pfeffer, Zucker, Mehl, Öl, Butter, Essig, Senf, etc.

Antworte NUR mit einem JSON-Objekt in diesem Format:
{{
  "shopping_items": [
    {{
      "name": "Hähnchenbrust",
      "amount": "500g",
      "category": "Fleisch & Fisch"
    }}
  ],
  "from_pantry": [
    {{
      "name": "Reis",
      "amount": "300g",
      "pantry_match": "Reis"
    }}
  ],
  "basic_items": [
    {{
      "name": "Salz",
      "category": "Gewürze & Öle"
    }}
  ]
}}

Antworte NUR mit validem JSON, kein anderer Text:"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text.strip()
        
        # Clean up response
        if response_text.startswith("```"):
            response_text = re.sub(r'^```(?:json)?\n?', '', response_text)
            response_text = re.sub(r'\n?```$', '', response_text)
        
        result = json.loads(response_text)
        
        # Group shopping items by category
        categorized = {}
        for item in result.get("shopping_items", []):
            category = item.get("category", "Sonstiges")
            if category not in categorized:
                categorized[category] = []
            categorized[category].append(item)
        
        # Define category order
        category_order = [
            "Obst & Gemüse",
            "Fleisch & Fisch", 
            "Eier & Milchprodukte",
            "Backwaren",
            "Tiefkühl",
            "Konserven & Fertigprodukte",
            "Gewürze & Öle",
            "Getränke",
            "Sonstiges"
        ]
        
        # Sort categories
        sorted_categories = []
        for cat in category_order:
            if cat in categorized:
                sorted_categories.append({
                    "name": cat,
                    "items": categorized[cat]
                })
        
        return {
            "categories": sorted_categories,
            "from_pantry": result.get("from_pantry", []),
            "basic_items": result.get("basic_items", [])
        }
        
    except Exception as e:
        print(f"Shopping list processing error: {e}")
        # Fallback: return unprocessed list
        return {
            "categories": [{
                "name": "Sonstiges",
                "items": [{"name": ing, "amount": "", "category": "Sonstiges"} for ing in ingredients]
            }],
            "from_pantry": [],
            "basic_items": []
        }


async def search_supermarket_offers(
    items: list[str],
    postal_code: str,
    supermarkets: list[str] = ["Lidl", "Aldi", "Rewe", "Kaufland", "Edeka", "Netto", "Penny"]
) -> list[dict]:
    """Search for current supermarket offers using Marktguru API"""
    
    # Marktguru API - free and reliable
    MARKTGURU_URL = "https://api.marktguru.de/api/v1/offers/search"
    MARKTGURU_HEADERS = {
        "x-clientkey": "WU/RH+PMGDi+gkZer3WbMelt6zcYHSTytNB7VpTia90=",
        "x-apikey": "8Kk+pmbf7TgJ9nVj2cXeA7P5zBGv8iuutVVMRfOfvNE="
    }
    
    # Extract product names from items (remove quantities)
    search_terms = []
    for item in items[:10]:  # Max 10 items
        # Remove quantities and units to get core product name
        cleaned = re.sub(r'^[\d.,/\s]+', '', item)
        cleaned = re.sub(r'\b\d+[.,]?\d*\s*(g|kg|ml|l|EL|TL|Stück)\b', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()
        if cleaned and len(cleaned) > 2:
            # Take first 2-3 words as search term
            words = cleaned.split()[:3]
            search_terms.append(' '.join(words))
    
    # Remove duplicates
    search_terms = list(dict.fromkeys(search_terms))
    
    print(f"Searching Marktguru for: {search_terms} in PLZ {postal_code}")
    
    all_offers = []
    seen_offers = set()  # Deduplicate by product+price+retailer_base
    
    def normalize_retailer(name: str) -> str:
        """Normalize retailer name (REWE Dortmund -> REWE)"""
        name_lower = name.lower()
        if 'lidl' in name_lower:
            return 'Lidl'
        if 'aldi' in name_lower:
            return 'Aldi'
        if 'rewe' in name_lower:
            return 'REWE'
        if 'kaufland' in name_lower:
            return 'Kaufland'
        if 'edeka' in name_lower:
            return 'Edeka'
        if 'netto' in name_lower:
            return 'Netto'
        if 'penny' in name_lower:
            return 'Penny'
        return name
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for term in search_terms[:8]:  # Max 8 searches
                params = {
                    "as": "web",
                    "limit": 10,  # Get more results
                    "offset": 0,
                    "q": term,
                    "zipCode": postal_code
                }
                
                response = await client.get(
                    MARKTGURU_URL,
                    params=params,
                    headers=MARKTGURU_HEADERS
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    for result in data.get('results', []):
                        raw_retailer = result.get('advertisers', [{}])[0].get('name', '')
                        retailer = normalize_retailer(raw_retailer)
                        
                        # Parse validity dates
                        valid_from = ""
                        valid_to = ""
                        validity = result.get('validityDates', [])
                        if validity:
                            from_date = validity[0].get('from', '')
                            to_date = validity[0].get('to', '')
                            if from_date:
                                valid_from = from_date[8:10] + "." + from_date[5:7] + "."
                            if to_date:
                                valid_to = to_date[8:10] + "." + to_date[5:7] + "."
                        
                        # Format price
                        price = result.get('price')
                        old_price = result.get('oldPrice')
                        
                        product_name = result.get('product', {}).get('name', term)
                        
                        # Deduplicate by product + price + retailer
                        offer_key = f"{product_name}_{price}_{retailer}"
                        if offer_key in seen_offers:
                            continue
                        seen_offers.add(offer_key)
                        
                        offer = {
                            "item": product_name,
                            "supermarket": retailer,
                            "price": f"{price:.2f}€" if price else "",
                            "original_price": f"{old_price:.2f}€" if old_price else "",
                            "valid_from": valid_from,
                            "valid_until": valid_to,
                            "details": result.get('description', '')
                        }
                        all_offers.append(offer)
        
        # Sort by retailer for better readability
        all_offers.sort(key=lambda x: x['supermarket'])
        
        print(f"Found {len(all_offers)} offers from Marktguru")
        return all_offers
        
    except Exception as e:
        print(f"Marktguru search error: {e}")
        import traceback
        traceback.print_exc()
        return []
