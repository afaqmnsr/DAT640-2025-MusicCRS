"""Playlist Cover Image Generator using Llama for MusicCRS."""

import json
import os
import base64
import hashlib
import requests
from typing import Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
import io
import ollama
from dotenv import load_dotenv

# Load environment variables
load_dotenv('config.env')

OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'https://ollama.ux.uis.no')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.3:70b')
OLLAMA_API_KEY = os.getenv('OLLAMA_API_KEY')

class PlaylistCoverGenerator:
    """Generates playlist cover images using Llama for analysis and image generation."""
    
    def __init__(self):
        """Initialize the image generator with Llama client."""
        if not OLLAMA_API_KEY:
            raise ValueError("OLLAMA_API_KEY not found in environment variables.")
        
        self._llm = ollama.Client(
            host=OLLAMA_HOST,
            headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
        )
        
        # Create cache directory for generated images
        self.cache_dir = "generated_covers"
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Load genre mapping for better analysis
        self.genre_keywords = {
            'rock': ['rock', 'metal', 'punk', 'grunge', 'alternative', 'indie'],
            'pop': ['pop', 'mainstream', 'radio', 'hit', 'chart'],
            'hip_hop': ['hip hop', 'rap', 'trap', 'drill', 'gangsta'],
            'electronic': ['electronic', 'edm', 'techno', 'house', 'dubstep', 'ambient'],
            'jazz': ['jazz', 'blues', 'swing', 'bebop', 'fusion'],
            'classical': ['classical', 'orchestral', 'symphony', 'chamber'],
            'country': ['country', 'folk', 'bluegrass', 'western'],
            'r&b': ['r&b', 'soul', 'motown', 'funk'],
            'reggae': ['reggae', 'ska', 'dancehall'],
            'latin': ['latin', 'salsa', 'merengue', 'bachata', 'reggaeton']
        }
    
    def analyze_playlist(self, playlist_id: str, songs: List[str]) -> Dict[str, any]:
        """Analyze playlist characteristics using Llama."""
        if not songs:
            return self._get_default_analysis(playlist_id)
        
        # Prepare song data for analysis
        song_list = "\n".join([f"- {song}" for song in songs[:20]])  # Limit to first 20 songs
        
        analysis_prompt = f"""
Analyze this music playlist and provide a JSON response with the following information:

Playlist ID: "{playlist_id}"
Songs:
{song_list}

Please analyze and provide:
1. Primary genre(s) - choose from: rock, pop, hip_hop, electronic, jazz, classical, country, r&b, reggae, latin, or "mixed"
2. Mood/atmosphere - choose from: energetic, calm, romantic, nostalgic, party, workout, study, sad, happy, mysterious, or "mixed"
3. Color palette - suggest 3 colors that represent the playlist (hex codes)
4. Visual style - choose from: minimalist, vintage, neon, abstract, geometric, nature, urban, or "mixed"
5. Key elements - suggest 2-3 visual elements that would represent this playlist (e.g., "musical notes", "city skyline", "neon lights")

Respond ONLY with valid JSON in this exact format:
{{
    "genre": "primary_genre",
    "mood": "mood_description",
    "colors": ["#color1", "#color2", "#color3"],
    "style": "visual_style",
    "elements": ["element1", "element2", "element3"]
}}
"""
        
        try:
            response = self._llm.generate(
                model=OLLAMA_MODEL,
                prompt=analysis_prompt,
                options={
                    "stream": False,
                    "temperature": 0.3,  # Lower temperature for more consistent analysis
                    "max_tokens": 200,
                },
            )
            
            # Extract JSON from response
            response_text = response['response'].strip()
            
            # Try to find JSON in the response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_text = response_text[json_start:json_end]
                analysis = json.loads(json_text)
                
                # Validate and clean the analysis
                return self._validate_analysis(analysis, playlist_id, songs)
            else:
                print(f"Could not parse JSON from Llama response: {response_text}")
                return self._get_fallback_analysis(playlist_id, songs)
                
        except Exception as e:
            print(f"Error analyzing playlist with Llama: {e}")
            return self._get_fallback_analysis(playlist_id, songs)
    
    def _validate_analysis(self, analysis: Dict, playlist_id: str, songs: List[str]) -> Dict:
        """Validate and clean the analysis from Llama."""
        valid_genres = ['rock', 'pop', 'hip_hop', 'electronic', 'jazz', 'classical', 'country', 'r&b', 'reggae', 'latin', 'mixed']
        valid_moods = ['energetic', 'calm', 'romantic', 'nostalgic', 'party', 'workout', 'study', 'sad', 'happy', 'mysterious', 'mixed']
        valid_styles = ['minimalist', 'vintage', 'neon', 'abstract', 'geometric', 'nature', 'urban', 'mixed']
        
        # Validate genre
        genre = analysis.get('genre', 'mixed').lower()
        if genre not in valid_genres:
            genre = self._detect_genre_from_songs(songs)
        
        # Validate mood
        mood = analysis.get('mood', 'mixed').lower()
        if mood not in valid_moods:
            mood = 'mixed'
        
        # Validate colors
        colors = analysis.get('colors', [])
        if not isinstance(colors, list) or len(colors) < 3:
            colors = self._generate_colors_from_id(playlist_id)
        
        # Validate style
        style = analysis.get('style', 'mixed').lower()
        if style not in valid_styles:
            style = 'mixed'
        
        # Validate elements
        elements = analysis.get('elements', [])
        if not isinstance(elements, list) or len(elements) < 2:
            elements = ['musical notes', 'sound waves']
        
        return {
            'genre': genre,
            'mood': mood,
            'colors': colors[:3],  # Ensure exactly 3 colors
            'style': style,
            'elements': elements[:3]  # Ensure max 3 elements
        }
    
    def _detect_genre_from_songs(self, songs: List[str]) -> str:
        """Detect genre from song titles using keyword matching."""
        song_text = ' '.join(songs).lower()
        
        genre_scores = {}
        for genre, keywords in self.genre_keywords.items():
            score = sum(1 for keyword in keywords if keyword in song_text)
            if score > 0:
                genre_scores[genre] = score
        
        if genre_scores:
            return max(genre_scores, key=genre_scores.get)
        return 'mixed'
    
    def _generate_colors_from_id(self, playlist_id: str) -> List[str]:
        """Generate colors based on playlist ID with more variety."""
        # Create a hash from the playlist ID
        hash_obj = hashlib.md5(playlist_id.encode())
        hash_int = int(hash_obj.hexdigest(), 16)
        
        colors = []
        for i in range(3):
            # Use different parts of the hash for each color
            hue_seed = (hash_int + i * 120) % 360
            sat_seed = (hash_int + i * 200) % 100
            light_seed = (hash_int + i * 300) % 100
            
            # More vibrant and varied colors
            hue = hue_seed
            saturation = 70 + (sat_seed % 25)  # 70-95% saturation for vibrancy
            lightness = 35 + (light_seed % 30)  # 35-65% lightness for good contrast
            
            # Convert HSL to RGB then to hex
            import colorsys
            rgb = colorsys.hls_to_rgb(hue/360, lightness/100, saturation/100)
            hex_color = f"#{int(rgb[0]*255):02x}{int(rgb[1]*255):02x}{int(rgb[2]*255):02x}"
            colors.append(hex_color)
        
        return colors
    
    def _get_default_analysis(self, playlist_id: str) -> Dict:
        """Get default analysis for empty playlists."""
        return {
            'genre': 'mixed',
            'mood': 'calm',
            'colors': self._generate_colors_from_id(playlist_id),
            'style': 'minimalist',
            'elements': ['musical notes', 'sound waves']
        }
    
    def _get_fallback_analysis(self, playlist_id: str, songs: List[str]) -> Dict:
        """Get fallback analysis when Llama fails."""
        genre = self._detect_genre_from_songs(songs)
        colors = self._generate_colors_from_id(playlist_id)
        
        # Add more variety to fallback elements based on playlist ID
        import random
        random.seed(hash(playlist_id) % 2**32)
        
        # More diverse element options
        element_options = [
            ['musical notes', 'sound waves'],
            ['musical notes', 'geometric shapes'],
            ['sound waves', 'abstract patterns'],
            ['musical notes', 'sound waves', 'geometric shapes'],
            ['abstract patterns', 'musical notes'],
            ['sound waves', 'musical notes', 'abstract patterns']
        ]
        
        # Random style based on playlist ID
        style_options = ['minimalist', 'abstract', 'geometric', 'mixed']
        selected_style = random.choice(style_options)
        
        # Random mood based on playlist ID
        mood_options = ['energetic', 'calm', 'mysterious', 'happy', 'mixed']
        selected_mood = random.choice(mood_options)
        
        selected_elements = random.choice(element_options)
        
        random.seed()  # Reset random seed
        
        return {
            'genre': genre,
            'mood': selected_mood,
            'colors': colors,
            'style': selected_style,
            'elements': selected_elements
        }
    
    def generate_cover_image(self, playlist_id: str, songs: List[str], playlist_name: str = None, size: Tuple[int, int] = (400, 400)) -> str:
        """Generate a playlist cover image based on analysis."""
        # Check cache first
        cache_key = self._get_cache_key(playlist_id, songs)
        cached_image = self._get_cached_image(cache_key)
        if cached_image:
            return cached_image
        
        # Analyze playlist using ID for uniqueness
        analysis = self.analyze_playlist(playlist_id, songs)
        
        # Generate image with consistent cache key as filename
        image_path = self._create_cover_image(playlist_id, analysis, size, cache_key, playlist_name)
        
        # Image is already cached with cache_key as filename
        
        return image_path
    
    def _get_cache_key(self, playlist_id: str, songs: List[str]) -> str:
        """Generate a cache key for the playlist."""
        content = f"{playlist_id}:{':'.join(songs[:10])}"  # Use first 10 songs for cache key
        return hashlib.md5(content.encode()).hexdigest()
    
    def _get_cached_image(self, cache_key: str) -> Optional[str]:
        """Check if image is cached."""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.png")
        if os.path.exists(cache_file):
            return cache_file
        return None
    
    def _cache_image(self, cache_key: str, image_path: str) -> None:
        """Cache the generated image."""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.png")
        if os.path.exists(image_path) and image_path != cache_file:
            import shutil
            shutil.copy2(image_path, cache_file)
    
    def _create_cover_image(self, playlist_id: str, analysis: Dict, size: Tuple[int, int], cache_key: str, playlist_name: str = None) -> str:
        """Create the actual cover image using PIL."""
        width, height = size
        
        # Create image with gradient background
        image = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(image)
        
        # Create gradient background
        colors = analysis['colors']
        self._draw_gradient_background(draw, width, height, colors)
        
        # Add visual elements based on analysis
        self._add_visual_elements(draw, width, height, analysis, playlist_id)
        
        # Use actual playlist name if provided, otherwise fallback to ID-based name
        display_name = playlist_name if playlist_name else f"Playlist {playlist_id[:8]}"
        self._add_playlist_name(draw, width, height, display_name)
        
        # Add genre/mood indicators
        self._add_genre_mood_indicators(draw, width, height, analysis)
        
        # Save image using cache key as filename for consistency
        filename = f"{cache_key}.png"
        filepath = os.path.join(self.cache_dir, filename)
        image.save(filepath, 'PNG')
        
        return filepath
    
    def _draw_gradient_background(self, draw: ImageDraw.Draw, width: int, height: int, colors: List[str]):
        """Draw a gradient background using the analyzed colors."""
        # Convert hex colors to RGB
        rgb_colors = []
        for color in colors:
            if color.startswith('#'):
                hex_color = color[1:]
                rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                rgb_colors.append(rgb)
            else:
                rgb_colors.append((100, 100, 100))  # Fallback color
        
        # Create gradient
        for y in range(height):
            # Interpolate between colors
            ratio = y / height
            if ratio < 0.5:
                # Blend first two colors
                t = ratio * 2
                color1 = rgb_colors[0]
                color2 = rgb_colors[1]
                r = int(color1[0] * (1-t) + color2[0] * t)
                g = int(color1[1] * (1-t) + color2[1] * t)
                b = int(color1[2] * (1-t) + color2[2] * t)
            else:
                # Blend second and third colors
                t = (ratio - 0.5) * 2
                color2 = rgb_colors[1]
                color3 = rgb_colors[2]
                r = int(color2[0] * (1-t) + color3[0] * t)
                g = int(color2[1] * (1-t) + color3[1] * t)
                b = int(color2[2] * (1-t) + color3[2] * t)
            
            draw.line([(0, y), (width, y)], fill=(r, g, b))
    
    def _add_visual_elements(self, draw: ImageDraw.Draw, width: int, height: int, analysis: Dict, playlist_id: str = ""):
        """Add visual elements based on analysis."""
        elements = analysis.get('elements', ['musical notes'])
        style = analysis.get('style', 'mixed')
        
        # Add musical notes
        if 'musical notes' in elements or 'musical' in str(elements).lower():
            self._draw_musical_notes(draw, width, height, playlist_id)
        
        # Add sound waves
        if 'sound waves' in elements or 'waves' in str(elements).lower():
            self._draw_sound_waves(draw, width, height, playlist_id)
        
        # Add geometric patterns based on style or elements
        if style in ['geometric', 'abstract'] or 'geometric shapes' in elements or 'abstract patterns' in elements:
            self._draw_geometric_patterns(draw, width, height, playlist_id)
        elif style == 'vintage':
            self._draw_vintage_elements(draw, width, height, playlist_id)
        elif style == 'neon':
            self._draw_neon_elements(draw, width, height, playlist_id)
    
    def _draw_musical_notes(self, draw: ImageDraw.Draw, width: int, height: int, playlist_id: str = ""):
        """Draw musical notes on the image with randomization based on playlist ID."""
        import random
        
        # Use playlist ID as seed for consistent randomization
        random.seed(hash(playlist_id) % 2**32)
        
        # Generate random number of notes (3-6)
        num_notes = random.randint(3, 6)
        
        for i in range(num_notes):
            # Random positions
            x = random.randint(int(width * 0.1), int(width * 0.9))
            y = random.randint(int(height * 0.2), int(height * 0.8))
            
            # Random sizes
            note_size = random.randint(6, 12)
            stem_length = random.randint(15, 30)
            
            # Random colors (white, light gray, or very light colors)
            note_colors = ['white', '#f0f0f0', '#e0e0e0', '#d0d0d0']
            note_color = random.choice(note_colors)
            
            # Draw note head (circle)
            draw.ellipse([x-note_size, y-note_size, x+note_size, y+note_size], 
                        fill=note_color, outline='black', width=1)
            
            # Draw stem (line) - sometimes up, sometimes down
            stem_direction = random.choice([-1, 1])
            stem_end_y = y + (stem_length * stem_direction)
            draw.line([x+note_size, y-note_size, x+note_size, stem_end_y], 
                     fill='black', width=2)
            
            # Draw flag (small rectangle) - only sometimes
            if random.random() > 0.5:
                flag_width = random.randint(4, 8)
                flag_height = random.randint(3, 6)
                draw.rectangle([x+note_size, stem_end_y, x+note_size+flag_width, stem_end_y+flag_height], 
                              fill='black')
        
        # Reset random seed
        random.seed()
    
    def _draw_sound_waves(self, draw: ImageDraw.Draw, width: int, height: int, playlist_id: str = ""):
        """Draw sound wave patterns with randomization based on playlist ID."""
        import random
        import math
        
        # Use playlist ID as seed for consistent randomization
        random.seed(hash(playlist_id + "waves") % 2**32)
        
        # Random number of wave lines (2-4)
        num_waves = random.randint(2, 4)
        
        for i in range(num_waves):
            # Random wave position and size
            wave_y = random.randint(int(height * 0.6), int(height * 0.9))
            wave_width = random.randint(int(width * 0.6), int(width * 0.9))
            wave_start_x = random.randint(int(width * 0.05), int(width * 0.2))
            
            # Random wave properties
            amplitude = random.randint(5, 20)
            frequency = random.uniform(0.05, 0.2)
            wave_color = random.choice(['white', '#f0f0f0', '#e0e0e0'])
            wave_width_px = random.randint(1, 3)
            
            points = []
            for x in range(int(wave_start_x), int(wave_start_x + wave_width), 3):
                y = wave_y + amplitude * math.sin((x - wave_start_x) * frequency)
                points.append((x, y))
            
            if len(points) > 1:
                draw.line(points, fill=wave_color, width=wave_width_px)
        
        # Reset random seed
        random.seed()
    
    def _draw_geometric_patterns(self, draw: ImageDraw.Draw, width: int, height: int, playlist_id: str = ""):
        """Draw geometric patterns with randomization."""
        import random
        
        # Use playlist ID as seed for consistent randomization
        random.seed(hash(playlist_id + "geo") % 2**32)
        
        # Random number of shapes (2-5)
        num_shapes = random.randint(2, 5)
        shape_types = ['triangle', 'circle', 'square']
        
        for i in range(num_shapes):
            shape_type = random.choice(shape_types)
            x = random.randint(int(width * 0.1), int(width * 0.9))
            y = random.randint(int(height * 0.1), int(height * 0.9))
            size = random.randint(int(min(width, height) * 0.05), int(min(width, height) * 0.15))
            
            if shape_type == 'triangle':
                points = [
                    (x, y - size),
                    (x - size, y + size),
                    (x + size, y + size)
                ]
                draw.polygon(points, fill='white', outline='black', width=1)
            elif shape_type == 'circle':
                draw.ellipse([x-size, y-size, x+size, y+size], fill='white', outline='black', width=1)
            elif shape_type == 'square':
                draw.rectangle([x-size, y-size, x+size, y+size], fill='white', outline='black', width=1)
        
        # Reset random seed
        random.seed()
    
    def _draw_vintage_elements(self, draw: ImageDraw.Draw, width: int, height: int, playlist_id: str = ""):
        """Draw vintage-style elements with randomization."""
        import random
        
        # Use playlist ID as seed for consistent randomization
        random.seed(hash(playlist_id + "vintage") % 2**32)
        
        # Random border width
        border_width = random.randint(8, 15)
        draw.rectangle([border_width, border_width, width-border_width, height-border_width], 
                      outline='white', width=border_width)
        
        # Random corner decorations
        corner_size = random.randint(15, 25)
        corners = [(0, 0), (width-corner_size, 0), (0, height-corner_size), (width-corner_size, height-corner_size)]
        for x, y in corners:
            if random.random() > 0.3:  # Sometimes skip corners
                draw.rectangle([x, y, x+corner_size, y+corner_size], fill='white')
        
        # Reset random seed
        random.seed()
    
    def _draw_neon_elements(self, draw: ImageDraw.Draw, width: int, height: int, playlist_id: str = ""):
        """Draw neon-style elements with randomization."""
        import random
        
        # Use playlist ID as seed for consistent randomization
        random.seed(hash(playlist_id + "neon") % 2**32)
        
        # Random number of circles (2-4)
        num_circles = random.randint(2, 4)
        
        for i in range(num_circles):
            x = random.randint(int(width * 0.2), int(width * 0.8))
            y = random.randint(int(height * 0.2), int(height * 0.8))
            
            # Random sizes
            outer_radius = random.randint(20, 35)
            inner_radius = random.randint(10, 20)
            
            # Random neon colors
            neon_colors = [
                (255, 100, 255),  # Pink
                (100, 255, 255),  # Cyan
                (255, 255, 100),  # Yellow
                (100, 255, 100),  # Green
                (255, 100, 100),  # Red
            ]
            neon_color = random.choice(neon_colors)
            
            # Outer glow
            draw.ellipse([x-outer_radius, y-outer_radius, x+outer_radius, y+outer_radius], 
                        fill=(*neon_color, 50))
            # Inner circle
            draw.ellipse([x-inner_radius, y-inner_radius, x+inner_radius, y+inner_radius], 
                        fill=neon_color)
        
        # Reset random seed
        random.seed()
    
    def _add_playlist_name(self, draw: ImageDraw.Draw, width: int, height: int, playlist_name: str):
        """Add playlist name to the image."""
        try:
            # Try to use a system font
            font_size = min(width, height) // 15
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            # Fallback to default font
            font = ImageFont.load_default()
        
        # Calculate text position
        text_bbox = draw.textbbox((0, 0), playlist_name, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        x = (width - text_width) // 2
        y = height - text_height - 20
        
        # Draw text with outline for better visibility
        draw.text((x-1, y-1), playlist_name, font=font, fill='black')
        draw.text((x+1, y-1), playlist_name, font=font, fill='black')
        draw.text((x-1, y+1), playlist_name, font=font, fill='black')
        draw.text((x+1, y+1), playlist_name, font=font, fill='black')
        draw.text((x, y), playlist_name, font=font, fill='white')
    
    def _add_genre_mood_indicators(self, draw: ImageDraw.Draw, width: int, height: int, analysis: Dict):
        """Add genre and mood indicators."""
        genre = analysis.get('genre', 'mixed')
        mood = analysis.get('mood', 'mixed')
        
        # Add small indicators in corners
        indicator_size = 15
        
        # Genre indicator (top-left)
        genre_colors = {
            'rock': (139, 69, 19),      # Brown
            'pop': (255, 20, 147),      # Pink
            'hip_hop': (255, 165, 0),   # Orange
            'electronic': (0, 255, 255), # Cyan
            'jazz': (255, 215, 0),      # Gold
            'classical': (128, 0, 128), # Purple
            'country': (34, 139, 34),   # Forest Green
            'r&b': (255, 69, 0),        # Red Orange
            'reggae': (0, 128, 0),      # Green
            'latin': (255, 0, 0),       # Red
            'mixed': (128, 128, 128)    # Gray
        }
        
        genre_color = genre_colors.get(genre, (128, 128, 128))
        draw.ellipse([10, 10, 10+indicator_size, 10+indicator_size], fill=genre_color)
        
        # Mood indicator (top-right)
        mood_colors = {
            'energetic': (255, 0, 0),    # Red
            'calm': (0, 0, 255),        # Blue
            'romantic': (255, 192, 203), # Pink
            'nostalgic': (255, 165, 0),  # Orange
            'party': (255, 20, 147),     # Hot Pink
            'workout': (0, 255, 0),      # Green
            'study': (0, 0, 139),        # Dark Blue
            'sad': (105, 105, 105),      # Dim Gray
            'happy': (255, 255, 0),      # Yellow
            'mysterious': (75, 0, 130),  # Indigo
            'mixed': (128, 128, 128)     # Gray
        }
        
        mood_color = mood_colors.get(mood, (128, 128, 128))
        draw.ellipse([width-indicator_size-10, 10, width-10, 10+indicator_size], fill=mood_color)

# Import math for wave calculations
import math

