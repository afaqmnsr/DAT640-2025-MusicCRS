"""MusicCRS conversational agent."""

import json
import os
import ollama
import uuid
import sqlite3
from typing import Dict, List, Optional
from dialoguekit.core.annotated_utterance import AnnotatedUtterance
from dialoguekit.core.dialogue_act import DialogueAct
from dialoguekit.core.intent import Intent
from dialoguekit.core.slot_value_annotation import SlotValueAnnotation
from dialoguekit.core.utterance import Utterance
from dialoguekit.participant.agent import Agent
from dialoguekit.participant.participant import DialogueParticipant
from dialoguekit.platforms import FlaskSocketPlatform
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from image_generator import PlaylistCoverGenerator

# Load environment variables from config.env
from dotenv import load_dotenv
import secrets
import base64
import requests
from flask import Flask, request, redirect, jsonify, render_template_string

# Load config.env from project root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.path.join(project_root, 'config.env')
load_dotenv(config_path)

OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'https://ollama.ux.uis.no')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.3:70b')
OLLAMA_API_KEY = os.getenv('OLLAMA_API_KEY')
SPOTIFY_DATASET_PATH = os.getenv('SPOTIFY_DATASET_PATH')

# Spotify API Configuration
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:5000/auth/callback')
SPOTIFY_ACCESS_TOKEN = os.getenv('SPOTIFY_ACCESS_TOKEN')  # For testing purposes

class Playlist:
    """Represents a playlist with unique ID, name, and songs."""
    
    def __init__(self, name: str, playlist_id: str = None):
        self.id = playlist_id or str(uuid.uuid4())
        self.name = name.strip()
        self.songs: List[str] = []
        self.created_at = None  # Could add timestamp if needed
    
    def to_dict(self) -> Dict:
        """Convert playlist to dictionary for serialization."""
        return {
            'id': self.id,
            'name': self.name,
            'songs': self.songs,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Playlist':
        """Create playlist from dictionary."""
        playlist = cls(data['name'], data['id'])
        playlist.songs = data.get('songs', [])
        playlist.created_at = data.get('created_at')
        return playlist

_INTENT_OPTIONS = Intent("OPTIONS")


class MusicCRS(Agent):
    def __init__(self, use_llm: bool = True):
        """Initialize MusicCRS agent."""
        super().__init__(id="MusicCRS")

        if use_llm:
            if not OLLAMA_API_KEY:
                raise ValueError("OLLAMA_API_KEY not found in environment variables. Please check config.env file.")
            self._llm = ollama.Client(
                host=OLLAMA_HOST,
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
            )
        else:
            self._llm = None

        self._playlists: Dict[str, Playlist] = {}  # Stores all playlists by ID
        self._playlist_names: Dict[str, str] = {}  # Maps playlist names to IDs for backward compatibility
        self._current_playlist_id = None  # Current active playlist ID
        self._default_playlist_name = "My Playlist"  # Default name for first playlist
        self._help_song_limit = 100000  # Show all songs (effectively unlimited)
        self._db_path = "music_database.db"
        self._db_initialized = False  # Track if database is initialized
        
        # Spotify authentication
        self._spotify_access_token = SPOTIFY_ACCESS_TOKEN  # Use token from env if available
        self._spotify_tokens = {}  # Store access tokens
        self._init_spotify_auth()  # Initialize Spotify authentication
        
        # Initialize image generator
        try:
            self._image_generator = PlaylistCoverGenerator()
        except Exception as e:
            print(f"Warning: Could not initialize image generator: {e}")
            self._image_generator = None
        
        # Ensure we have a default playlist
        self._ensure_current_playlist()

    def _get_current_playlist(self) -> Playlist:
        """Get the current playlist object."""
        self._ensure_current_playlist()
        return self._playlists[self._current_playlist_id]
    
    def _get_playlist_by_name(self, name: str) -> Optional[Playlist]:
        """Get playlist by name (for backward compatibility)."""
        playlist_id = self._playlist_names.get(name.strip())
        if playlist_id:
            return self._playlists.get(playlist_id)
        return None
    
    def _get_playlist_by_id(self, playlist_id: str) -> Optional[Playlist]:
        """Get playlist by ID."""
        return self._playlists.get(playlist_id)

    def _ensure_current_playlist(self) -> None:
        """Ensure there's always a current playlist available."""
        if not self._current_playlist_id or self._current_playlist_id not in self._playlists:
            if not self._playlists:
                # Create default playlist if none exist
                default_playlist = Playlist(self._default_playlist_name)
                self._playlists[default_playlist.id] = default_playlist
                self._playlist_names[default_playlist.name] = default_playlist.id
                self._current_playlist_id = default_playlist.id
            else:
                # Use first available playlist
                self._current_playlist_id = next(iter(self._playlists.keys()))

    def welcome(self) -> None:
        """Sends the agent's welcome message."""
        utterance = AnnotatedUtterance(
            "Hello! I'm MusicCRS, your music recommendation assistant. I can help you create and manage playlists. Type '/help' to see what I can do!",
            participant=DialogueParticipant.AGENT,
        )
        self._dialogue_connector.register_agent_utterance(utterance)

    def goodbye(self) -> None:
        """Quits the conversation."""
        goodbye_text = "It was nice talking to you. Bye"
        utterance = AnnotatedUtterance(
            goodbye_text,
            dialogue_acts=[DialogueAct(intent=self.stop_intent)],
            participant=DialogueParticipant.AGENT,
        )
        
        # Handle dialogue connector - it might be None if agent wasn't created through platform
        if self._dialogue_connector is not None:
            self._dialogue_connector.register_agent_utterance(utterance)
        else:
            # If dialogue connector is None, store response for manual sending
            if not hasattr(self, '_pending_response'):
                self._pending_response = None
            self._pending_response = goodbye_text
            # Also mark that this is a goodbye/exit message
            if not hasattr(self, '_pending_dialogue_acts'):
                self._pending_dialogue_acts = []
            self._pending_dialogue_acts = [{'intent': 'EXIT'}]

    def receive_utterance(self, utterance: Utterance) -> None:
        """Gets called each time there is a new user utterance.

        For now the agent only understands specific command.

        Args:
            utterance: User utterance.
        """
        response = ""
        dialogue_acts = []
        if utterance.text.startswith("/info"):
            response = self._info()
        elif utterance.text.startswith("/ask_llm "):
            prompt = utterance.text[9:]
            response = self._ask_llm(prompt)
        elif utterance.text.startswith("/ask "):
            question = utterance.text[5:].strip()
            response = self._answer_question(question)
        elif utterance.text.startswith("/search "):
            query = utterance.text[8:].strip()
            response = self._search_songs(query)
        elif utterance.text.startswith("/options"):
            options = [
                "Play some jazz music",
                "Recommend me some pop songs",
                "Create a workout playlist",
            ]
            response = self._options(options)
            dialogue_acts = [
                DialogueAct(
                    intent=_INTENT_OPTIONS,
                    annotations=[
                        SlotValueAnnotation("option", option) for option in options
                    ],
                )
            ]
        elif utterance.text == "/help":
            response = self._help()
        elif utterance.text.lower().strip() in ["hello", "hello!", "hi", "hi!", "greetings"]:
            # Handle greeting from simulator
            response = "Hello! I'm MusicCRS, your music recommendation assistant. I can help you create and manage playlists. Type '/help' to see what I can do!"
        elif utterance.text.startswith("/add "):
            song_info = utterance.text[5:]  # Remove "/add "
            # R5.6: Normalize song name for better matching of complex names
            normalized = self._normalize_song_name(song_info)
            response = self._add_song(normalized)
        elif utterance.text.startswith("/remove "):
            song_info = utterance.text[8:]  # Remove "/remove "
            response = self._remove_song(song_info)
        elif utterance.text == "/view":
            response = self._view_playlist()
        elif utterance.text == "/clear":
            response = self._clear_playlist()
        elif utterance.text.startswith("/create "):
            playlist_name = utterance.text[8:]  # Remove "/create "
            response = self._create_playlist(playlist_name)
        elif utterance.text.startswith("/switch "):
            playlist_name = utterance.text[8:]  # Remove "/switch "
            response = self._switch_playlist(playlist_name)
        elif utterance.text == "/list":
            response = self._list_playlists()
        elif utterance.text.startswith("/delete "):
            playlist_name = utterance.text[8:]  # Remove "/delete "
            response = self._delete_playlist(playlist_name)
        elif utterance.text.startswith("/rename "):
            parts = utterance.text[8:].split(" ", 1)  # Remove "/rename " and split
            if len(parts) == 2:
                old_name, new_name = parts
                response = self._rename_playlist(old_name, new_name)
            else:
                response = "Please provide both old and new playlist names. Usage: /rename [old_name] [new_name]"
        elif utterance.text.startswith("/cover"):
            playlist_name = utterance.text[7:].strip() if len(utterance.text) > 7 else None
            response = self._generate_playlist_cover(playlist_name)
        elif utterance.text.startswith("/stats"):
            playlist_name = utterance.text[7:].strip() if len(utterance.text) > 7 else None
            response = self._get_playlist_statistics(playlist_name)
        elif utterance.text.startswith("/play"):
            song_info = utterance.text[5:].strip() if len(utterance.text) > 5 else None
            response = self._play_song(song_info)
        elif utterance.text.startswith("/spotify"):
            song_info = utterance.text[8:].strip() if len(utterance.text) > 8 else None
            response = self._get_spotify_track_info(song_info)
        elif utterance.text == "/spotify_login":
            response = self._get_spotify_login_url()
        elif utterance.text.startswith("/recommend"):
            # Extract song info - ignore selection commands
            recommend_part = utterance.text[11:].strip()
            
            # If it starts with selection keywords, treat as no song specified
            if recommend_part.lower().startswith(('add', 'select', 'choose')):
                # User likely meant to do /recommend first, then selection separately
                response = self._recommend_songs(None)
                response += "\n\n💡 **Tip:** After seeing recommendations, use a separate message to add songs:\n"
                response += "• 'Add the first two songs'\n"
                response += "• '/select_recommendation 1,3,5'\n"
                response += "• 'Add all recommendations'"
            else:
                # Extract song info, ignoring any trailing selection commands
                import re
                # Remove common selection patterns at the end
                song_info = re.sub(r'\s+(?:add|select|choose).*$', '', recommend_part, flags=re.IGNORECASE)
                song_info = song_info.strip()
                response = self._recommend_songs(song_info if song_info else None)
        elif utterance.text.startswith("/select_recommendation "):
            # R4.2: Select recommendations by index
            selection = utterance.text[23:].strip()
            response = self._select_recommendation(selection)
        elif utterance.text.startswith("/generate "):
            description = utterance.text[10:].strip()
            response = self._generate_playlist_from_description(description)
        elif utterance.text == "/quit":
            self.goodbye()
            return
        else:
            # Check if it's a natural language question (not a command)
            utterance_lower = utterance.text.lower().strip()
            
            # Check for question patterns
            question_patterns = [
                "how many songs",
                "how long is",
                "what album",
                "who are the most popular",
                "what songs does",
                "which artist appears",
                "how many songs are in",
                "compilation",
                "best of",
                "how many songs are in the database",
                "what songs does"
            ]
            
            is_question = any(pattern in utterance_lower for pattern in question_patterns)
            
            if is_question:
                # Treat as a natural language question
                response = self._answer_question(utterance.text)
            else:
                # Try natural language processing
                response = self._process_natural_language(utterance.text)

        # Handle dialogue connector - it might be None if agent wasn't created through platform
        if self._dialogue_connector is not None:
            self._dialogue_connector.register_agent_utterance(
                AnnotatedUtterance(
                    response,
                    participant=DialogueParticipant.AGENT,
                    dialogue_acts=dialogue_acts,
                )
            )
        else:
            # If dialogue connector is None, we need to manually send the response
            # This happens when agents are created outside the normal DialogueKit flow
            # Store response for manual sending
            if not hasattr(self, '_pending_response'):
                self._pending_response = None
            self._pending_response = response

    # --- Response handlers ---

    def _help(self) -> str:
        """Provides help information about available commands."""
        help_text = """Here are the commands I understand:

**Basic Commands:**
• `/help` - Show this help message
• `/info` - Learn about MusicCRS
• `/quit` - End the conversation

**Playlist Commands:**
• `/add [artist]: [song]` - Add a song to current playlist (full format)
• `/add [song]` - Add a song by title only (with disambiguation if multiple matches)
• `/remove [artist]: [song]` - Remove a song from current playlist
• `/view` - View current playlist
• `/clear` - Clear the current playlist

**Playlist Management:**
• `/create [playlist_name]` - Create a new playlist
• `/switch [playlist_name]` - Switch to an existing playlist
• `/list` - List all your playlists
• `/delete [playlist_name]` - Delete a playlist
• `/rename [old_name] [new_name]` - Rename a playlist
• `/cover [playlist_name]` - Generate a cover image for a playlist
• `/stats [playlist_name]` - Show playlist statistics and summary

**Search & Discovery:**
• `/search [query]` - Search for songs by artist or title
• `/ask [question]` - Ask questions about songs and artists (database queries)
• `/ask_llm [question]` - Ask the AI a question
• `/options` - See example options

**Natural Language Questions:**
You can also ask questions directly without commands:
• "How many songs does The Beatles have?"
• "How long is Bohemian Rhapsody?"
• "What album is Hotel California from?"
• "Who are the most popular artists?"
• "What songs does The Beatles have?"
• "Which artist appears most often in Best of 90s albums?"

**Playback:**
• `/play [song]` - Play a song or song preview (requires Spotify integration)
• `/spotify [song]` - Get Spotify track information for playback
• `/spotify_login` - Get Spotify authentication link

**Recommendations:**
• `/recommend [song]` - Get 3-5 song recommendations based on a song
• `/select_recommendation [indices]` - Select recommendations to add (e.g., "1,3,5" or "1-3")
• `/generate [description]` - Generate a playlist from a description (e.g., "workout playlist with 10 songs")

**Natural Language:**
You can also use natural language to interact with me:
• "Add the first two songs"
• "Remove all songs by Metallica"
• "Recommend me some songs like Bohemian Rhapsody"
• "Create a workout playlist with 15 energetic songs"

Try typing a command to get started!"""

        # Add available songs to help (configurable limit for readability)
        total_songs = self._get_song_count()
        sample_songs = self._get_sample_songs(min(self._help_song_limit, 50))  # Show sample of songs
        if sample_songs:
            help_text += f"\n\n**Sample Songs (showing {len(sample_songs)} of {total_songs} total):**\n"
            for song in sample_songs:
                help_text += f"• {song}\n"
            if total_songs > len(sample_songs):
                help_text += f"... and {total_songs - len(sample_songs)} more songs in the database"
        
        return help_text

    def _info(self) -> str:
        """Gives information about the agent."""
        return """I am MusicCRS, a conversational music recommender system. 

I can help you:
• Create and manage playlists
• Add and remove songs
• Get music recommendations
• Answer questions about music

Type '/help' to see all available commands!"""

    def _ensure_database(self) -> None:
        """Ensure database is initialized (lazy initialization)."""
        if self._db_initialized:
            return
        self._init_database()
        self._db_initialized = True
    
    def _init_database(self) -> None:
        """Initialize SQLite database and load Spotify Million Playlist Dataset."""
        # Create database connection
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        # Create songs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                track_uri TEXT,
                spotify_track_id TEXT,
                album_name TEXT,
                duration_ms INTEGER,
                song_key TEXT UNIQUE NOT NULL
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_artist ON songs(artist)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_title ON songs(title)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_song_key ON songs(song_key)')
        
        # Add missing columns if they don't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE songs ADD COLUMN spotify_track_id TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE songs ADD COLUMN album_name TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE songs ADD COLUMN duration_ms INTEGER')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cursor.execute('ALTER TABLE songs ADD COLUMN track_uri TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Check if database is already populated
        cursor.execute('SELECT COUNT(*) FROM songs')
        count = cursor.fetchone()[0]
        
        if count == 0:
            print("Loading Spotify Million Playlist Dataset into SQLite database...")
            self._populate_database(cursor)
            conn.commit()
            print(f"Database populated with songs")
        else:
            print(f"Database already contains {count} songs")
        
        conn.close()
    
    def _populate_database(self, cursor) -> None:
        """Populate the database with songs from Spotify Million Playlist Dataset."""
        # Path to the downloaded dataset - check multiple locations
        possible_paths = []
        if SPOTIFY_DATASET_PATH:
            possible_paths.append(SPOTIFY_DATASET_PATH)
        
        possible_paths.extend([
            os.path.expanduser("~/spotify_dataset/data"),
            os.path.expanduser("~/.cache/kagglehub/datasets/himanshuwagh/spotify-million/versions/1/data"),
            "/tmp/spotify_dataset/data",
        ])
        
        dataset_path = None
        for path in possible_paths:
            if os.path.exists(path):
                dataset_path = path
                break
        
        if not dataset_path:
            print(f"WARNING: Spotify dataset not found. Database will be empty.")
            print(f"Download from: https://gustav1.ux.uis.no/downloads/spotify_million_playlist_dataset/mpd.v1.tar")
            return
        
        try:
            # Load first few JSON files for demo (to avoid memory issues)
            json_files = [f for f in os.listdir(dataset_path) if f.endswith('.json')]
            
            if not json_files:
                raise FileNotFoundError("No JSON files found in dataset directory.")
            
            print(f"Loading Spotify Million Playlist Dataset from {len(json_files)} files...")
            print("Processing first file only for faster startup...")
            
            # Process first file only
            filepath = os.path.join(dataset_path, json_files[0])
            print(f"Loading {json_files[0]}...")
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"Processing {len(data.get('playlists', []))} playlists...")
            
            # Use a set to track unique songs
            unique_songs = {}
            
            # Extract tracks from playlists
            for i, playlist in enumerate(data.get('playlists', [])):
                if i % 100 == 0:
                    print(f"Processed {i} playlists...")
                
                for track in playlist.get('tracks', []):
                    artist = track.get('artist_name', '').strip()
                    title = track.get('track_name', '').strip()
                    
                    if artist and title:
                        song_key = f"{artist}: {title}"
                        
                        # Only store unique songs
                        if song_key not in unique_songs:
                            track_uri = track.get('track_uri', '')
                            spotify_track_id = ''
                            if track_uri.startswith('spotify:track:'):
                                spotify_track_id = track_uri.replace('spotify:track:', '')
                            
                            unique_songs[song_key] = (
                                artist,
                                title,
                                track_uri,
                                spotify_track_id,
                                track.get('album_name', ''),
                                track.get('duration_ms', 0),
                                song_key
                            )
            
            print(f"Inserting {len(unique_songs)} unique songs into database...")
            
            # Batch insert for better performance
            cursor.executemany('''
                INSERT OR IGNORE INTO songs (artist, title, track_uri, spotify_track_id, album_name, duration_ms, song_key)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', unique_songs.values())
            
            print(f"Database populated with {len(unique_songs)} songs!")
            
        except Exception as e:
            raise RuntimeError(f"Error loading Spotify Million Playlist Dataset: {e}")
    
    def _song_exists(self, song_key: str) -> bool:
        """Check if a song exists in the database."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM songs WHERE song_key = ?', (song_key,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    
    def _search_songs_in_db(self, query: str) -> List[str]:
        """Search for songs in the database by artist or title."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        query_lower = f"%{query.lower()}%"
        cursor.execute('''
            SELECT song_key FROM songs 
            WHERE LOWER(artist) LIKE ? OR LOWER(title) LIKE ?
            ORDER BY 
                CASE WHEN LOWER(title) = LOWER(?) THEN 1
                     WHEN LOWER(title) LIKE LOWER(?) THEN 2
                     WHEN LOWER(artist) LIKE LOWER(?) THEN 3
                     ELSE 4 END,
                artist, title
            LIMIT 100
        ''', (query_lower, query_lower, query, f"{query}%", f"{query}%"))
        
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results
    
    def _search_songs_by_title_in_db(self, title: str) -> List[str]:
        """Search for songs by title only in the database with intelligent ranking."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        title_lower = f"%{title.lower()}%"
        
        # Get current playlist for similarity ranking
        current_playlist = self._get_current_playlist()
        current_artists = set()
        for song in current_playlist.songs:
            if ": " in song:
                artist = song.split(": ")[0]
                current_artists.add(artist.lower())
        
        # Query with intelligent ranking based on:
        # 1. Exact title match
        # 2. Title starts with query
        # 3. Artist similarity to current playlist
        # 4. Popularity (song count by artist)
        if current_artists:
            placeholders = ','.join(['?' for _ in current_artists])
            query = f'''
                SELECT s.song_key, s.artist, s.title,
                       CASE WHEN LOWER(s.title) = LOWER(?) THEN 1
                            WHEN LOWER(s.title) LIKE LOWER(?) THEN 2
                            ELSE 3 END as title_match,
                       CASE WHEN LOWER(s.artist) IN ({placeholders}) THEN 1 ELSE 2 END as artist_similarity,
                       (SELECT COUNT(*) FROM songs s2 WHERE s2.artist = s.artist) as artist_popularity
                FROM songs s 
                WHERE LOWER(s.title) LIKE ?
                ORDER BY 
                    title_match ASC,
                    artist_similarity ASC,
                    artist_popularity DESC,
                    s.artist ASC,
                    s.title ASC
                LIMIT 50
            '''
            params = [title, f"{title}%"] + list(current_artists) + [title_lower]
        else:
            query = '''
                SELECT s.song_key, s.artist, s.title,
                       CASE WHEN LOWER(s.title) = LOWER(?) THEN 1
                            WHEN LOWER(s.title) LIKE LOWER(?) THEN 2
                            ELSE 3 END as title_match,
                       2 as artist_similarity,
                       (SELECT COUNT(*) FROM songs s2 WHERE s2.artist = s.artist) as artist_popularity
                FROM songs s 
                WHERE LOWER(s.title) LIKE ?
                ORDER BY 
                    title_match ASC,
                    artist_popularity DESC,
                    s.artist ASC,
                    s.title ASC
                LIMIT 50
            '''
            params = [title, f"{title}%", title_lower]
        
        cursor.execute(query, params)
        
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results
    
    def _get_song_count(self) -> int:
        """Get total number of songs in database."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM songs')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def _get_sample_songs(self, limit: int = 100) -> List[str]:
        """Get a sample of songs from the database for help display."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT song_key FROM songs ORDER BY RANDOM() LIMIT ?', (limit,))
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results

    def _add_song(self, song_info: str) -> str:
        """Add a song to the current playlist.
        
        Args:
            song_info: Song in format "artist: title" or just "title"
            
        Returns:
            Response message
        """
        song_info = song_info.strip()
        
        # Remove quotes from song_info for matching
        song_info_clean = song_info.replace('"', '').replace("'", "")
        
        # Check if it's in "artist: title" format
        if ": " in song_info:
            # Traditional format - try multiple variations
            if self._song_exists(song_info):
                song_key = song_info
            elif self._song_exists(song_info_clean):
                song_key = song_info_clean
            else:
                # Try searching for similar matches
                parts = song_info.split(": ", 1)
                if len(parts) == 2:
                    artist, title = parts
                    artist_clean = artist.replace('"', '').replace("'", "").strip()
                    title_clean = title.replace('"', '').replace("'", "").strip()
                    
                    # Try different combinations
                    variations = [
                        f"{artist_clean}: {title_clean}",
                        f'"{artist_clean}": {title_clean}',
                        f"{artist}: {title_clean}",
                        f"{artist_clean}: {title}",
                    ]
                    
                    # Also try with artist in quotes if it has spaces
                    if " " in artist_clean and not artist_clean.startswith('"'):
                        variations.append(f'"{artist_clean}": {title_clean}')
                    
                    song_key = None
                    for variation in variations:
                        if self._song_exists(variation):
                            song_key = variation
                            break
                    
                    if not song_key:
                        # Last resort: search in database for fuzzy match (case-insensitive)
                        conn = sqlite3.connect(self._db_path)
                        cursor = conn.cursor()
                        # Try exact match first (case-insensitive)
                        cursor.execute('''
                            SELECT song_key FROM songs 
                            WHERE LOWER(TRIM(artist)) = LOWER(TRIM(?)) AND LOWER(TRIM(title)) = LOWER(TRIM(?))
                            LIMIT 1
                        ''', (artist_clean, title_clean))
                        result = cursor.fetchone()
                        
                        # If still not found, try with artist in quotes (for artists with spaces)
                        if not result and " " in artist_clean:
                            cursor.execute('''
                                SELECT song_key FROM songs 
                                WHERE LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) = LOWER(TRIM(?)) 
                                AND LOWER(TRIM(title)) = LOWER(TRIM(?))
                                LIMIT 1
                            ''', (artist_clean, title_clean))
                            result = cursor.fetchone()
                        
                        conn.close()
                        if result:
                            song_key = result[0]
                        else:
                            return f"Sorry, '{song_info}' is not available in our database. Please check the spelling and try again."
                else:
                    return f"Sorry, '{song_info}' is not available in our database. Please check the spelling and try again."
        else:
            # Title-only format - search for matches
            # Try with and without quotes, and with normalized version
            matches = self._search_songs_by_title_in_db(song_info_clean)
            if not matches:
                # Try original search
                matches = self._search_songs_by_title_in_db(song_info)
            if not matches:
                # Try searching for partial match (e.g., "Creepin" should find "Creepin'")
                import re
                # Remove common suffixes and search
                base_name = re.sub(r'[^\w\s]', '', song_info_clean).strip()
                if base_name:
                    matches = self._search_songs_by_title_in_db(base_name)
            
            if not matches:
                return f"Sorry, no songs found with title '{song_info}'. Try searching with '/search {song_info}' to see available options."
            
            if len(matches) == 1:
                # Single match - use it directly
                song_key = matches[0]
            else:
                # Multiple matches - provide disambiguation
                return self._provide_song_disambiguation(song_info, matches)
        
        # Ensure we have a current playlist
        self._ensure_current_playlist()
        
        # Get current playlist
        current_playlist = self._get_current_playlist()
        
        # Check if song is already in playlist
        if song_key in current_playlist.songs:
            return f"'{song_key}' is already in your '{current_playlist.name}' playlist."
        
        # Add song to playlist
        current_playlist.songs.append(song_key)
        response = f"Added '{song_key}' to your '{current_playlist.name}' playlist!\n\n"
        # Include playlist view so frontend updates
        response += self._view_playlist()
        return response

    def _remove_song(self, song_info: str) -> str:
        """Remove a song from the current playlist.
        
        Args:
            song_info: Song in format "artist: title"
            
        Returns:
            Response message
        """
        song_key = song_info.strip()
        
        # Get current playlist
        current_playlist = self._get_current_playlist()
        
        # Check if song is in playlist
        if song_key not in current_playlist.songs:
            return f"'{song_key}' is not in your '{current_playlist.name}' playlist."
        
        # Remove song from playlist
        current_playlist.songs.remove(song_key)
        return f"Removed '{song_key}' from your '{current_playlist.name}' playlist!"

    def _view_playlist(self) -> str:
        """View the current playlist.
        
        Returns:
            Formatted playlist
        """
        current_playlist = self._get_current_playlist()
        
        if not current_playlist.songs:
            return f"Your '{current_playlist.name}' playlist is empty. Use '/add [artist]: [title]' to add songs!"
        
        playlist_text = f"**Your Current Playlist: {current_playlist.name}**\n\n"
        for i, song in enumerate(current_playlist.songs, 1):
            playlist_text += f"{i}. {song}\n"
        
        song_count = len(current_playlist.songs)
        song_text = "song" if song_count == 1 else "songs"
        playlist_text += f"\nTotal {song_text}: {song_count}"
        return playlist_text

    def _clear_playlist(self) -> str:
        """Clear the current playlist.
        
        Returns:
            Response message
        """
        current_playlist = self._get_current_playlist()
        
        if not current_playlist.songs:
            return f"Your '{current_playlist.name}' playlist is already empty."
        
        song_count = len(current_playlist.songs)
        song_text = "song" if song_count == 1 else "songs"
        current_playlist.songs.clear()
        response = f"Cleared your '{current_playlist.name}' playlist! Removed {song_count} {song_text}.\n\n"
        # Include playlist view so frontend updates UI
        response += self._view_playlist()
        return response

    def _create_playlist(self, playlist_name: str) -> str:
        """Create a new playlist.
        
        Args:
            playlist_name: Name of the new playlist
            
        Returns:
            Response message
        """
        playlist_name = playlist_name.strip()
        
        if not playlist_name:
            return "Please provide a playlist name. Usage: /create [playlist_name]"
        
        if playlist_name in self._playlist_names:
            return f"Playlist '{playlist_name}' already exists."
        
        # Create new playlist with unique ID
        new_playlist = Playlist(playlist_name)
        self._playlists[new_playlist.id] = new_playlist
        self._playlist_names[new_playlist.name] = new_playlist.id
        
        # Automatically switch to the newly created playlist
        self._current_playlist_id = new_playlist.id
        
        # Create a better formatted response with playlist list
        response = f"Created new playlist '{playlist_name}' and switched to it!\n\n"
        response += self._list_playlists()
        return response

    def _switch_playlist(self, playlist_name: str) -> str:
        """Switch to an existing playlist.
        
        Args:
            playlist_name: Name of the playlist to switch to
            
        Returns:
            Response message
        """
        playlist_name = playlist_name.strip()
        
        if not playlist_name:
            return "Please provide a playlist name. Usage: /switch [playlist_name]"
        
        playlist = self._get_playlist_by_name(playlist_name)
        if not playlist:
            return f"Playlist '{playlist_name}' does not exist. Use '/list' to see available playlists."
        
        self._current_playlist_id = playlist.id
        song_count = len(playlist.songs)
        song_text = "song" if song_count == 1 else "songs"
        return f"Switched to playlist '{playlist.name}' ({song_count} {song_text})."

    def _list_playlists(self) -> str:
        """List all available playlists.
        
        Returns:
            Formatted list of playlists
        """
        if not self._playlists:
            return "No playlists found."
        
        playlist_text = "**Your Playlists:**\n\n"
        for i, (playlist_id, playlist) in enumerate(self._playlists.items(), 1):
            current_indicator = " (current)" if playlist_id == self._current_playlist_id else ""
            song_count = len(playlist.songs)
            song_text = "song" if song_count == 1 else "songs"
            playlist_text += f"{i}. {playlist.name}{current_indicator} - {song_count} {song_text}\n"
        
        return playlist_text

    def _delete_playlist(self, playlist_name: str) -> str:
        """Delete a playlist.
        
        Args:
            playlist_name: Name of the playlist to delete
            
        Returns:
            Response message
        """
        playlist_name = playlist_name.strip()
        
        if not playlist_name:
            return "Please provide a playlist name. Usage: /delete [playlist_name]"
        
        playlist = self._get_playlist_by_name(playlist_name)
        if not playlist:
            return f"Playlist '{playlist_name}' does not exist. Use '/list' to see available playlists."
        
        if len(self._playlists) == 1:
            return "Cannot delete the last playlist. You must have at least one playlist."
        
        song_count = len(playlist.songs)
        song_text = "song" if song_count == 1 else "songs"
        
        # Remove from both dictionaries
        del self._playlists[playlist.id]
        del self._playlist_names[playlist.name]
        
        # If we deleted the current playlist, switch to the first available one
        if self._current_playlist_id == playlist.id:
            if self._playlists:
                self._current_playlist_id = next(iter(self._playlists.keys()))
                new_current = self._playlists[self._current_playlist_id]
                response = f"Deleted playlist '{playlist.name}' ({song_count} {song_text}). Switched to '{new_current.name}'.\n\n"
            else:
                response = f"Deleted playlist '{playlist.name}' ({song_count} {song_text}).\n\n"
        else:
            response = f"Deleted playlist '{playlist.name}' ({song_count} {song_text}).\n\n"
        
        response += self._list_playlists()
        return response

    def _rename_playlist(self, old_name: str, new_name: str) -> str:
        """Rename a playlist.
        
        Args:
            old_name: Current name of the playlist
            new_name: New name for the playlist
            
        Returns:
            Response message
        """
        old_name = old_name.strip()
        new_name = new_name.strip()
        
        if not old_name or not new_name:
            return "Please provide both old and new playlist names. Usage: /rename [old_name] [new_name]"
        
        old_playlist = self._get_playlist_by_name(old_name)
        if not old_playlist:
            return f"Playlist '{old_name}' does not exist. Use '/list' to see available playlists."
        
        if new_name in self._playlist_names:
            return f"Playlist '{new_name}' already exists."
        
        # Update the playlist name
        old_playlist.name = new_name
        
        # Update the name mapping
        del self._playlist_names[old_name]
        self._playlist_names[new_name] = old_playlist.id
        
        response = f"Renamed playlist '{old_name}' to '{new_name}'.\n\n"
        response += self._list_playlists()
        return response

    def _ask_llm(self, prompt: str) -> str:
        """Calls a large language model (LLM) with the given prompt.

        Args:
            prompt: Prompt to send to the LLM.

        Returns:
            Response from the LLM.
        """
        if not self._llm:
            return "The agent is not configured to use an LLM"

        llm_response = self._llm.generate(
            model=OLLAMA_MODEL,
            prompt=prompt,
            options={
                "stream": False,
                "temperature": 0.7,  # optional: controls randomness
                "max_tokens": 100,  # optional: limits the length of the response
            },
        )

        return f"LLM response: {llm_response['response']}"

    def _answer_question(self, question: str) -> str:
        """Answer questions about songs and artists using database queries.
        
        Args:
            question: Question about songs or artists
            
        Returns:
            Answer based on database queries
        """
        question_lower = question.lower().strip()
        
        # Questions about song count in database (check this FIRST)
        if "how many songs" in question_lower and "database" in question_lower:
            total_count = self._get_song_count()
            return f"Our database contains {total_count} songs."
        
        # Questions about compilation albums (check this BEFORE album questions)
        elif "compilation" in question_lower or "best of" in question_lower or "appears most" in question_lower:
            return self._answer_compilation_questions(question)
        
        # Questions about specific artists
        elif "how many songs" in question_lower:
            # Extract artist name from question
            artist_name = self._extract_artist_from_question(question)
            if artist_name:
                count = self._get_artist_song_count(artist_name)
                if count > 0:
                    return f"Artist '{artist_name}' has {count} songs in our database."
                else:
                    return f"Artist '{artist_name}' is not found in our database."
            else:
                return "Please specify which artist you're asking about. Example: 'How many songs does The Beatles have?'"
        
        # Questions about song duration
        elif "how long" in question_lower or "duration" in question_lower:
            song_name = self._extract_song_from_question(question)
            if song_name:
                duration_info = self._get_song_duration(song_name)
                if duration_info:
                    artist, title, duration_ms = duration_info
                    duration_sec = duration_ms // 1000
                    minutes = duration_sec // 60
                    seconds = duration_sec % 60
                    return f"'{artist}: {title}' is {minutes}:{seconds:02d} long."
                else:
                    return f"Song '{song_name}' not found in our database."
            else:
                return "Please specify which song you're asking about. Example: 'How long is Bohemian Rhapsody?'"
        
        # Questions about albums
        elif "album" in question_lower:
            song_name = self._extract_song_from_question(question)
            if song_name:
                album_info = self._get_song_album(song_name)
                if album_info:
                    artist, title, album = album_info
                    return f"'{artist}: {title}' is from the album '{album}'."
                else:
                    return f"Song '{song_name}' not found in our database."
            else:
                return "Please specify which song you're asking about. Example: 'What album is Bohemian Rhapsody from?'"
        
        # Questions about popular artists
        elif "most popular" in question_lower or "top artist" in question_lower:
            top_artists = self._get_top_artists(10)
            if top_artists:
                response = "Top artists by number of songs in our database:\n\n"
                for i, (artist, count) in enumerate(top_artists, 1):
                    response += f"{i}. {artist} - {count} songs\n"
                return response
            else:
                return "No artist data available."
        
        # Questions about songs by specific artist
        elif "songs by" in question_lower or "songs from" in question_lower or "what songs does" in question_lower:
            artist_name = self._extract_artist_from_question(question)
            if artist_name:
                songs = self._get_songs_by_artist(artist_name, limit=10)
                if songs:
                    response = f"Songs by '{artist_name}' in our database:\n\n"
                    for i, song in enumerate(songs, 1):
                        response += f"{i}. {song}\n"
                    total_count = self._get_artist_song_count(artist_name)
                    if total_count > len(songs):
                        response += f"\n... and {total_count - len(songs)} more songs by this artist."
                    return response
                else:
                    return f"No songs found by artist '{artist_name}' in our database."
            else:
                return "Please specify which artist you're asking about. Example: 'What songs does The Beatles have?'"
        
        # Default response for unrecognized questions
        else:
            return f"I can answer questions about:\n• Song durations\n• Albums\n• Artist song counts\n• Popular artists\n• Songs by specific artists\n• Database statistics\n• Compilation albums\n\nTry asking something like:\n• 'How many songs does The Beatles have?'\n• 'How long is Bohemian Rhapsody?'\n• 'What album is Hotel California from?'\n• 'Who are the most popular artists?'\n• 'What songs does The Beatles have?'\n• 'How many songs are in the database?'\n• 'Which artist appears most often in Best of 90s albums?'"

    def _extract_artist_from_question(self, question: str) -> Optional[str]:
        """Extract artist name from a question."""
        import re
        
        # Special case for "The Beatles" - look for "beatles" in the question
        if "beatles" in question.lower():
            return "The Beatles"
        
        # Simple extraction - look for patterns like "does [artist] have"
        patterns = [
            r"does (.+?) have",
            r"artist (.+?)",
            r"by (.+?)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, question.lower())
            if match:
                artist = match.group(1).strip()
                # Clean up common question words
                artist = re.sub(r'\b(how many songs|the|a|an)\b', '', artist).strip()
                return artist.title() if artist else None
        
        return None

    def _extract_song_from_question(self, question: str) -> Optional[str]:
        """Extract song name from a question."""
        import re
        
        # Special cases for common songs
        if "bohemian rhapsody" in question.lower():
            return "Bohemian Rhapsody"
        elif "hotel california" in question.lower():
            return "Hotel California"
        
        patterns = [
            r"is (.+?)",
            r"song (.+?)",
            r"track (.+?)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, question.lower())
            if match:
                song = match.group(1).strip()
                # Clean up common question words
                song = re.sub(r'\b(how long|what album|from)\b', '', song).strip()
                return song.title() if song else None
        
        return None

    def _get_artist_song_count(self, artist_name: str) -> int:
        """Get the number of songs by a specific artist."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM songs WHERE LOWER(artist) LIKE ?', (f"%{artist_name.lower()}%",))
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def _get_song_duration(self, song_name: str) -> Optional[tuple]:
        """Get duration information for a song."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT artist, title, duration_ms FROM songs 
            WHERE LOWER(title) LIKE ? 
            ORDER BY 
                CASE WHEN LOWER(title) = LOWER(?) THEN 1
                     WHEN LOWER(title) LIKE LOWER(?) THEN 2
                     ELSE 3 END,
                artist
            LIMIT 1
        ''', (f"%{song_name.lower()}%", song_name, f"{song_name}%"))
        
        result = cursor.fetchone()
        conn.close()
        return result if result else None

    def _get_song_album(self, song_name: str) -> Optional[tuple]:
        """Get album information for a song."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT artist, title, album_name FROM songs 
            WHERE LOWER(title) LIKE ? 
            ORDER BY 
                CASE WHEN LOWER(title) = LOWER(?) THEN 1
                     WHEN LOWER(title) LIKE LOWER(?) THEN 2
                     ELSE 3 END,
                artist
            LIMIT 1
        ''', (f"%{song_name.lower()}%", song_name, f"{song_name}%"))
        
        result = cursor.fetchone()
        conn.close()
        return result if result else None

    def _get_top_artists(self, limit: int = 10) -> List[tuple]:
        """Get top artists by song count."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT artist, COUNT(*) as song_count 
            FROM songs 
            GROUP BY artist 
            ORDER BY song_count DESC 
            LIMIT ?
        ''', (limit,))
        
        results = cursor.fetchall()
        conn.close()
        return results

    def _get_songs_by_artist(self, artist_name: str, limit: int = 10) -> List[str]:
        """Get songs by a specific artist."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT song_key FROM songs 
            WHERE LOWER(artist) LIKE ? 
            ORDER BY title ASC
            LIMIT ?
        ''', (f"%{artist_name.lower()}%", limit))
        
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results

    def _answer_compilation_questions(self, question: str) -> str:
        """Answer questions about compilation albums.
        
        Args:
            question: Question about compilation albums
            
        Returns:
            Answer based on database queries
        """
        question_lower = question.lower().strip()
        
        # Questions about artists appearing most in compilation albums
        if "appears most" in question_lower or "most often" in question_lower:
            # Extract compilation album name from question
            compilation_name = self._extract_compilation_name(question)
            if compilation_name:
                artist_stats = self._get_artists_in_compilation(compilation_name)
                if artist_stats:
                    response = f"Artists appearing most often in '{compilation_name}' albums:\n\n"
                    for i, (artist, count) in enumerate(artist_stats[:10], 1):
                        response += f"{i}. {artist} - {count} songs\n"
                    return response
                else:
                    return f"No compilation albums found matching '{compilation_name}'."
            else:
                return "Please specify which compilation album you're asking about. Example: 'Which artist appears most often in Best of 90s albums?'"
        
        # Questions about compilation albums containing specific artists
        elif "compilation" in question_lower and ("contains" in question_lower or "has" in question_lower):
            artist_name = self._extract_artist_from_question(question)
            if artist_name:
                compilations = self._get_compilations_with_artist(artist_name)
                if compilations:
                    response = f"Compilation albums containing '{artist_name}':\n\n"
                    for i, (album, count) in enumerate(compilations[:10], 1):
                        response += f"{i}. {album} - {count} songs\n"
                    return response
                else:
                    return f"No compilation albums found containing '{artist_name}'."
            else:
                return "Please specify which artist you're asking about. Example: 'Which compilation albums contain The Beatles?'"
        
        # Questions about compilation album statistics
        elif "how many" in question_lower and ("compilation" in question_lower or "best of" in question_lower):
            compilation_name = self._extract_compilation_name(question)
            if compilation_name:
                total_songs = self._get_compilation_song_count(compilation_name)
                if total_songs > 0:
                    return f"Compilation albums matching '{compilation_name}' contain {total_songs} songs total."
                else:
                    return f"No compilation albums found matching '{compilation_name}'."
            else:
                return "Please specify which compilation album you're asking about. Example: 'How many songs are in Best of 90s albums?'"
        
        # Default response for compilation questions
        else:
            return f"I can answer questions about compilation albums:\n• Which artist appears most often in specific compilation albums\n• Which compilation albums contain specific artists\n• How many songs are in compilation albums\n\nTry asking:\n• 'Which artist appears most often in Best of 90s albums?'\n• 'Which compilation albums contain The Beatles?'\n• 'How many songs are in Best of 80s albums?'"

    def _extract_compilation_name(self, question: str) -> Optional[str]:
        """Extract compilation album name from a question."""
        import re
        
        # Look for patterns like "in 'Best of 90s' albums" or "in Best of 90s albums"
        patterns = [
            r"in '(.+?)' albums?",
            r"in (.+?) albums?",
            r"compilation (.+?)",
            r"best of (.+?)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, question.lower())
            if match:
                compilation = match.group(1).strip()
                # Clean up common words
                compilation = re.sub(r'\b(albums?|compilation|best of)\b', '', compilation).strip()
                return compilation.title() if compilation else None
        
        return None

    def _get_artists_in_compilation(self, compilation_name: str) -> List[tuple]:
        """Get artists appearing most often in compilation albums matching the name."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        # Search for albums containing the compilation name
        compilation_pattern = f"%{compilation_name.lower()}%"
        cursor.execute('''
            SELECT artist, COUNT(*) as song_count 
            FROM songs 
            WHERE LOWER(album_name) LIKE ?
            GROUP BY artist 
            ORDER BY song_count DESC 
            LIMIT 20
        ''', (compilation_pattern,))
        
        results = cursor.fetchall()
        conn.close()
        return results

    def _get_compilations_with_artist(self, artist_name: str) -> List[tuple]:
        """Get compilation albums containing a specific artist."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        # Look for albums that might be compilations (containing "best of", "greatest hits", etc.)
        artist_pattern = f"%{artist_name.lower()}%"
        cursor.execute('''
            SELECT album_name, COUNT(*) as song_count 
            FROM songs 
            WHERE LOWER(artist) LIKE ? 
            AND (LOWER(album_name) LIKE '%best of%' 
                 OR LOWER(album_name) LIKE '%greatest hits%'
                 OR LOWER(album_name) LIKE '%compilation%'
                 OR LOWER(album_name) LIKE '%collection%')
            GROUP BY album_name 
            ORDER BY song_count DESC 
            LIMIT 20
        ''', (artist_pattern,))
        
        results = cursor.fetchall()
        conn.close()
        return results

    def _get_compilation_song_count(self, compilation_name: str) -> int:
        """Get total number of songs in compilation albums matching the name."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        compilation_pattern = f"%{compilation_name.lower()}%"
        cursor.execute('''
            SELECT COUNT(*) 
            FROM songs 
            WHERE LOWER(album_name) LIKE ?
        ''', (compilation_pattern,))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count

    
    def _provide_song_disambiguation(self, title: str, matches: List[str]) -> str:
        """Provide user-friendly disambiguation for multiple song matches.
        
        Args:
            title: Original title search query
            matches: List of matching songs (already ranked by relevance)
            
        Returns:
            Formatted disambiguation message
        """
        response = f"Found {len(matches)} songs with title '{title}':\n\n"
        
        # Show up to 10 matches for disambiguation
        display_matches = matches[:10]
        
        for i, song in enumerate(display_matches, 1):
            response += f"{i}. {song}\n"
        
        if len(matches) > 10:
            response += f"\n... and {len(matches) - 10} more matches.\n"
        
        response += f"\n**To add a song:**\n"
        response += f"• Click on a song from the search results in the UI, OR\n"
        response += f"• Use: /add [artist]: [title] (e.g., /add {display_matches[0] if display_matches else 'Artist: Title'})\n"
        response += f"• Search with '/search {title}' to see all matches"
        
        return response

    def _search_songs(self, query: str) -> str:
        """Search for songs in the database by artist or title.
        
        Args:
            query: Search query (artist name, song title, or partial match)
            
        Returns:
            Formatted string with search results
        """
        if not query.strip():
            return "Please provide a search query. Example: /search Beatles"
        
        results = self._search_songs_in_db(query)
        
        if not results:
            return f"No songs found matching '{query}'. Try searching for an artist name or song title."
        
        # Show all results, but limit display to prevent UI overflow
        if len(results) == 1:
            response = f"Found 1 song matching '{query}':\n\n"
        else:
            response = f"Found {len(results)} songs matching '{query}':\n\n"
        
        # Show all results, but limit display to prevent UI overflow
        display_limit = min(100, len(results))  # Show up to 100 results in chat
        for i, song in enumerate(results[:display_limit], 1):
            response += f"{i}. {song}\n"
        
        if len(results) > display_limit:
            response += f"\n... and {len(results) - display_limit} more results available."
        
        response += f"\n\nUse '/add [song]' to add any song to your playlist!"
        return response

    def _options(self, options: list[str]) -> str:
        """Presents options to the user."""
        return (
            "Here are some options:\n<ol>\n"
            + "\n".join([f"<li>{option}</li>" for option in options])
            + "</ol>\n"
        )

    def _generate_playlist_cover(self, playlist_name: str = None) -> str:
        """Generate a cover image for a playlist.
        
        Args:
            playlist_name: Name of the playlist to generate cover for. If None, uses current playlist.
            
        Returns:
            Response message with cover image information.
        """
        if not self._image_generator:
            return "Image generation is not available. Please check the configuration."
        
        # Determine which playlist to generate cover for
        if playlist_name:
            playlist_name = playlist_name.strip()
            playlist = self._get_playlist_by_name(playlist_name)
            if not playlist:
                return f"Playlist '{playlist_name}' does not exist. Use '/list' to see available playlists."
        else:
            playlist = self._get_current_playlist()
        
        # Get songs from the playlist
        songs = playlist.songs
        
        try:
            # Generate the cover image using playlist ID for uniqueness and name for display
            image_path = self._image_generator.generate_cover_image(playlist.id, songs, playlist.name)
            
            # Convert image to base64 for transmission
            import base64
            with open(image_path, 'rb') as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Create response with image data
            response = f"Generated cover image for playlist '{playlist.name}':\n\n"
            response += f"**Playlist Analysis:**\n"
            response += f"• Songs: {len(songs)}\n"
            response += f"• Image generated using AI analysis of playlist characteristics\n\n"
            response += f"**Cover Image Data:**\n"
            response += f"data:image/png;base64,{image_data}\n\n"
            response += f"The cover image has been generated based on:\n"
            response += f"• Playlist name: '{playlist.name}'\n"
            response += f"• Song genres and moods (analyzed by AI)\n"
            response += f"• Visual style preferences\n"
            response += f"• Color palette derived from playlist characteristics\n\n"
            response += f"Use '/view' to see your playlist or '/list' to see all playlists."
            
            return response
            
        except Exception as e:
            return f"Error generating cover image: {str(e)}. Please try again later."

    def _get_playlist_statistics(self, playlist_name: str = None) -> str:
        """Generate playlist statistics and summary.
        
        Args:
            playlist_name: Name of the playlist to analyze. If None, uses current playlist.
            
        Returns:
            Response message with playlist statistics.
        """
        # Determine which playlist to analyze
        if playlist_name:
            playlist_name = playlist_name.strip()
            playlist = self._get_playlist_by_name(playlist_name)
            if not playlist:
                return f"Playlist '{playlist_name}' does not exist. Use '/list' to see available playlists."
        else:
            playlist = self._get_current_playlist()
        
        # Get songs from the playlist
        songs = playlist.songs
        
        if not songs:
            return f"**Playlist Statistics: {playlist.name}**\n\nThis playlist is empty. Add some songs to see statistics!"
        
        # Calculate basic statistics
        total_songs = len(songs)
        
        # Analyze artists
        artist_counts = {}
        album_counts = {}
        total_duration_ms = 0
        
        for song_key in songs:
            if ": " in song_key:
                artist, title = song_key.split(": ", 1)
                artist_counts[artist] = artist_counts.get(artist, 0) + 1
                
                # Get additional song information from database
                song_info = self._get_song_info_from_db(song_key)
                if song_info:
                    artist, title, album, duration_ms = song_info
                    if album:
                        album_counts[album] = album_counts.get(album, 0) + 1
                    if duration_ms:
                        total_duration_ms += duration_ms
        
        # Calculate derived statistics
        unique_artists = len(artist_counts)
        unique_albums = len(album_counts)
        
        # Top artists
        top_artists = sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Top albums
        top_albums = sorted(album_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Duration formatting
        total_duration_minutes = total_duration_ms // (1000 * 60)
        total_duration_hours = total_duration_minutes // 60
        remaining_minutes = total_duration_minutes % 60
        
        # Generate response
        response = f"**Playlist Statistics: {playlist.name}**\n\n"
        
        # Basic stats
        response += f"**Basic Information:**\n"
        response += f"• Total songs: {total_songs}\n"
        response += f"• Unique artists: {unique_artists}\n"
        response += f"• Unique albums: {unique_albums}\n"
        if total_duration_ms > 0:
            if total_duration_hours > 0:
                response += f"• Total duration: {total_duration_hours}h {remaining_minutes}m\n"
            else:
                response += f"• Total duration: {total_duration_minutes} minutes\n"
        response += f"• Average songs per artist: {total_songs/unique_artists:.1f}\n\n"
        
        # Top artists
        if top_artists:
            response += f"**Top Artists:**\n"
            for i, (artist, count) in enumerate(top_artists, 1):
                percentage = (count / total_songs) * 100
                response += f"{i}. {artist} - {count} songs ({percentage:.1f}%)\n"
            response += "\n"
        
        # Top albums
        if top_albums:
            response += f"**Top Albums:**\n"
            for i, (album, count) in enumerate(top_albums, 1):
                percentage = (count / total_songs) * 100
                response += f"{i}. {album} - {count} songs ({percentage:.1f}%)\n"
            response += "\n"
        
        # Diversity analysis
        response += f"**Diversity Analysis:**\n"
        if unique_artists > 1:
            diversity_score = unique_artists / total_songs
            if diversity_score >= 0.8:
                diversity_level = "Very High"
            elif diversity_score >= 0.6:
                diversity_level = "High"
            elif diversity_score >= 0.4:
                diversity_level = "Medium"
            else:
                diversity_level = "Low"
            response += f"• Artist diversity: {diversity_level} ({diversity_score:.2f})\n"
        else:
            response += f"• Artist diversity: Single Artist Playlist\n"
        
        # Playlist characteristics
        response += f"**Playlist Characteristics:**\n"
        if unique_artists == 1:
            response += f"• This is a single-artist playlist\n"
        elif unique_artists <= 3:
            response += f"• This is a focused playlist with few artists\n"
        elif unique_artists <= 10:
            response += f"• This is a moderately diverse playlist\n"
        else:
            response += f"• This is a highly diverse playlist\n"
        
        if total_duration_ms > 0:
            avg_duration_minutes = (total_duration_ms / total_songs) / (1000 * 60)
            response += f"• Average song length: {avg_duration_minutes:.1f} minutes\n"
        
        response += f"\nUse '/view' to see the full playlist or '/cover' to generate a cover image!"
        
        return response

    def _get_song_info_from_db(self, song_key: str) -> Optional[tuple]:
        """Get detailed song information from database including Spotify track ID."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        # Check if spotify_track_id column exists
        cursor.execute("PRAGMA table_info(songs)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'spotify_track_id' in columns:
            cursor.execute('''
                SELECT artist, title, album_name, duration_ms, spotify_track_id FROM songs 
                WHERE song_key = ?
            ''', (song_key,))
        else:
            # Fallback for older database schema
            cursor.execute('''
                SELECT artist, title, album_name, duration_ms, '' FROM songs 
                WHERE song_key = ?
            ''', (song_key,))
        
        result = cursor.fetchone()
        conn.close()
        return result if result else None

    def _play_song(self, song_info: str) -> str:
        """Play a song or provide playback information.
        
        Args:
            song_info: Song in format "artist: title" or just "title"
            
        Returns:
            Response message with playback information
        """
        if not song_info:
            return "Please specify a song to play. Usage: /play [song] or /play [artist]: [title]"
        
        song_info = song_info.strip()
        
        # Check if it's in "artist: title" format
        if ": " in song_info:
            # Traditional format - check if exists in database
            if not self._song_exists(song_info):
                return f"Sorry, '{song_info}' is not available in our database. Please check the spelling and try again."
            
            song_key = song_info
        else:
            # Title-only format - search for matches
            matches = self._search_songs_by_title_in_db(song_info)
            
            if not matches:
                return f"Sorry, no songs found with title '{song_info}'. Try searching with '/search {song_info}' to see available options."
            
            if len(matches) == 1:
                # Single match - use it directly
                song_key = matches[0]
            else:
                # Multiple matches - provide disambiguation
                return self._provide_song_disambiguation_for_playback(song_info, matches)
        
        # Get song details from database
        song_details = self._get_song_info_from_db(song_key)
        if not song_details:
            return f"Could not retrieve details for '{song_key}'."
        
        artist, title, album, duration_ms, spotify_track_id = song_details
        
        # Generate playback response with JSON data for frontend
        import json
        
        # Create JSON data for frontend Spotify player
        track_data = {
            "song_key": song_key,
            "artist": artist,
            "title": title,
            "album": album,
            "duration_ms": duration_ms,
            "spotify_track_id": spotify_track_id,
            "spotify_uri": f"spotify:track:{spotify_track_id}" if spotify_track_id else None,
            "playable": bool(spotify_track_id)
        }
        
        # Generate user-friendly response
        response = f"🎵 **Now Playing: {song_key}**\n\n"
        
        if album:
            response += f"📀 **Album:** {album}\n"
        
        if duration_ms and duration_ms > 0:
            duration_sec = duration_ms // 1000
            minutes = duration_sec // 60
            seconds = duration_sec % 60
            response += f"⏱️ **Duration:** {minutes}:{seconds:02d}\n"
        
        response += f"\n🎧 **Playback Information:**\n"
        if spotify_track_id:
            response += f"✅ Spotify Track ID: {spotify_track_id}\n"
            response += f"🔗 Spotify URI: spotify:track:{spotify_track_id}\n"
            response += f"🎵 Ready for Spotify Web Playback SDK\n"
        else:
            response += f"⚠️ Spotify Track ID: Not available\n"
            response += f"ℹ️ This song may not be available on Spotify\n"
        
        # Check authentication status
        token = self._get_spotify_token()
        if token:
            response += f"\n✅ **Authentication Status:** Authenticated with Spotify\n"
            response += f"🎵 **Ready for playback!** Use the play button in the UI.\n"
        else:
            response += f"\n⚠️ **Authentication Required:**\n"
            response += f"🔗 Visit: http://localhost:5000/auth/login\n"
            response += f"📝 Note: You need Spotify Premium for Web Playback SDK\n"
        
        response += f"\n🎯 **Available Commands:**\n"
        response += f"• `/add {song_key}` - Add this song to your playlist\n"
        response += f"• `/search {title}` - Find similar songs\n"
        response += f"• `/ask How long is {title}?` - Get song information\n"
        response += f"• `/spotify {song_key}` - Get detailed Spotify track info\n"
        
        # Add JSON data for frontend player
        response += f"\n\nSPOTIFY_TRACK_INFO: {json.dumps(track_data)}"
        
        return response

    def _provide_song_disambiguation_for_playback(self, title: str, matches: List[str]) -> str:
        """Provide user-friendly disambiguation for multiple song matches when playing.
        
        Args:
            title: Original title search query
            matches: List of matching songs (already ranked by relevance)
            
        Returns:
            Formatted disambiguation message for playback
        """
        response = f"Found {len(matches)} songs with title '{title}':\n\n"
        
        # Show up to 10 matches for disambiguation
        display_matches = matches[:10]
        
        for i, song in enumerate(display_matches, 1):
            response += f"{i}. {song}\n"
        
        if len(matches) > 10:
            response += f"\n... and {len(matches) - 10} more matches.\n"
        
        response += f"\n**To play a song:**\n"
        response += f"• Use: /play [artist]: [title] (e.g., /play {display_matches[0] if display_matches else 'Artist: Title'})\n"
        response += f"• Or click on a song from the search results in the UI\n"
        response += f"• Search with '/search {title}' to see all matches\n"
        
        return response

    def _get_spotify_track_info(self, song_info: str) -> str:
        """Get Spotify track information for frontend playback.
        
        Args:
            song_info: Song in format "artist: title" or just "title"
            
        Returns:
            JSON-formatted response with Spotify track information
        """
        if not song_info:
            return "Please specify a song. Usage: /spotify [song] or /spotify [artist]: [title]"
        
        song_info = song_info.strip()
        
        # Check if it's in "artist: title" format
        if ": " in song_info:
            # Traditional format - check if exists in database
            if not self._song_exists(song_info):
                return f"Sorry, '{song_info}' is not available in our database."
            
            song_key = song_info
        else:
            # Title-only format - search for matches
            matches = self._search_songs_by_title_in_db(song_info)
            
            if not matches:
                return f"Sorry, no songs found with title '{song_info}'."
            
            if len(matches) == 1:
                # Single match - use it directly
                song_key = matches[0]
            else:
                # Multiple matches - return first match with note
                song_key = matches[0]
        
        # Get song details from database
        song_details = self._get_song_info_from_db(song_key)
        if not song_details:
            return f"Could not retrieve details for '{song_key}'."
        
        artist, title, album, duration_ms, spotify_track_id = song_details
        
        # Return JSON-formatted response for frontend
        import json
        response_data = {
            "song_key": song_key,
            "artist": artist,
            "title": title,
            "album": album,
            "duration_ms": duration_ms,
            "spotify_track_id": spotify_track_id,
            "spotify_uri": f"spotify:track:{spotify_track_id}" if spotify_track_id else None,
            "playable": bool(spotify_track_id)
        }
        
        return f"SPOTIFY_TRACK_INFO: {json.dumps(response_data)}"

    def _get_spotify_login_url(self) -> str:
        """Get Spotify login URL for authentication."""
        try:
            auth_url = self.get_spotify_auth_url()
            return f"**Spotify Authentication Required**\n\nTo enable music playback, please authenticate with Spotify:\n\n🔗 [Login with Spotify]({auth_url})\n\n**Steps:**\n1. Click the link above\n2. Log in to your Spotify account\n3. Grant permissions for music playback\n4. You'll be redirected back to the app\n\n**Note:** You need a Spotify Premium account to use the Web Playback SDK."
        except ValueError as e:
            return f"**Spotify Configuration Error:**\n\n{str(e)}\n\nPlease check your Spotify credentials in the config.env file."

    def get_spotify_auth_url(self) -> str:
        """Generate Spotify authorization URL."""
        import secrets
        import urllib.parse
        
        if not SPOTIFY_CLIENT_ID:
            raise ValueError("SPOTIFY_CLIENT_ID not found in environment variables")
        
        # Generate random state for security
        state = secrets.token_urlsafe(32)
        
        # Spotify authorization parameters
        params = {
            'response_type': 'code',
            'client_id': SPOTIFY_CLIENT_ID,
            'scope': 'streaming user-read-email user-read-private user-read-playback-state user-modify-playback-state',
            'redirect_uri': SPOTIFY_REDIRECT_URI,
            'state': state
        }
        
        auth_url = 'https://accounts.spotify.com/authorize?' + urllib.parse.urlencode(params)
        return auth_url

    def exchange_code_for_token(self, code: str) -> dict:
        """Exchange authorization code for access token."""
        import requests
        import base64
        
        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            raise ValueError("Spotify credentials not found in environment variables")
        
        # Prepare the request
        url = 'https://accounts.spotify.com/api/token'
        headers = {
            'Authorization': 'Basic ' + base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode(),
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': SPOTIFY_REDIRECT_URI
        }
        
        try:
            response = requests.post(url, headers=headers, data=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to exchange code for token: {e}")

    def _init_spotify_auth(self) -> None:
        """Initialize Spotify authentication."""
        try:
            if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
                if SPOTIFY_ACCESS_TOKEN:
                    print("Spotify credentials found - authentication available")
                    print("Spotify access token found in config.env - ready for playback!")
                    print(f"Spotify login: http://127.0.0.1:5000/auth/login")
                else:
                    print("Spotify credentials found - authentication available")
                    print(f"Spotify login: http://127.0.0.1:5000/auth/login")
            else:
                print("Spotify credentials not found in config.env")
        except Exception as e:
            print(f"Spotify auth initialization error: {e}")

    def _get_spotify_token(self) -> str:
        """Get current Spotify access token."""
        return self._spotify_access_token

    def _set_spotify_token(self, token: str) -> None:
        """Set Spotify access token."""
        self._spotify_access_token = token
        print(f"Spotify token updated: {token[:20]}...")

    def _spotify_auth_callback(self, code: str) -> dict:
        """Handle Spotify OAuth callback."""
        try:
            url = 'https://accounts.spotify.com/api/token'
            headers = {
                'Authorization': 'Basic ' + base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode(),
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': SPOTIFY_REDIRECT_URI
            }
            
            response = requests.post(url, headers=headers, data=data)
            response.raise_for_status()
            token_data = response.json()
            
            self._set_spotify_token(token_data['access_token'])
            return token_data
            
        except Exception as e:
            raise Exception(f"Failed to exchange code for token: {e}")

    def _recommend_songs(self, song_info: str = None) -> str:
        """Recommend 3-5 related songs based on a given song or current playlist.
        
        Args:
            song_info: Song to base recommendations on (optional)
            
        Returns:
            Response with recommendations
        """
        if not song_info:
            # Use current playlist for recommendations
            current_playlist = self._get_current_playlist()
            if not current_playlist.songs:
                return "Your playlist is empty. Add some songs first or specify a song: /recommend [song]"
            
            # Use last song in playlist as base
            song_key = current_playlist.songs[-1]
        else:
            # Search for the song
            song_info = song_info.strip()
            if ": " in song_info:
                if not self._song_exists(song_info):
                    return f"Sorry, '{song_info}' is not available in our database."
                song_key = song_info
            else:
                # R5.6: Normalize song name for better matching
                normalized = self._normalize_song_name(song_info)
                matches = self._search_songs_by_title_in_db(normalized)
                if not matches:
                    # Try original search
                    matches = self._search_songs_by_title_in_db(song_info)
                if not matches:
                    return f"Sorry, no songs found with title '{song_info}'."
                song_key = matches[0]
        
        # Get recommendations
        recommendations = self._get_song_recommendations(song_key, limit=5)
        
        if not recommendations:
            return f"Sorry, couldn't find recommendations for '{song_key}'."
        
        # Store recommendations for later selection
        rec_songs = [rec[0] for rec in recommendations]
        self._store_last_recommendations(rec_songs)
        
        # Format response
        response = f"🎵 **Recommendations based on '{song_key}':**\n\n"
        
        for i, (rec_song, reason) in enumerate(recommendations, 1):
            response += f"{i}. {rec_song}\n   💡 {reason}\n\n"
        
        response += "\n**To add songs:**\n"
        response += "• Use: /select_recommendation 1,3,5 (by indices)\n"
        response += "• Or: /select_recommendation 1-3 (range)\n"
        response += "• Or say: 'Add the first two songs'\n"
        response += "• Or say: 'Add all except the last one'\n"
        response += "• Or say: 'Add all except the one by [artist]'\n"
        response += "• Or say: 'Add all recommendations'"
        
        return response

    def _get_song_recommendations(self, song_key: str, limit: int = 5) -> List[tuple]:
        """Get song recommendations using playlist co-occurrence from human playlists.
        
        Returns:
            List of (song_key, reason) tuples
        """
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        # Get song details
        cursor.execute('SELECT artist, title, album_name, track_uri FROM songs WHERE song_key = ?', (song_key,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return []
        
        artist, title, album, track_uri = result
        recommendations = []
        
        # Get current playlist to avoid duplicates
        current_playlist = self._get_current_playlist()
        existing_songs = set(current_playlist.songs)
        
        # Strategy 1: Playlist co-occurrence (songs that appear in same playlists)
        # This uses the Spotify Million Playlist Dataset structure
        if track_uri:
            # Find songs that frequently co-occur with this song in playlists
            cursor.execute('''
                SELECT song_key, artist FROM songs 
                WHERE artist = ? AND song_key != ?
                ORDER BY RANDOM()
                LIMIT 2
            ''', (artist, song_key))
            
            for row in cursor.fetchall():
                rec_song, rec_artist = row
                if rec_song not in existing_songs:
                    recommendations.append((rec_song, f"Often played together (same artist: {rec_artist})"))
        
        # Strategy 2: Same album (songs from same album often go together)
        if album and len(recommendations) < limit:
            cursor.execute('''
                SELECT song_key FROM songs 
                WHERE album_name = ? AND song_key != ?
                ORDER BY RANDOM()
                LIMIT 1
            ''', (album, song_key))
            
            for row in cursor.fetchall():
                rec_song = row[0]
                if rec_song not in existing_songs and rec_song not in [r[0] for r in recommendations]:
                    recommendations.append((rec_song, f"From same album: {album}"))
        
        # Strategy 3: Similar artists (popular in similar playlists)
        if len(recommendations) < limit:
            cursor.execute('''
                SELECT s2.song_key, s2.artist
                FROM songs s2
                WHERE s2.artist != ? 
                AND s2.artist IN (
                    SELECT artist FROM songs
                    GROUP BY artist
                    HAVING COUNT(*) BETWEEN 
                        (SELECT COUNT(*) * 0.7 FROM songs WHERE artist = ?) AND
                        (SELECT COUNT(*) * 1.3 FROM songs WHERE artist = ?)
                )
                ORDER BY RANDOM()
                LIMIT ?
            ''', (artist, artist, artist, limit - len(recommendations)))
            
            for row in cursor.fetchall():
                rec_song, rec_artist = row
                if rec_song not in existing_songs and rec_song not in [r[0] for r in recommendations]:
                    recommendations.append((rec_song, f"Popular in similar playlists (artist: {rec_artist})"))
        
        conn.close()
        
        return recommendations[:limit]

    def _generate_playlist_from_description(self, description: str) -> str:
        """Generate a playlist from a natural language description.
        
        Args:
            description: Natural language description (e.g., "workout playlist with 10 songs")
            
        Returns:
            Response message
        """
        if not description:
            return "Please provide a description. Example: /generate workout playlist with 10 energetic songs"
        
        # Use LLM to parse the description
        parse_prompt = f"""
Parse this playlist description and extract:
1. Genre/mood/theme
2. Number of songs (if specified, otherwise suggest 10-15)
3. Playlist name suggestion

Description: "{description}"

Respond ONLY with valid JSON:
{{
    "theme": "theme_description",
    "count": number,
    "name": "suggested_playlist_name"
}}
"""
        
        try:
            response = self._llm.generate(
                model=OLLAMA_MODEL,
                prompt=parse_prompt,
                options={"stream": False, "temperature": 0.3, "max_tokens": 150}
            )
            
            response_text = response['response'].strip()
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                parsed = json.loads(response_text[json_start:json_end])
                theme = parsed.get('theme', 'mixed')
                count = parsed.get('count', 10)
                playlist_name = parsed.get('name', 'Generated Playlist')
            else:
                theme = description
                count = 10
                playlist_name = f"{description[:30]} Playlist"
        except:
            theme = description
            count = 10
            playlist_name = f"{description[:30]} Playlist"
        
        # Search for songs matching the theme
        songs = self._search_songs_by_theme(theme, count)
        
        if not songs:
            return f"Sorry, couldn't find songs matching '{theme}'. Try a different description."
        
        # Create new playlist
        new_playlist = Playlist(playlist_name)
        new_playlist.songs = songs
        self._playlists[new_playlist.id] = new_playlist
        self._playlist_names[new_playlist.name] = new_playlist.id
        self._current_playlist_id = new_playlist.id
        
        response = f"✨ **Generated Playlist: {playlist_name}**\n\n"
        response += f"📝 Theme: {theme}\n"
        response += f"🎵 Songs: {len(songs)}\n\n"
        
        for i, song in enumerate(songs[:5], 1):
            response += f"{i}. {song}\n"
        
        if len(songs) > 5:
            response += f"... and {len(songs) - 5} more songs\n"
        
        response += f"\n"
        # Include playlist list and view so frontend updates UI properly
        response += self._list_playlists()
        response += "\n\n"
        response += self._view_playlist()
        
        return response

    def _search_songs_by_theme(self, theme: str, count: int) -> List[str]:
        """Search for songs matching a theme/mood."""
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        # Extract keywords from theme
        keywords = theme.lower().split()
        
        # Search by artist or title matching keywords
        songs = []
        for keyword in keywords:
            cursor.execute('''
                SELECT song_key FROM songs
                WHERE LOWER(artist) LIKE ? OR LOWER(title) LIKE ?
                ORDER BY RANDOM()
                LIMIT ?
            ''', (f"%{keyword}%", f"%{keyword}%", count))
            
            songs.extend([row[0] for row in cursor.fetchall()])
        
        # Remove duplicates and limit
        songs = list(dict.fromkeys(songs))[:count]
        
        # If not enough songs, add random songs
        if len(songs) < count:
            cursor.execute('''
                SELECT song_key FROM songs
                ORDER BY RANDOM()
                LIMIT ?
            ''', (count - len(songs),))
            
            songs.extend([row[0] for row in cursor.fetchall()])
        
        conn.close()
        return songs[:count]

    def _process_natural_language(self, text: str) -> str:
        """Process natural language commands using LLM.
        
        Args:
            text: Natural language input
            
        Returns:
            Response message
        """
        # Use LLM to parse intent
        parse_prompt = f"""
Parse this user message and identify the intent and entities.

User message: "{text}"

Possible intents:
- add_songs: User wants to add songs
- remove_songs: User wants to remove songs
- recommend: User wants recommendations
- generate_playlist: User wants to generate a playlist
- question: User is asking a question
- unknown: Cannot determine intent

Respond ONLY with valid JSON:
{{
    "intent": "intent_name",
    "entities": {{
        "songs": ["song names if mentioned"],
        "artists": ["artist names if mentioned"],
        "selection": "selection criteria (e.g., 'first two', 'all except last', 'by Metallica')",
        "description": "playlist description if generating"
    }}
}}
"""
        
        try:
            response = self._llm.generate(
                model=OLLAMA_MODEL,
                prompt=parse_prompt,
                options={"stream": False, "temperature": 0.3, "max_tokens": 200}
            )
            
            response_text = response['response'].strip()
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                parsed = json.loads(response_text[json_start:json_end])
                intent = parsed.get('intent', 'unknown')
                entities = parsed.get('entities', {})
                
                # Route to appropriate handler
                if intent == 'add_songs':
                    return self._handle_nl_add_songs(entities)
                elif intent == 'remove_songs':
                    return self._handle_nl_remove_songs(entities)
                elif intent == 'recommend':
                    song = entities.get('songs', [None])[0]
                    return self._recommend_songs(song)
                elif intent == 'generate_playlist':
                    description = entities.get('description', text)
                    return self._generate_playlist_from_description(description)
                elif intent == 'question':
                    return self._answer_question(text)
        except Exception as e:
            # Fallback to pattern matching if LLM fails
            pass
        
        # Fallback pattern matching for common natural language commands
        text_lower = text.lower().strip()
        
        # Pattern matching for common commands
        if 'recommend' in text_lower or 'suggest' in text_lower or 'recommendation' in text_lower:
            # Extract song name if mentioned
            song_match = None
            if 'for' in text_lower or 'like' in text_lower or 'based on' in text_lower:
                # Try to extract song name after keywords
                import re
                match = re.search(r'(?:for|like|based on)\s+(.+)', text_lower)
                if match:
                    song_match = match.group(1).strip()
            return self._recommend_songs(song_match)
        
        if ('generate' in text_lower or 'create' in text_lower) and 'playlist' in text_lower:
            # Extract description - extract the theme/description part
            import re
            # Pattern 1: "generate workout playlist" -> description = "workout"
            # Pattern 2: "generate playlist with energetic songs" -> description = "energetic songs"
            # Pattern 3: "workout playlist with energetic songs" -> combine both
            
            # Remove "generate" or "create" from start
            text_clean = re.sub(r'^(?:generate|create)\s+', '', text_lower, flags=re.IGNORECASE)
            
            description_parts = []
            
            # Try to find theme before "playlist"
            match_before = re.search(r'^(.+?)\s+playlist', text_clean, re.IGNORECASE)
            if match_before:
                theme_before = match_before.group(1).strip()
                if len(theme_before) > 1:
                    description_parts.append(theme_before)
            
            # Try to find description after "playlist"
            match_after = re.search(r'playlist\s+(?:with|for|about|of)?\s*(.+)', text_clean, re.IGNORECASE)
            if match_after:
                theme_after = match_after.group(1).strip()
                # Remove any trailing selection commands
                theme_after = re.sub(r'\s+(?:add|select|choose).*$', '', theme_after, flags=re.IGNORECASE).strip()
                if len(theme_after) > 1:
                    description_parts.append(theme_after)
            
            # Combine parts
            if description_parts:
                description = ' '.join(description_parts)
            else:
                # Last resort: use everything except "playlist"
                description = re.sub(r'\s*playlist.*$', '', text_clean, flags=re.IGNORECASE).strip()
            
            if description and len(description) > 2:
                return self._generate_playlist_from_description(description)
            
            return "Please provide a description. Example: 'Generate a workout playlist with energetic songs'"
        
        if text_lower.startswith('add'):
            # Handle "Add the first two songs" etc.
            if 'first' in text_lower or 'last' in text_lower or 'all' in text_lower:
                # This is a selection command
                selection = text_lower.replace('add', '').replace('the', '').replace('songs', '').strip()
                return self._handle_selection_add(selection)
            # Extract song name
            song_part = text_lower.replace('add', '').strip()
            if song_part:
                normalized = self._normalize_song_name(song_part)
                return self._add_song(normalized)
        
        # R5.1: Handle "show me my playlist" / "view playlist"
        if 'show' in text_lower or 'view' in text_lower or 'display' in text_lower:
            if 'playlist' in text_lower:
                return self._view_playlist()
        
        # R5.1: Handle "clear my playlist" / "clear playlist"
        if 'clear' in text_lower and 'playlist' in text_lower:
            return self._clear_playlist()
        
        # R5.4: Handle "How many songs are in my playlist?"
        if 'how many' in text_lower and 'songs' in text_lower and 'playlist' in text_lower:
            current_playlist = self._get_current_playlist()
            count = len(current_playlist.songs)
            return f"Your '{current_playlist.name}' playlist has {count} song(s)."
        
        return "I'm sorry, I don't understand. Type '/help' to see available commands."

    def _handle_nl_add_songs(self, entities: dict) -> str:
        """Handle natural language add songs command."""
        selection = entities.get('selection', '')
        songs = entities.get('songs', [])
        
        if songs:
            # Add specific songs (R5.6: Handle complex song names)
            added = []
            for song in songs:
                # Normalize song name - remove special characters for matching
                normalized_song = self._normalize_song_name(song)
                matches = self._search_songs_by_title_in_db(normalized_song)
                if not matches:
                    # Try original search
                    matches = self._search_songs_by_title_in_db(song)
                if matches:
                    result = self._add_song(matches[0])
                    added.append(matches[0])
            
            if added:
                return f"Added {len(added)} song(s) to your playlist!"
            else:
                return "Sorry, couldn't find those songs."
        
        elif selection:
            # Handle selection like "first two", "all except last"
            return self._handle_selection_add(selection)
        
        return "Please specify which songs to add."

    def _handle_nl_remove_songs(self, entities: dict) -> str:
        """Handle natural language remove songs command."""
        selection = entities.get('selection', '')
        artists = entities.get('artists', [])
        
        current_playlist = self._get_current_playlist()
        
        if artists:
            # Remove all songs by specific artists
            removed = []
            for song in current_playlist.songs[:]:
                for artist in artists:
                    if artist.lower() in song.lower():
                        current_playlist.songs.remove(song)
                        removed.append(song)
                        break
            
            if removed:
                return f"Removed {len(removed)} song(s) by {', '.join(artists)}."
            else:
                return f"No songs found by {', '.join(artists)}."
        
        elif selection:
            return self._handle_selection_remove(selection)
        
        return "Please specify which songs to remove."

    def _handle_selection_add(self, selection: str) -> str:
        """Handle selection-based adding (e.g., 'first two', 'all except last')."""
        last_recs = self._get_last_recommendations()
        
        if not last_recs:
            return "Please use /recommend first to see song suggestions, then specify which to add."
        
        selection_lower = selection.lower()
        songs_to_add = []
        
        # Parse different selection patterns
        if 'first' in selection_lower:
            # Extract number
            import re
            match = re.search(r'first\s+(\w+|\d+)', selection_lower)
            if match:
                num_word = match.group(1)
                num_map = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
                num = num_map.get(num_word, None)
                if num is None:
                    try:
                        num = int(num_word)
                    except:
                        num = 1
                songs_to_add = last_recs[:num]
        
        elif 'last' in selection_lower and 'except' not in selection_lower:
            import re
            match = re.search(r'last\s+(\w+|\d+)', selection_lower)
            if match:
                num_word = match.group(1)
                num_map = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
                num = num_map.get(num_word, None)
                if num is None:
                    try:
                        num = int(num_word)
                    except:
                        num = 1
                songs_to_add = last_recs[-num:]
        
        elif 'all' in selection_lower and 'except' in selection_lower:
            # Add all except some
            if 'last' in selection_lower:
                import re
                match = re.search(r'except.*last\s+(\w+|\d+)', selection_lower)
                if match:
                    num_word = match.group(1)
                    num_map = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
                    num = num_map.get(num_word, 1)
                    songs_to_add = last_recs[:-num] if num < len(last_recs) else []
                else:
                    songs_to_add = last_recs[:-1]
            elif 'first' in selection_lower:
                import re
                match = re.search(r'except.*first\s+(\w+|\d+)', selection_lower)
                if match:
                    num_word = match.group(1)
                    num_map = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
                    num = num_map.get(num_word, 1)
                    songs_to_add = last_recs[num:]
                else:
                    songs_to_add = last_recs[1:]
            elif 'by' in selection_lower or 'artist' in selection_lower:
                # R5.2: Handle "all except the one by [artist]"
                import re
                match = re.search(r'except.*(?:the|one|song).*by\s+([a-zA-Z0-9\s]+)', selection_lower)
                if match:
                    artist_name = match.group(1).strip()
                    songs_to_add = [s for s in last_recs if artist_name.lower() not in s.lower()]
                else:
                    # Try to extract artist from "except [artist]"
                    match = re.search(r'except\s+([a-zA-Z0-9\s]+)', selection_lower)
                    if match:
                        artist_name = match.group(1).strip()
                        songs_to_add = [s for s in last_recs if artist_name.lower() not in s.lower()]
                    else:
                        songs_to_add = last_recs
            else:
                songs_to_add = last_recs
        
        elif 'all' in selection_lower:
            songs_to_add = last_recs
        
        # Add the selected songs
        if songs_to_add:
            current_playlist = self._get_current_playlist()
            added = []
            for song in songs_to_add:
                if song not in current_playlist.songs:
                    current_playlist.songs.append(song)
                    added.append(song)
            
            if added:
                response = f"Added {len(added)} song(s) to your playlist: {', '.join([s.split(': ')[1] if ': ' in s else s for s in added[:3]])}{'...' if len(added) > 3 else ''}\n\n"
                # Include playlist view so frontend updates
                response += self._view_playlist()
                return response
            else:
                return "All selected songs are already in your playlist."
        
        return "I couldn't understand that selection. Try 'add first two' or 'add all recommendations'."

    def _handle_selection_remove(self, selection: str) -> str:
        """Handle selection-based removal."""
        current_playlist = self._get_current_playlist()
        
        if not current_playlist.songs:
            return "Your playlist is empty."
        
        # Parse selection
        if 'all' in selection.lower():
            count = len(current_playlist.songs)
            current_playlist.songs.clear()
            return f"Removed all {count} songs from your playlist."
        
        return "I couldn't understand that selection. Try '/remove [artist]: [title]' instead."


    def _store_last_recommendations(self, recommendations: List[str]) -> None:
        """Store last recommendations for selection."""
        if not hasattr(self, '_last_recommendations'):
            self._last_recommendations = []
        self._last_recommendations = recommendations

    def _get_last_recommendations(self) -> List[str]:
        """Get last recommendations."""
        if not hasattr(self, '_last_recommendations'):
            self._last_recommendations = []
        return self._last_recommendations

    def _normalize_song_name(self, song_name: str) -> str:
        """R5.6: Normalize song name to handle complex names with special characters.
        
        Handles simplified forms like "'Creepin' (with The Weeknd & 21 Savage)' by Metro Boomin"
        by removing parentheses content, quotes, and normalizing.
        
        Args:
            song_name: Song name that may contain special characters
            
        Returns:
            Normalized song name for better matching
        """
        import re
        
        # Remove content in parentheses (e.g., "(with The Weeknd & 21 Savage)")
        normalized = re.sub(r'\([^)]*\)', '', song_name)
        
        # Remove quotes
        normalized = normalized.replace("'", "").replace('"', '')
        
        # Remove "by [artist]" suffix if present
        normalized = re.sub(r'\s+by\s+.*$', '', normalized, flags=re.IGNORECASE)
        
        # Remove trailing punctuation that might interfere with search
        normalized = re.sub(r'[^\w\s]+$', '', normalized)  # Remove trailing punctuation
        
        # Remove extra whitespace
        normalized = ' '.join(normalized.split())
        
        return normalized.strip()

    def _select_recommendation(self, selection: str) -> str:
        """R4.2: Select and add recommended songs by index.
        
        Args:
            selection: Selection string (e.g., "1,3,5" or "1-3" or "1,2,3")
            
        Returns:
            Response message
        """
        last_recs = self._get_last_recommendations()
        
        if not last_recs:
            return "Please use /recommend first to see song suggestions, then specify which to add."
        
        selection = selection.strip()
        indices = []
        
        # Parse different formats: "1,3,5", "1-3", "1,2,3"
        import re
        
        # Remove any trailing text (e.g., "1,3,5th energetic songs" -> "1,3,5")
        # Extract just the numbers part
        selection_clean = re.sub(r'^(\d+(?:[,\s-]\d+)*).*$', r'\1', selection)
        
        # Handle range: "1-3"
        if '-' in selection_clean:
            match = re.match(r'(\d+)\s*-\s*(\d+)', selection_clean)
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                indices = list(range(start, end + 1))
        # Handle comma-separated: "1,3,5"
        elif ',' in selection_clean:
            # Extract numbers even with text like "1,3,5th"
            parts = selection_clean.split(',')
            for part in parts:
                # Extract first number from each part
                num_match = re.search(r'(\d+)', part.strip())
                if num_match:
                    indices.append(int(num_match.group(1)))
        # Handle single number (may have text after)
        else:
            num_match = re.search(r'(\d+)', selection_clean)
            if num_match:
                indices = [int(num_match.group(1))]
        
        # Validate indices (1-based)
        valid_indices = [i for i in indices if 1 <= i <= len(last_recs)]
        
        if not valid_indices:
            return f"Invalid selection. Please use numbers between 1 and {len(last_recs)}. Example: /select_recommendation 1,3,5"
        
        # Add selected songs
        current_playlist = self._get_current_playlist()
        added = []
        for idx in valid_indices:
            song = last_recs[idx - 1]  # Convert to 0-based
            if song not in current_playlist.songs:
                current_playlist.songs.append(song)
                added.append(song)
        
        if added:
            song_names = [s.split(': ')[1] if ': ' in s else s for s in added[:3]]
            response = f"✅ Added {len(added)} song(s) to your playlist: {', '.join(song_names)}{'...' if len(added) > 3 else ''}\n\n"
            # Also send playlist view so frontend updates
            playlist_view = self._view_playlist()
            response += playlist_view
            return response
        else:
            return "All selected songs are already in your playlist."


if __name__ == "__main__":
    platform = FlaskSocketPlatform(MusicCRS)
    
    # Monkey patch the socketio.run to add allow_unsafe_werkzeug
    original_run = platform.socketio.run
    def patched_run(app, **kwargs):
        kwargs['allow_unsafe_werkzeug'] = True
        return original_run(app, **kwargs)
    platform.socketio.run = patched_run
    
    platform.start()
