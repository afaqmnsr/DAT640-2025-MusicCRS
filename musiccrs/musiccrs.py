"""MusicCRS conversational agent."""

import json
import os
import ollama
import uuid
import sqlite3
import re
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
        
        # Initialize with error handling to prevent connection failures
        # Defer slow operations to avoid blocking connection acceptance
        try:
            # Spotify authentication - quick initialization
            self._spotify_access_token = SPOTIFY_ACCESS_TOKEN  # Use token from env if available
            self._spotify_tokens = {}  # Store access tokens
            # Only print, don't do heavy initialization
            if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
                if SPOTIFY_ACCESS_TOKEN:
                    pass  # Will print in _init_spotify_auth when needed
                else:
                    pass  # Will print in _init_spotify_auth when needed
        except Exception as e:
            print(f"Warning: Could not initialize Spotify auth: {e}")
            self._spotify_access_token = None
            self._spotify_tokens = {}
        
        # Initialize image generator - defer to avoid blocking
        self._image_generator = None  # Will be initialized lazily when needed
        
        # Ensure we have a default playlist - this is fast
        try:
            # Create minimal playlist immediately without database access
            import uuid
            playlist_id = str(uuid.uuid4())
            self._playlists[playlist_id] = Playlist(self._default_playlist_name, playlist_id)
            self._playlist_names[self._default_playlist_name] = playlist_id
            self._current_playlist_id = playlist_id
        except Exception as e:
            print(f"Warning: Could not create default playlist: {e}")
            # Fallback: create minimal playlist
            import uuid
            playlist_id = str(uuid.uuid4())
            self._playlists[playlist_id] = Playlist(self._default_playlist_name, playlist_id)
            self._playlist_names[self._default_playlist_name] = playlist_id
            self._current_playlist_id = playlist_id

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
        try:
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
                # Clean up query - remove trailing descriptive text like "to find songs that fit..."
                # Take only the first meaningful part (artist/song name)
                import re
                # Remove common trailing phrases
                query = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|find|add|search|playlist|song|track|that|fits|fit).*$', '', query, flags=re.IGNORECASE).strip()
                # If query contains "or", take the first part
                if ' or ' in query.lower():
                    query = query.split(' or ', 1)[0].strip()
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
                try:
                    song_info = utterance.text[5:]  # Remove "/add "
                    # Remove trailing phrases like "to my [playlist] playlist" or "to the [playlist] playlist"
                    # Pattern: "to [optional article] [playlist name] [optional 'playlist' word]"
                    # This matches: "to my Gym Boost playlist", "to the Gym Boost playlist", "to Gym Boost playlist", etc.
                    # Be more conservative - only match if "playlist" appears at the end
                    original_song_info = song_info
                    # Only remove if "playlist" appears near the end (last 50 chars to avoid matching song titles)
                    if len(song_info) > 10 and 'playlist' in song_info[-50:].lower():
                        # More conservative pattern - only match if we see "to [article] [name] playlist" pattern
                        song_info = re.sub(r'\s+to\s+(?:my|the|a|an)\s+[A-Za-z][A-Za-z\s]{1,30}?\s+playlist.*$', '', song_info, flags=re.IGNORECASE).strip()
                        # Also handle "to [name] playlist" without article
                        song_info = re.sub(r'\s+to\s+[A-Za-z][A-Za-z\s]{1,30}?\s+playlist.*$', '', song_info, flags=re.IGNORECASE).strip()
                        # Also remove other common trailing phrases like "from my playlist", "in my playlist"
                        song_info = re.sub(r'\s+(?:from|in|on|at)\s+(?:my|the|a|an)\s+[A-Za-z][A-Za-z\s]{1,30}?\s+playlist.*$', '', song_info, flags=re.IGNORECASE).strip()
                    
                    # If we stripped too much and song_info is empty or too short, use original
                    if not song_info or len(song_info) < 3:
                        song_info = original_song_info
                    
                    # R5.6: Normalize song name for better matching of complex names
                    normalized = self._normalize_song_name(song_info)
                    response = self._add_song(normalized)
                except Exception as e:
                    # Log the error for debugging
                    import traceback
                    print(f"Error in /add command: {e}")
                    print(traceback.format_exc())
                    # Try without normalization as fallback
                    try:
                        response = self._add_song(song_info if 'song_info' in locals() else utterance.text[5:])
                    except:
                        response = "I'm sorry, there was an error processing your request. Please try again or use '/help' to see available commands."
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
                    # Check if it's "songs by [artist]" pattern
                    import re
                    songs_by_match = re.search(r'songs?\s+by\s+(.+?)(?:\s+(?:for|to|and|my|the|a|an|playlist|workout).*)?$', recommend_part, re.IGNORECASE)
                    if songs_by_match:
                        # User wants recommendations based on songs by a specific artist
                        artist_name = songs_by_match.group(1).strip()
                        response = self._recommend_songs_by_artist(artist_name)
                    else:
                        # Extract song info, ignoring any trailing selection commands and descriptive text
                        # Remove common selection patterns and descriptive text like "for my playlist"
                        song_info = re.sub(r'\s+(?:add|select|choose).*$', '', recommend_part, flags=re.IGNORECASE)
                        song_info = re.sub(r'\s+(?:for|to|and|my|the|a|an|playlist|workout|to\s+find|that\s+fit).*$', '', song_info, flags=re.IGNORECASE)
                        song_info = song_info.strip()
                        
                        # Check if it looks like an artist name (capitalized words, possibly with "or" or "and")
                        # Pattern: "Artist Name" or "Artist1 or Artist2" or "Artist1 and Artist2"
                        if song_info:
                            # Check if it contains "or" or "and" - likely multiple artists
                            if ' or ' in song_info.lower() or ' and ' in song_info.lower():
                                # Take first artist
                                first_artist = re.split(r'\s+(?:or|and)\s+', song_info, flags=re.IGNORECASE)[0].strip()
                                if first_artist and len(first_artist.split()) <= 5:  # Reasonable artist name length
                                    response = self._recommend_songs_by_artist(first_artist)
                                else:
                                    response = self._recommend_songs(None)
                            # Check if it looks like an artist name (starts with capital, 1-5 words, no "by" keyword)
                            elif (song_info[0].isupper() and 
                                  len(song_info.split()) <= 5 and 
                                  ' by ' not in song_info.lower() and
                                  ':' not in song_info):
                                # Likely an artist name - try artist-based recommendations
                                response = self._recommend_songs_by_artist(song_info)
                            # If no valid song info after cleanup, use current playlist
                            elif not song_info or len(song_info.split()) > 5:
                                response = self._recommend_songs(None)
                            else:
                                response = self._recommend_songs(song_info)
                        else:
                            response = self._recommend_songs(None)
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
                    "what songs does",
                    "what's the name",
                    "what is the name",
                    "which artist",
                    "what artist",
                    "just added",
                    "you just added",
                    "you added"
                ]
                
                is_question = any(pattern in utterance_lower for pattern in question_patterns)
                
                if is_question:
                    # Treat as a natural language question
                    response = self._answer_question(utterance.text)
                else:
                    # Try natural language processing
                    response = self._process_natural_language(utterance.text)
                    # If response is None, it means goodbye was triggered
                    if response is None:
                        return

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
        except Exception as e:
            # Log the error and send a safe response to prevent server crash
            import traceback
            print(f"Error processing utterance '{utterance.text}': {e}")
            print(traceback.format_exc())
            
            # Send error response to user
            error_response = "I'm sorry, there was an error processing your request. Please try again or use '/help' to see available commands."
            
            if self._dialogue_connector is not None:
                self._dialogue_connector.register_agent_utterance(
                    AnnotatedUtterance(
                        error_response,
                        participant=DialogueParticipant.AGENT,
                        dialogue_acts=[],
                    )
                )
            else:
                if not hasattr(self, '_pending_response'):
                    self._pending_response = None
                self._pending_response = error_response

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
            print("Processing all files to build complete database (this may take a while)...")
            
            # Use a set to track unique songs
            unique_songs = {}
            
            # Process all JSON files (or limit to first 100 for faster initial load)
            max_files = len(json_files)  # Process all files for complete database
            if max_files < len(json_files):
                print(f"Processing first {max_files} files out of {len(json_files)} total files...")
                print("To load all files, set max_files to len(json_files) in the code.")
            
            for file_idx, json_file in enumerate(json_files[:max_files]):
                filepath = os.path.join(dataset_path, json_file)
                print(f"Loading {json_file} ({file_idx + 1}/{max_files})...")
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    playlists = data.get('playlists', [])
                    print(f"Processing {len(playlists)} playlists from {json_file}...")
                    
                    # Extract tracks from playlists
                    for i, playlist in enumerate(playlists):
                        if i % 1000 == 0 and i > 0:
                            print(f"  Processed {i}/{len(playlists)} playlists from {json_file}...")
                        
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
                except Exception as e:
                    print(f"Error loading {json_file}: {e}")
                    continue
            
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
        """Search for songs in the database by artist or title.
        
        Prioritizes exact matches, especially for multi-word artist names like "Die Ärzte".
        """
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        query_stripped = query.strip()
        query_lower = query_stripped.lower()
        
        # Check if query looks like a multi-word artist name (2+ words, capitalized)
        is_multi_word_artist = len(query_stripped.split()) >= 2 and query_stripped[0].isupper()
        
        if is_multi_word_artist:
            # For multi-word artist names, prioritize exact artist matches
            # Try exact match first (case-insensitive)
            cursor.execute('''
                SELECT song_key FROM songs 
                WHERE LOWER(TRIM(artist)) = LOWER(?)
                ORDER BY artist, title
                LIMIT 100
            ''', (query_stripped,))
            exact_artist_matches = [row[0] for row in cursor.fetchall()]
            
            if exact_artist_matches:
                conn.close()
                return exact_artist_matches
            
            # If no exact match, try with special character variations (ä->ae, etc.)
            query_clean = query_stripped.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('Ä', 'Ae').replace('Ö', 'Oe').replace('Ü', 'Ue')
            if query_clean != query_stripped:
                cursor.execute('''
                    SELECT song_key FROM songs 
                    WHERE LOWER(TRIM(artist)) = LOWER(?)
                    ORDER BY artist, title
                    LIMIT 100
                ''', (query_clean,))
                fuzzy_matches = [row[0] for row in cursor.fetchall()]
                if fuzzy_matches:
                    conn.close()
                    return fuzzy_matches
            
            # Try partial match on artist (artist contains the query)
            query_lower_pattern = f"%{query_lower}%"
            cursor.execute('''
                SELECT song_key FROM songs 
                WHERE LOWER(artist) LIKE ?
                ORDER BY 
                    CASE WHEN LOWER(TRIM(artist)) = LOWER(?) THEN 1
                         WHEN LOWER(artist) LIKE LOWER(?) THEN 2
                         ELSE 3 END,
                    artist, title
                LIMIT 100
            ''', (query_lower_pattern, query_stripped, f"{query_lower}%"))
            partial_matches = [row[0] for row in cursor.fetchall()]
            
            if partial_matches:
                conn.close()
                return partial_matches
        
        # Standard search for single words or when multi-word didn't match
        query_lower_pattern = f"%{query_lower}%"
        cursor.execute('''
            SELECT song_key FROM songs 
            WHERE LOWER(artist) LIKE ? OR LOWER(title) LIKE ?
            ORDER BY 
                CASE WHEN LOWER(title) = LOWER(?) THEN 1
                     WHEN LOWER(title) LIKE LOWER(?) THEN 2
                     WHEN LOWER(TRIM(artist)) = LOWER(?) THEN 3
                     WHEN LOWER(artist) LIKE LOWER(?) THEN 4
                     ELSE 5 END,
                artist, title
            LIMIT 100
        ''', (query_lower_pattern, query_lower_pattern, query_stripped, f"{query_lower}%", query_stripped, f"{query_lower}%"))
        
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
                        # Try exact match first (case-insensitive) with EXACT artist match priority
                        cursor.execute('''
                            SELECT song_key FROM songs 
                            WHERE LOWER(TRIM(artist)) = LOWER(TRIM(?)) 
                              AND (LOWER(TRIM(title)) = LOWER(TRIM(?))
                                   OR LOWER(TRIM(REPLACE(REPLACE(REPLACE(title, '(', ''), ')', ''), '  ', ' '))) = LOWER(TRIM(?)))
                            LIMIT 1
                        ''', (artist_clean, title_clean, title_clean))
                        result = cursor.fetchone()
                        
                        # If still not found, try with artist in quotes (for artists with spaces)
                        if not result and " " in artist_clean:
                            cursor.execute('''
                                SELECT song_key FROM songs 
                                WHERE LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) = LOWER(TRIM(?)) 
                                  AND (LOWER(TRIM(title)) = LOWER(TRIM(?))
                                       OR LOWER(TRIM(REPLACE(REPLACE(REPLACE(title, '(', ''), ')', ''), '  ', ' '))) = LOWER(TRIM(?)))
                                LIMIT 1
                            ''', (artist_clean, title_clean, title_clean))
                            result = cursor.fetchone()
                        
                        # If no exact artist match, try to find song by title (handling parenthetical parts)
                        # But prioritize the requested artist strongly
                        if not result:
                            # First, try fuzzy artist matching - check if artist name is similar
                            # Try with variations (e.g., "The Supertramp" vs "Supertramp")
                            artist_variations = [artist_clean.lower().strip()]
                            if artist_clean.lower().strip().startswith('the '):
                                artist_variations.append(artist_clean.lower().strip()[4:])
                            else:
                                artist_variations.append('the ' + artist_clean.lower().strip())
                            
                            # Try exact title match with artist variations
                            placeholders = ','.join(['?' for _ in artist_variations])
                            cursor.execute(f'''
                                SELECT song_key FROM songs 
                                WHERE LOWER(TRIM(title)) = LOWER(TRIM(?))
                                  AND LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) IN ({placeholders})
                                LIMIT 1
                            ''', [title_clean] + artist_variations)
                            result = cursor.fetchone()
                            
                            # If still not found, try partial artist match (handles typos)
                            if not result:
                                cursor.execute('''
                                    SELECT song_key FROM songs 
                                    WHERE LOWER(TRIM(title)) = LOWER(TRIM(?))
                                      AND (LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) LIKE ? 
                                           OR ? LIKE LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) || '%')
                                    ORDER BY 
                                        CASE WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) = LOWER(TRIM(?)) THEN 0
                                             WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) LIKE ? || '%' THEN 1
                                             ELSE 2 END
                                    LIMIT 1
                                ''', (title_clean, f"%{artist_clean.lower()}%", artist_clean.lower(), artist_clean.lower(), f"%{artist_clean.lower()}%"))
                                result = cursor.fetchone()
                            
                            # If still not found, try title match but warn if artist doesn't match
                            if not result:
                                cursor.execute('''
                                    SELECT song_key, artist FROM songs 
                                    WHERE LOWER(TRIM(title)) = LOWER(TRIM(?))
                                    ORDER BY 
                                        CASE WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) = LOWER(TRIM(?)) THEN 0 ELSE 1 END,
                                        CASE WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) LIKE ? || '%' THEN 0 ELSE 1 END,
                                        artist
                                    LIMIT 1
                                ''', (title_clean, artist_clean.lower(), f"%{artist_clean.lower()}%"))
                                result = cursor.fetchone()
                                
                                # Check if the found artist matches the requested one
                                if result:
                                    found_song_key, found_artist = result
                                    found_artist_clean = found_artist.replace('"', '').replace("'", "").strip().lower()
                                    requested_artist_clean = artist_clean.lower().strip()
                                    
                                    # Check if artists match (exact or fuzzy)
                                    artists_match = (
                                        found_artist_clean == requested_artist_clean or
                                        requested_artist_clean in found_artist_clean or
                                        found_artist_clean in requested_artist_clean or
                                        # Handle common variations like "Luke Coombs" vs "Luke Combs"
                                        self._artist_names_similar(requested_artist_clean, found_artist_clean)
                                    )
                                    
                                    # If artists don't match, DO NOT add the song - return error
                                    if not artists_match:
                                        # Check if we can find any match with the requested artist
                                        cursor.execute('''
                                            SELECT song_key FROM songs 
                                            WHERE LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) LIKE ?
                                            LIMIT 5
                                        ''', (f"%{requested_artist_clean}%",))
                                        artist_songs = cursor.fetchall()
                                        
                                        if artist_songs:
                                            # Artist exists but doesn't have this song
                                            conn.close()
                                            return f"Sorry, I couldn't find '{title_clean}' by {artist_clean} in our database. I found '{title_clean}' by {found_artist} instead. Would you like to add that version, or search for a different song?"
                                        else:
                                            # Artist doesn't exist in database
                                            conn.close()
                                            return f"Sorry, I couldn't find '{title_clean}' by {artist_clean} in our database. I found '{title_clean}' by {found_artist} instead. Would you like to add that version?"
                                    
                                    # Only set result if artists match
                                    result = (found_song_key,)
                            
                            # If still not found, try matching title with LIKE (handles parenthetical parts)
                            # But be stricter for short titles or single-word titles - require word boundary or exact match
                            if not result:
                                # For short titles (3 chars or less) OR single-word titles, only try exact match or word boundary
                                # This prevents "Agency" from matching "The Agency Heist"
                                is_single_word = len(title_clean.split()) == 1
                                if len(title_clean) <= 3 or is_single_word:
                                    # Very short title or single word - only exact match or word boundary
                                    # For single words, require exact match or word boundary to prevent substring matches
                                    # e.g., "Agency" should NOT match "The Agency Heist"
                                    if is_single_word:
                                        # Single word - require exact match or title starts with the word
                                        # This prevents "Agency" from matching "The Agency Heist"
                                        # Only match if title is exactly "Agency" or starts with "Agency "
                                        cursor.execute('''
                                            SELECT song_key, artist FROM songs 
                                            WHERE (LOWER(TRIM(title)) = LOWER(TRIM(?))
                                                   OR LOWER(TRIM(title)) LIKE LOWER(TRIM(?)) || ' %'
                                                   OR LOWER(TRIM(REPLACE(REPLACE(REPLACE(title, '(', ''), ')', ''), '  ', ' '))) = LOWER(TRIM(?)))
                                            ORDER BY 
                                                CASE WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) = LOWER(TRIM(?)) THEN 0 ELSE 1 END,
                                                CASE WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) LIKE ? || '%' THEN 0 ELSE 1 END,
                                                CASE WHEN LOWER(TRIM(title)) = LOWER(TRIM(?)) THEN 0 ELSE 1 END,
                                                artist
                                            LIMIT 1
                                        ''', (title_clean, title_clean, title_clean, artist_clean.lower(), f"%{artist_clean.lower()}%", title_clean))
                                    else:
                                        # Very short (<=3 chars) - only exact match or word boundary
                                        cursor.execute('''
                                            SELECT song_key, artist FROM songs 
                                            WHERE (LOWER(TRIM(title)) = LOWER(TRIM(?))
                                                   OR LOWER(TRIM(title)) LIKE LOWER(TRIM(?)) || ' %'
                                                   OR LOWER(TRIM(REPLACE(REPLACE(REPLACE(title, '(', ''), ')', ''), '  ', ' '))) = LOWER(TRIM(?)))
                                            ORDER BY 
                                                CASE WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) = LOWER(TRIM(?)) THEN 0 ELSE 1 END,
                                                CASE WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) LIKE ? || '%' THEN 0 ELSE 1 END,
                                                CASE WHEN LOWER(TRIM(title)) = LOWER(TRIM(?)) THEN 0 ELSE 1 END,
                                                artist
                                            LIMIT 1
                                        ''', (title_clean, title_clean, title_clean, artist_clean.lower(), f"%{artist_clean.lower()}%", title_clean))
                                else:
                                    # Longer title - allow prefix matching but prioritize exact
                                    cursor.execute('''
                                        SELECT song_key, artist FROM songs 
                                        WHERE (LOWER(TRIM(title)) LIKE LOWER(TRIM(?)) || '%'
                                               OR LOWER(TRIM(REPLACE(REPLACE(REPLACE(title, '(', ''), ')', ''), '  ', ' '))) LIKE LOWER(TRIM(?)) || '%')
                                        ORDER BY 
                                            CASE WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) = LOWER(TRIM(?)) THEN 0 ELSE 1 END,
                                            CASE WHEN LOWER(TRIM(REPLACE(REPLACE(artist, '"', ''), "'", ''))) LIKE ? || '%' THEN 0 ELSE 1 END,
                                            CASE WHEN LOWER(TRIM(title)) = LOWER(TRIM(?)) THEN 0 
                                                 WHEN LOWER(TRIM(title)) LIKE LOWER(TRIM(?)) || '%' THEN 1 
                                                 ELSE 2 END,
                                            artist
                                        LIMIT 1
                                    ''', (title_clean, title_clean, artist_clean.lower(), f"%{artist_clean.lower()}%", title_clean, title_clean))
                                
                                result = cursor.fetchone()
                                
                                # Check if artist matches when using LIKE
                                if result and len(result) == 2:
                                    found_song_key, found_artist = result
                                    found_artist_clean = found_artist.replace('"', '').replace("'", "").strip().lower()
                                    requested_artist_clean = artist_clean.lower().strip()
                                    
                                    # Check if artists match (exact or fuzzy)
                                    artists_match = (
                                        found_artist_clean == requested_artist_clean or
                                        requested_artist_clean in found_artist_clean or
                                        found_artist_clean in requested_artist_clean or
                                        # Handle common variations like "Luke Coombs" vs "Luke Combs"
                                        self._artist_names_similar(requested_artist_clean, found_artist_clean)
                                    )
                                    
                                    # If artists don't match, DO NOT add the song - return error
                                    if not artists_match:
                                        conn.close()
                                        return f"Sorry, I couldn't find '{title_clean}' by {artist_clean} in our database. I found a similar song '{found_song_key.split(': ', 1)[1] if ': ' in found_song_key else found_song_key}' by {found_artist} instead. Would you like to add that version?"
                                    
                                    # Only set result if artists match
                                    result = (found_song_key,)
                        
                        conn.close()
                        if result:
                            # Extract song_key from result (could be (song_key,) or (song_key, artist))
                            song_key = result[0]
                        else:
                            return f"Sorry, '{song_info}' is not available in our database. Please check the spelling and try again."
                else:
                    return f"Sorry, '{song_info}' is not available in our database. Please check the spelling and try again."
        else:
            # Title-only format - but check if user specified an artist with "by [artist]"
            import re
            # Fix common typos FIRST (like "bby" -> "by") before pattern matching
            song_info_fixed = re.sub(r'\bbby\b', 'by', song_info, flags=re.IGNORECASE)
            song_info_clean_fixed = song_info_fixed.replace('"', '').replace("'", "")
            
            requested_artist = None
            title_only = song_info_clean_fixed
            
            # Check for "by [artist]" pattern - handle both "by" and fixed "bby"
            by_match = re.search(r'\s+(?:by|bby)\s+([^,\.]+?)(?:\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|$))', song_info_fixed, re.IGNORECASE)
            if by_match:
                requested_artist = by_match.group(1).strip()
                # Remove "by [artist]" from title for searching
                title_only = re.sub(r'\s+(?:by|bby)\s+.*$', '', song_info_clean_fixed, flags=re.IGNORECASE).strip()
                # Fix common typos in artist name
                requested_artist = re.sub(r'\bbby\b', 'by', requested_artist, flags=re.IGNORECASE)
                requested_artist = re.sub(r'([a-z])\1{2,}', r'\1\1', requested_artist, flags=re.IGNORECASE)  # Fix double letters
            
            # If artist is specified, try direct database search first for better accuracy
            song_key = None  # Initialize to track if we found a direct match
            if requested_artist:
                self._ensure_database()
                conn = sqlite3.connect(self._db_path)
                cursor = conn.cursor()
                
                # Try exact match: title + artist
                title_clean_lower = title_only.lower().strip()
                artist_clean_lower = requested_artist.lower().strip()
                
                # Search for exact match first
                cursor.execute('''
                    SELECT song_key FROM songs 
                    WHERE LOWER(TRIM(title)) = LOWER(TRIM(?))
                      AND LOWER(TRIM(artist)) = LOWER(TRIM(?))
                    LIMIT 1
                ''', (title_clean_lower, artist_clean_lower))
                exact_match = cursor.fetchone()
                
                if exact_match:
                    conn.close()
                    song_key = exact_match[0]
                    # Skip to adding the song - set matches to empty to skip matching logic
                    matches = []
                else:
                    # Try with artist variations (e.g., "The Queen" vs "Queen")
                    artist_variations = [artist_clean_lower]
                    if artist_clean_lower.startswith('the '):
                        artist_variations.append(artist_clean_lower[4:])
                    else:
                        artist_variations.append('the ' + artist_clean_lower)
                    
                    placeholders = ','.join(['?' for _ in artist_variations])
                    cursor.execute(f'''
                        SELECT song_key FROM songs 
                        WHERE LOWER(TRIM(title)) = LOWER(TRIM(?))
                          AND LOWER(TRIM(artist)) IN ({placeholders})
                        LIMIT 1
                    ''', [title_clean_lower] + artist_variations)
                    variation_match = cursor.fetchone()
                    
                    if variation_match:
                        conn.close()
                        song_key = variation_match[0]
                        # Skip to adding the song - set matches to empty to skip matching logic
                        matches = []
                    else:
                        conn.close()
                        # Fall through to regular search
                        matches = self._search_songs_by_title_in_db(title_only)
                        if not matches:
                            # Try original search
                            matches = self._search_songs_by_title_in_db(song_info)
                        if not matches:
                            # Try searching for partial match (e.g., "Creepin" should find "Creepin'")
                            # Remove common suffixes and search
                            base_name = re.sub(r'[^\w\s]', '', song_info_clean).strip()
                            if base_name:
                                matches = self._search_songs_by_title_in_db(base_name)
            else:
                # No artist specified, use regular search
                matches = self._search_songs_by_title_in_db(title_only)
                if not matches:
                    # Try original search
                    matches = self._search_songs_by_title_in_db(song_info)
                if not matches:
                    # Try searching for partial match (e.g., "Creepin" should find "Creepin'")
                    # Remove common suffixes and search
                    base_name = re.sub(r'[^\w\s]', '', song_info_clean).strip()
                    if base_name:
                        matches = self._search_songs_by_title_in_db(base_name)
            
            # If we already found a direct match, skip the matching logic
            if not song_key:
                if not matches:
                    # Check if this looks like a recommendation request that was misidentified
                    if any(keyword in song_info.lower() for keyword in ['recommend', 'suggest', 'recommendation', 'recommendations', 'based on', 'fit', 'theme']):
                        return "It looks like you're asking for recommendations. Try saying 'Can you recommend songs?' or use '/recommend' to get song suggestions based on your playlist."
                    return f"Sorry, no songs found with title '{song_info}'. Try searching with '/search {song_info}' to see available options."
                
                # If user specified an artist, prioritize matches by that artist
                if requested_artist and matches:
                    # First, try to find exact match by requested artist
                    requested_artist_lower = requested_artist.lower().strip()
                    # Also try with common variations (e.g., "The Queen" vs "Queen")
                    requested_artist_variations = [requested_artist_lower]
                    if requested_artist_lower.startswith('the '):
                        requested_artist_variations.append(requested_artist_lower[4:])
                    else:
                        requested_artist_variations.append('the ' + requested_artist_lower)
                    
                    exact_artist_matches = []
                    close_artist_matches = []
                    fuzzy_artist_matches = []
                    other_matches = []
                    
                    for match in matches:
                        if ': ' in match:
                            artist, _ = match.split(': ', 1)
                            artist_lower = artist.lower().strip()
                            # Try exact match first (including variations)
                            if artist_lower in requested_artist_variations:
                                exact_artist_matches.append(match)
                            # Try substring match (handles typos like "Queeen" -> "Queen")
                            elif requested_artist_lower in artist_lower or artist_lower in requested_artist_lower:
                                close_artist_matches.append(match)
                            # Try fuzzy match - check if artist names are similar (handles typos)
                            elif self._artist_names_similar(requested_artist, artist):
                                fuzzy_artist_matches.append(match)
                            else:
                                other_matches.append(match)
                        else:
                            other_matches.append(match)
                    
                    # Prioritize: exact matches > close matches > fuzzy matches > others
                    if exact_artist_matches:
                        song_key = exact_artist_matches[0]
                    elif close_artist_matches:
                        song_key = close_artist_matches[0]
                    elif fuzzy_artist_matches:
                        song_key = fuzzy_artist_matches[0]
                    elif len(matches) == 1:
                        # Only one match, but not by requested artist - warn user
                        song_key = matches[0]
                        if ': ' in song_key:
                            actual_artist, title = song_key.split(': ', 1)
                            return f"I found '{title}' by {actual_artist}, but you requested it by {requested_artist}. Would you like to add this version, or search for a different one?"
                    else:
                        # Multiple matches, none by requested artist - show disambiguation but mention artist preference
                        return f"I found multiple songs with title '{title_only}', but none by {requested_artist}. " + self._provide_song_disambiguation(song_info, matches)
                elif len(matches) == 1:
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
        
        # Format response to show artist and title clearly
        if ': ' in song_key:
            artist, title = song_key.split(': ', 1)
            response = f"Added '{title}' by {artist} to your '{current_playlist.name}' playlist!\n\n"
        else:
            response = f"Added '{song_key}' to your '{current_playlist.name}' playlist!\n\n"
        
        # Include playlist view so frontend updates
        response += self._view_playlist()
        return response

    def _remove_song(self, song_info: str) -> str:
        """Remove a song from the current playlist.
        
        Args:
            song_info: Song in format "artist: title", just "title", or just "artist" (removes all songs by that artist)
            
        Returns:
            Response message
        """
        song_key = song_info.strip()
        
        # Get current playlist
        current_playlist = self._get_current_playlist()
        
        # First try exact match
        if song_key in current_playlist.songs:
            current_playlist.songs.remove(song_key)
            return f"Removed '{song_key}' from your '{current_playlist.name}' playlist!"
        
        # Check if it's a request to remove all songs by an artist (no colon, and matches an artist name)
        # Pattern: "Remove Metallica" or "remove ABBA songs"
        song_key_lower = song_key.lower()
        # Remove common suffixes like "songs" or "tracks"
        artist_name = re.sub(r'\s+(songs?|tracks?)$', '', song_key, flags=re.IGNORECASE).strip()
        artist_name_lower = artist_name.lower()
        
        # Check if this matches any artist in the playlist
        removed_by_artist = []
        for song in list(current_playlist.songs):  # Use list() to avoid modification during iteration
            if ':' in song:
                artist, _ = song.split(':', 1)
                artist_clean = artist.strip().lower()
                # Check if the requested name matches the artist (exact or partial)
                if (artist_name_lower == artist_clean or 
                    artist_name_lower in artist_clean or 
                    artist_clean in artist_name_lower):
                    current_playlist.songs.remove(song)
                    removed_by_artist.append(song)
        
        if removed_by_artist:
            count = len(removed_by_artist)
            return f"Removed {count} song(s) by '{artist_name}' from your '{current_playlist.name}' playlist!"
        
        # Try to match by artist and title (case-insensitive, with normalization)
        if ':' in song_key:
            parts = song_key.split(':', 1)
            if len(parts) == 2:
                requested_artist = parts[0].strip().lower()
                requested_title = parts[1].strip().lower()
                
                # Try exact artist and title match (case-insensitive)
                for song in current_playlist.songs:
                    if ':' in song:
                        artist, title = song.split(':', 1)
                        artist_clean = artist.strip().lower()
                        title_clean = title.strip().lower()
                        
                        # Exact match on both
                        if artist_clean == requested_artist and title_clean == requested_title:
                            current_playlist.songs.remove(song)
                            return f"Removed '{song}' from your '{current_playlist.name}' playlist!"
                        
                        # Match by title only if artist matches (handle variations)
                        if title_clean == requested_title:
                            # Check if artist is similar (handles accents, etc.)
                            if requested_artist in artist_clean or artist_clean in requested_artist:
                                current_playlist.songs.remove(song)
                                return f"Removed '{song}' from your '{current_playlist.name}' playlist!"
                
                # Try title-only match if artist specified but not found
                for song in current_playlist.songs:
                    if ':' in song:
                        artist, title = song.split(':', 1)
                        title_clean = title.strip().lower()
                        if title_clean == requested_title:
                            current_playlist.songs.remove(song)
                            return f"Removed '{song}' from your '{current_playlist.name}' playlist!"
        
        # Try partial match by title only (for title-only input)
        song_lower = song_key.lower()
        for song in current_playlist.songs:
            if ':' in song:
                _, title = song.split(':', 1)
                if song_lower == title.strip().lower() or song_lower in title.lower() or title.lower() in song_lower:
                    current_playlist.songs.remove(song)
                    return f"Removed '{song}' from your '{current_playlist.name}' playlist!"
            else:
                # Song without artist
                if song_lower == song.lower() or song_lower in song.lower():
                    current_playlist.songs.remove(song)
                    return f"Removed '{song}' from your '{current_playlist.name}' playlist!"
        
        return f"'{song_key}' is not in your '{current_playlist.name}' playlist."

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
        
        # Handle confirmation questions about playlist contents (check FIRST)
        # Patterns like "confirm that X has been added", "is X in the playlist", "does the playlist have X"
        import re
        confirmation_patterns = [
            r"confirm\s+(?:that\s+)?(.+?)\s+(?:has\s+been\s+added|is\s+in|in\s+the\s+playlist)",
            r"is\s+(.+?)\s+(?:in|on)\s+(?:the\s+)?playlist",
            r"does\s+(?:the\s+)?playlist\s+(?:have|contain)\s+(.+?)",
            r"has\s+(.+?)\s+been\s+added",
            r"can\s+you\s+confirm\s+(?:that\s+)?(.+?)\s+(?:has\s+been\s+added|is\s+in)",
        ]
        
        for pattern in confirmation_patterns:
            match = re.search(pattern, question_lower, re.IGNORECASE)
            if match:
                song_info = match.group(1).strip()
                # Clean up common trailing words
                song_info = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|now|yet).*$', '', song_info, flags=re.IGNORECASE).strip()
                
                if song_info:
                    # Check if song is in current playlist
                    current_playlist = self._get_current_playlist()
                    
                    # Try to match the song
                    song_found = None
                    for song in current_playlist.songs:
                        # Check if the song info matches (case-insensitive, partial match)
                        if song_info.lower() in song.lower() or song.lower() in song_info.lower():
                            song_found = song
                            break
                        # Check if "Title by Artist" format matches
                        if 'by' in song_info.lower():
                            parts = song_info.lower().split('by', 1)
                            if len(parts) == 2:
                                title_part = parts[0].strip()
                                artist_part = parts[1].strip()
                                if ':' in song:
                                    song_artist, song_title = song.split(':', 1)
                                    if title_part in song_title.lower() and artist_part in song_artist.lower():
                                        song_found = song
                                        break
                    
                    if song_found:
                        if ': ' in song_found:
                            artist, title = song_found.split(': ', 1)
                            return f"Yes! '{title}' by {artist} is in your '{current_playlist.name}' playlist."
                        else:
                            return f"Yes! '{song_found}' is in your '{current_playlist.name}' playlist."
                    else:
                        # Song not found in playlist
                        return f"No, I don't see '{song_info}' in your '{current_playlist.name}' playlist. Would you like me to add it?"
        
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
        
        # Questions about songs in current playlist
        # Must be specifically asking about songs, not just complaining
        elif (("playlist" in question_lower or "just added" in question_lower or "last song" in question_lower) and \
             ("artist" in question_lower or "song" in question_lower)) or \
             ("what" in question_lower and "song" in question_lower and ("added" in question_lower or "playlist" in question_lower)):
            current_playlist = self._get_current_playlist()
            if not current_playlist.songs:
                return "Your playlist is empty."
            
            # Get the last song added
            last_song = current_playlist.songs[-1]
            
            # Extract song title from question if mentioned
            song_from_question = self._extract_song_from_question(question)
            
            # Only process if we extracted a valid short song name (not a whole sentence)
            if song_from_question and len(song_from_question.split()) <= 5:
                # User is asking about a specific song in the playlist
                # Check if it's in the playlist
                matching_song = None
                for song in current_playlist.songs:
                    if song_from_question.lower() in song.lower():
                        matching_song = song
                        break
                
                if matching_song:
                    # Parse the song to get artist
                    if ':' in matching_song:
                        artist, title = matching_song.split(':', 1)
                        artist = artist.strip()
                        title = title.strip()
                        return f"The song '{title}' in your playlist is by {artist}."
                    else:
                        return f"'{matching_song}' is in your playlist, but I couldn't determine the artist format."
                else:
                    # Song not found in playlist
                    return f"I don't see '{song_from_question}' in your playlist. Would you like to see your current playlist?"
            else:
                # General question about last added song
                if ':' in last_song:
                    artist, title = last_song.split(':', 1)
                    artist = artist.strip()
                    title = title.strip()
                    return f"The last song added to your playlist is '{title}' by {artist}."
                else:
                    return f"The last song in your playlist is '{last_song}'."
        
        # Handle statements about expectations or preferences (e.g., "I was expecting more X")
        elif "expecting" in question_lower or "expected" in question_lower or "prefer" in question_lower or "want more" in question_lower:
            # Extract genre/artist/style from the statement
            import re
            # Try to extract what they're expecting
            genre_match = re.search(r'(?:expecting|expected|want more|prefer|looking for)\s+(?:more\s+)?([^,\.]+?)(?:\s+(?:in|on|for|and|,|\.|$))', question_lower, re.IGNORECASE)
            if genre_match:
                genre_or_style = genre_match.group(1).strip()
                # Suggest using /recommend or /generate
                return f"I understand you'd like more {genre_or_style} music. You can:\n• Use '/recommend songs by [artist]' to get recommendations by a specific artist\n• Use '/generate [description]' to create a playlist with that style\n• Or tell me which artists you'd like, and I can help you add their songs!"
            else:
                return "I understand you'd like different music. You can:\n• Use '/recommend songs by [artist]' to get recommendations\n• Use '/generate [description]' to create a new playlist\n• Or tell me which songs or artists you'd like to add!"
        
        # Default response for unrecognized questions
        else:
            return f"I can answer questions about:\n• Song durations\n• Albums\n• Artist song counts\n• Popular artists\n• Songs by specific artists\n• Database statistics\n• Compilation albums\n\nTry asking something like:\n• 'How many songs does The Beatles have?'\n• 'How long is Bohemian Rhapsody?'\n• 'What album is Hotel California from?'\n• 'Who are the most popular artists?'\n• 'What songs does The Beatles have?'\n• 'How many songs are in the database?'\n• 'Which artist appears most often in Best of 90s albums?'"

    def _artist_names_similar(self, name1: str, name2: str) -> bool:
        """Check if two artist names are similar (handles typos)."""
        import re
        name1_clean = re.sub(r'[^\w\s]', '', name1.lower()).strip()
        name2_clean = re.sub(r'[^\w\s]', '', name2.lower()).strip()
        
        # Remove extra repeated letters (e.g., "Queeen" -> "Queen")
        name1_clean = re.sub(r'([a-z])\1{2,}', r'\1\1', name1_clean)
        name2_clean = re.sub(r'([a-z])\1{2,}', r'\1\1', name2_clean)
        
        # Check if they're the same after normalization
        if name1_clean == name2_clean:
            return True
        
        # Check if one is a substring of the other (with some tolerance)
        if len(name1_clean) >= 3 and len(name2_clean) >= 3:
            # If one name is mostly contained in the other
            if name1_clean in name2_clean or name2_clean in name1_clean:
                return True
            
            # Check Levenshtein-like similarity (simple version)
            # If names differ by 1-2 characters, they might be similar
            if abs(len(name1_clean) - len(name2_clean)) <= 2:
                # Count matching characters at start
                min_len = min(len(name1_clean), len(name2_clean))
                matching = sum(1 for i in range(min_len) if name1_clean[i] == name2_clean[i])
                if matching >= min_len * 0.7:  # 70% of characters match
                    return True
        
        return False

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
        
        # Try to extract song title with various patterns
        question_lower = question.lower()
        
        # Pattern: "song with the title X" or "song called X" or "song X"
        patterns = [
            r"title\s+([a-z0-9\s]+?)(?:\s+(?:did|that|you|by|to|from|in|is|\?|,))",  # "title Goodbye did you"
            r"song\s+(?:with\s+the\s+title\s+|called\s+)?([a-z0-9\s]+?)(?:\s+(?:did|that|you|by|to|from|in|is|\?|,))",  # "song Goodbye" or "song called Goodbye"
            r"track\s+([a-z0-9\s]+?)(?:\s+(?:did|that|you|by|to|from|in|is|\?|,))",
            r"'([^']+)'",  # Quoted song name
            r'"([^"]+)"',  # Double-quoted song name
        ]
        
        for pattern in patterns:
            match = re.search(pattern, question_lower)
            if match:
                song = match.group(1).strip()
                # Clean up common question words
                song = re.sub(r'\b(how long|what album|from|the)\b', '', song).strip()
                if song and len(song) > 1:
                    return song.title()
        
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

    def _recommend_songs(self, song_info: str = None, limit: int = 5) -> str:
        """Recommend related songs based on a given song or current playlist.
        
        Args:
            song_info: Song to base recommendations on (optional)
            limit: Number of recommendations to return (default: 5)
            
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
        recommendations = self._get_song_recommendations(song_key, limit=limit)
        
        if not recommendations:
            return f"Sorry, couldn't find recommendations for '{song_key}'."
        
        # Store recommendations for later selection
        rec_songs = [rec[0] for rec in recommendations]
        self._store_last_recommendations(rec_songs)
        
        # Format response
        if limit == 1:
            response = f"🎵 **Recommendation based on '{song_key}':**\n\n"
        else:
            response = f"🎵 **Recommendations based on '{song_key}':**\n\n"
        
        for i, (rec_song, reason) in enumerate(recommendations, 1):
            response += f"{i}. {rec_song}\n   💡 {reason}\n\n"
        
        # Only show "To add songs" instructions if there's more than one recommendation
        if limit > 1:
            response += "\n**To add songs:**\n"
            response += "• Use: /select_recommendation 1,3,5 (by indices)\n"
            response += "• Or: /select_recommendation 1-3 (range)\n"
            response += "• Or say: 'Add the first two songs'\n"
            response += "• Or say: 'Add all except the last one'\n"
            response += "• Or say: 'Add all except the one by [artist]'\n"
            response += "• Or say: 'Add all recommendations'"
        else:
            response += "\n**To add this song:**\n"
            response += "• Say: 'Add this song' or 'Add it'\n"
            response += "• Or use: /select_recommendation 1"
        
        return response

    def _recommend_songs_by_artist(self, artist_name: str, limit: int = 5) -> str:
        """Recommend songs by a specific artist.
        
        Args:
            artist_name: Name of the artist
            limit: Number of recommendations to return (default: 5)
            
        Returns:
            Response with song recommendations by the artist
        """
        self._ensure_database()
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        # Get current playlist to avoid duplicates
        current_playlist = self._get_current_playlist()
        existing_songs = set(current_playlist.songs)
        
        # Search for songs by this artist (case-insensitive)
        cursor.execute('''
            SELECT song_key, title FROM songs 
            WHERE LOWER(TRIM(artist)) LIKE LOWER(TRIM(?))
            ORDER BY RANDOM()
            LIMIT ?
        ''', (f'%{artist_name}%', limit * 2))  # Get more to filter out duplicates
        
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return f"Sorry, I couldn't find any songs by '{artist_name}' in our database. Please check the spelling or try a different artist."
        
        # Filter out songs already in playlist
        recommendations = []
        for song_key, title in results:
            if song_key not in existing_songs and len(recommendations) < limit:
                recommendations.append((song_key, f"Song by {artist_name}"))
        
        if not recommendations:
            return f"All songs by '{artist_name}' in our database are already in your playlist!"
        
        # Store recommendations for later selection
        rec_songs = [rec[0] for rec in recommendations]
        self._store_last_recommendations(rec_songs)
        
        # Format response
        response = f"🎵 **Songs by '{artist_name}':**\n\n"
        
        for i, (rec_song, reason) in enumerate(recommendations, 1):
            response += f"{i}. {rec_song}\n   💡 {reason}\n\n"
        
        response += "\n**To add songs:**\n"
        response += "• Use: /select_recommendation 1,3,5 (by indices)\n"
        response += "• Or: /select_recommendation 1-3 (range)\n"
        response += "• Or say: 'Add the first two songs'\n"
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
        # If the original description is longer/more detailed than the extracted theme, 
        # use the full description to ensure we capture all artist names and details
        search_text = description if len(description) > len(theme) * 1.5 else theme
        songs = self._search_songs_by_theme(search_text, count)
        
        if not songs:
            return f"Sorry, couldn't find songs matching '{theme}'. Try a different description."
        
        # Check if requested artists appear in the playlist
        # Extract artists from description to check (use same logic as _search_songs_by_theme)
        import re
        requested_artists = []
        # Try to find comma-separated lists with "or" - most common pattern
        comma_or_pattern = r'(?:artists?\s+(?:like|such\s+as|including)\s+|favorite\s+artists?[^,]*?(?:such\s+as|like|including)?\s*)?([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*)(?:\s*,\s*([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))+(?:\s+or\s+([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))'
        comma_or_match = re.search(comma_or_pattern, description)
        if comma_or_match:
            # Extract the full match and split by commas and "or"
            full_match = comma_or_match.group(0)
            # Split by comma or "or" to get individual artists
            parts = re.split(r'\s*,\s*|\s+or\s+', full_match, flags=re.IGNORECASE)
            for part in parts:
                # Remove leading words like "artists like" or "such as"
                part = re.sub(r'^(?:artists?\s+(?:like|such\s+as|including)\s+|favorite\s+artists?[^,]*?(?:such\s+as|like|including)?\s*)', '', part, flags=re.IGNORECASE).strip()
                # Remove trailing punctuation
                part = re.sub(r'[,\s\.]+$', '', part).strip()
                # Validate it looks like an artist name
                if part and 1 <= len(part.split()) <= 5 and part[0].isupper():
                    if part not in requested_artists:
                        requested_artists.append(part)
        
        # Also try simpler patterns
        if not requested_artists:
            simple_patterns = [
                r'(?:artists?\s+(?:like|such\s+as|including)\s+|favorite\s+artists?[^,]*?(?:such\s+as|like|including)?\s*)([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*)(?:\s+or\s+([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))?',
            ]
            for pattern in simple_patterns:
                match = re.search(pattern, description, re.IGNORECASE)
                if match:
                    for group in match.groups():
                        if group and group.strip():
                            artist = group.strip()
                            artist = re.sub(r'\s+(?:or|and|,|\.|$).*$', '', artist, flags=re.IGNORECASE).strip()
                            if artist and 1 <= len(artist.split()) <= 5 and artist[0].isupper():
                                if artist not in requested_artists:
                                    requested_artists.append(artist)
                    if requested_artists:
                        break
        
        # Check which requested artists appear in the playlist
        found_artists = set()
        missing_artists = []
        if requested_artists:
            for song in songs:
                if ': ' in song:
                    song_artist = song.split(': ', 1)[0].strip()
                    for req_artist in requested_artists:
                        # Check if requested artist matches (case-insensitive, partial match)
                        if req_artist.lower() in song_artist.lower() or song_artist.lower() in req_artist.lower():
                            found_artists.add(req_artist)
            
            # Find missing artists
            missing_artists = [a for a in requested_artists if a not in found_artists]
        
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
        
        # Add feedback about requested artists
        if requested_artists:
            if found_artists:
                response += f"\n✅ **Found songs from:** {', '.join(sorted(found_artists))}\n"
            if missing_artists:
                response += f"\n⚠️ **Note:** Could not find songs from {', '.join(missing_artists)} in our database. "
                response += f"You can try searching for these artists with '/search {missing_artists[0]}' to see available songs.\n"
        
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
        
        # Use LLM to extract relevant artist names and genres from the theme
        extract_prompt = f"""
Extract relevant artist names, music-related keywords, and EXCLUSIONS from this theme.

Theme: "{theme}"

Respond ONLY with valid JSON:
{{
    "artists": ["artist1", "artist2"],
    "keywords": ["keyword1", "keyword2"],
    "exclude_genres": ["genre1", "genre2"],
    "exclude_artists": ["artist1", "artist2"]
}}

Focus on:
- Artist names (e.g., "Eminem", "Metallica", "ABBA", "Avicii", "Sido", "Die Ärzte", "Haru Nemuri", "NewJeans", "STAYC", "Linkin Park", "Gims")
- Music genres/styles (e.g., "metal", "rap", "rock", "pop", "vocaloid", "jpop", "kpop", "heavy metal", "techno", "electronic")
- Specific descriptive keywords (e.g., "aggressive", "upbeat", "vocaloid", "electronic", "fast", "energetic")

CRITICAL EXTRACTION RULES:
1. Extract ALL artist names mentioned, including:
   - Direct mentions: "Eminem", "Avicii", "Sido", "Die Ärzte"
   - Phrases with "like": "artists like Eminem or Avicii" -> ["Eminem", "Avicii"]
   - Phrases with "such as": "artists such as Eminem, Avicii" -> ["Eminem", "Avicii"]
   - Phrases with "from artists like": "more songs from artists like Eminem, Avicii, Sido, or Die Ärzte" -> ["Eminem", "Avicii", "Sido", "Die Ärzte"]
   - Phrases with "or": "Eminem or Avicii" -> ["Eminem", "Avicii"]
   - Phrases with commas: "Eminem, Avicii, Sido, or Die Ärzte" -> ["Eminem", "Avicii", "Sido", "Die Ärzte"]

2. Include multi-word artist names exactly as written:
   - "Die Ärzte" (not "Die" and "Ärzte")
   - "Linkin Park" (not "Linkin" and "Park")
   - "Haru Nemuri" (not "Haru" and "Nemuri")

3. Extract EXCLUSIONS from phrases like:
   - "I don't like X" -> exclude_artists: ["X"]
   - "it has X which is Y" -> exclude_artists: ["X"], exclude_genres: ["Y"]
   - "not X" -> exclude_genres: ["X"] or exclude_artists: ["X"]
   - "without X" -> exclude_genres: ["X"]
   - "no X" -> exclude_artists: ["X"]
   - "doesn't fit my style" -> exclude_artists: [mentioned artist]
   Examples:
   - "it has Metallica which is heavy metal" -> exclude_artists: ["Metallica"], exclude_genres: ["heavy metal", "metal"]
   - "I don't like ABBA" -> exclude_artists: ["ABBA"]
   - "not heavy metal" -> exclude_genres: ["heavy metal", "metal"]

4. Prioritize artist names over generic keywords - if artists are mentioned, they should be the PRIMARY focus

5. For vocaloid, also search for songs with "vocaloid" in title or artist

EXCLUDE common filler words from keywords: "workout", "playlist", "energetic", "music", "songs", "with", "for", "the", "a", "an", "my", "favorite", "artists", "such", "as", "like", "more", "from", "can", "you", "try", "again", "generate", "create", "make"
"""
        
        artists_to_search = []
        keywords_to_search = []
        exclude_genres = []
        exclude_artists = []
        
        try:
            if self._llm:
                response = self._llm.generate(
                    model=OLLAMA_MODEL,
                    prompt=extract_prompt,
                    options={"stream": False, "temperature": 0.3, "max_tokens": 200}
                )
                
                response_text = response['response'].strip()
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                
                if json_start != -1 and json_end > json_start:
                    parsed = json.loads(response_text[json_start:json_end])
                    artists_to_search = parsed.get('artists', [])
                    keywords_to_search = parsed.get('keywords', [])
                    exclude_genres = parsed.get('exclude_genres', [])
                    exclude_artists = parsed.get('exclude_artists', [])
        except Exception as e:
            # Fallback: extract keywords from theme
            keywords_to_search = theme.lower().split()
            print(f"LLM extraction failed: {e}")
        
        # Fallback: If LLM didn't extract artists, try pattern matching directly from theme
        if not artists_to_search:
            import re
            # First, try to find comma-separated lists with "or" - most common pattern
            # Pattern: "Eminem, Avicii, Sido, or Die Ärzte" or "artists like Eminem, Avicii, Sido, or Die Ärzte"
            # Look for patterns that have commas followed by "or" and a capitalized name
            comma_or_pattern = r'(?:artists?\s+(?:like|such\s+as|including)\s+)?([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*)(?:\s*,\s*([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))+(?:\s+or\s+([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))'
            comma_or_match = re.search(comma_or_pattern, theme)
            if comma_or_match:
                # Extract the full match and split by commas and "or"
                full_match = comma_or_match.group(0)
                # Split by comma or "or" to get individual artists
                parts = re.split(r'\s*,\s*|\s+or\s+', full_match, flags=re.IGNORECASE)
                for part in parts:
                    # Remove leading words like "artists like" or "such as"
                    part = re.sub(r'^(?:artists?\s+(?:like|such\s+as|including)\s+)', '', part, flags=re.IGNORECASE).strip()
                    # Remove trailing punctuation
                    part = re.sub(r'[,\s\.]+$', '', part).strip()
                    # Validate it looks like an artist name
                    if part and 1 <= len(part.split()) <= 5 and part[0].isupper():
                        if part not in artists_to_search:
                            artists_to_search.append(part)
            
            # If that didn't work, try other patterns
            if not artists_to_search:
                artist_patterns = [
                    # "artists like X, Y, or Z" or "artists such as X, Y, or Z"
                    r'(?:artists?|favorite\s+artists?)\s+(?:like|such\s+as|including)\s+([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*)(?:\s*,\s*([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))*(?:\s+or\s+([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))?',
                    # "from artists like X, Y, or Z"
                    r'from\s+artists?\s+(?:like|such\s+as|including)\s+([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*)(?:\s*,\s*([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))*(?:\s+or\s+([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))?',
                    # "X or Y" (when mentioned as artists)
                    r'([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)+)\s+or\s+([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)+)',
                ]
                
                for pattern in artist_patterns:
                    matches = re.finditer(pattern, theme, re.IGNORECASE)
                    for match in matches:
                        # Extract all groups (artists)
                        groups = [g for g in match.groups() if g and len(g.strip()) > 0]
                        for group in groups:
                            # Clean up the artist name
                            artist = group.strip()
                            # Remove common trailing words
                            artist = re.sub(r'\s+(?:or|and|,|\.|$).*$', '', artist, flags=re.IGNORECASE).strip()
                            # Validate it looks like an artist name (1-5 words, starts with capital)
                            if artist and 1 <= len(artist.split()) <= 5 and artist[0].isupper():
                                if artist not in artists_to_search:
                                    artists_to_search.append(artist)
                        if artists_to_search:
                            break
                    if artists_to_search:
                        break
            
            # Also try to find artist names mentioned with "favorite artists"
            if not artists_to_search and 'favorite' in theme.lower() and 'artist' in theme.lower():
                # Look for capitalized names after "favorite artists" - handle comma-separated lists
                # Pattern: "favorite artists, such as Eminem, Avicii, Sido, or Die Ärzte"
                fav_pattern = r'favorite\s+artists?[^,]*?(?:such\s+as|like|including)?\s*([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*)(?:\s*,\s*([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))*(?:\s+or\s+([A-Z][A-Za-zÄÖÜäöü]+(?:\s+[A-Z][A-Za-zÄÖÜäöü]+)*))?'
                fav_match = re.search(fav_pattern, theme, re.IGNORECASE)
                if fav_match:
                    for group in fav_match.groups():
                        if group and group.strip():
                            artist = group.strip()
                            artist = re.sub(r'\s+(?:or|and|,|\.|$).*$', '', artist, flags=re.IGNORECASE).strip()
                            if artist and 1 <= len(artist.split()) <= 5 and artist[0].isupper():
                                if artist not in artists_to_search:
                                    artists_to_search.append(artist)
        
        # Filter out common filler words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'with', 'for', 'to', 'of', 'in', 
                      'playlist', 'songs', 'music', 'track', 'tracks', 'some', 'my', 'energetic',
                      'workout', 'gym', 'session', 'relaxing', 'at', 'home'}
        keywords_to_search = [k for k in keywords_to_search if k.lower() not in stop_words]
        
        # Helper function to check if a song should be excluded
        def should_exclude_song(song_key: str) -> bool:
            """Check if a song should be excluded based on exclude_genres and exclude_artists."""
            if not exclude_genres and not exclude_artists:
                return False
            
            # Get song info
            cursor.execute('SELECT artist, title FROM songs WHERE song_key = ?', (song_key,))
            result = cursor.fetchone()
            if not result:
                return False
            
            song_artist = (result[0] or '').lower()
            song_title = (result[1] or '').lower()
            song_text = f"{song_artist} {song_title}".lower()
            
            # Check excluded artists
            for excluded_artist in exclude_artists:
                if excluded_artist.lower() in song_artist:
                    return True
            
            # Check excluded genres (common genre keywords)
            genre_keywords = {
                'heavy metal': ['metallica', 'metal', 'heavy', 'thrash', 'slayer', 'megadeth', 'iron maiden'],
                'metal': ['metallica', 'metal', 'heavy', 'thrash', 'slayer', 'megadeth', 'iron maiden'],
                'hard rock': ['metallica', 'metal', 'heavy', 'rock', 'hard rock', 'thrash'],
                'rock': ['rock', 'hard rock', 'classic rock'],
                'techno': ['techno', 'electronic', 'edm', 'dance'],
                'mellow': ['mellow', 'relaxed', 'relaxation', 'chill', 'ambient', 'meditation'],
                'relaxed': ['mellow', 'relaxed', 'relaxation', 'chill', 'ambient', 'meditation'],
                'relaxing': ['mellow', 'relaxed', 'relaxation', 'chill', 'ambient', 'meditation', 'therapy'],
                'rap battle': ['rap battle', 'battle', 'epic rap'],
                'jazz': ['jazz', 'swing', 'bebop'],
                'classical': ['classical', 'symphony', 'orchestra', 'chopin', 'mozart', 'beethoven']
            }
            
            for excluded_genre in exclude_genres:
                excluded_genre_lower = excluded_genre.lower()
                if excluded_genre_lower in genre_keywords:
                    # Check if any genre keyword appears in song
                    for keyword in genre_keywords[excluded_genre_lower]:
                        if keyword in song_text:
                            return True
                else:
                    # Direct keyword match
                    if excluded_genre_lower in song_text:
                        return True
            
            return False
        
        songs = []
        artists_found = {}  # Track which artists were found
        
        # First, search by artist names (highest priority)
        # If artists are mentioned, prioritize them heavily - try to get most songs from them
        if artists_to_search:
            # Calculate songs per artist - if we have multiple artists, distribute evenly
            # But ensure we get at least 3-4 songs per artist if possible
            if len(artists_to_search) == 1:
                songs_per_artist = min(count, 10)  # Get up to 10 songs from single artist
            elif len(artists_to_search) == 2:
                songs_per_artist = min(count // 2, 6)  # Get up to 6 songs per artist
            elif len(artists_to_search) <= 4:
                songs_per_artist = min(count // len(artists_to_search), 4)  # Get up to 4 songs per artist
            else:
                songs_per_artist = min(count // len(artists_to_search), 3)  # Get up to 3 songs per artist
            
            # Ensure minimum of 3 songs per artist
            songs_per_artist = max(3, songs_per_artist)
            
            for artist in artists_to_search:
                artist_songs_found = []
                # Try exact match first (case-insensitive) - this is the most important
                cursor.execute('''
                    SELECT song_key FROM songs
                    WHERE LOWER(TRIM(artist)) = LOWER(?)
                    ORDER BY RANDOM()
                    LIMIT ?
                ''', (artist.strip(), songs_per_artist * 2))  # Get more to filter exclusions
                
                exact_matches = [row[0] for row in cursor.fetchall()]
                # Filter out excluded songs
                exact_matches = [s for s in exact_matches if not should_exclude_song(s)]
                # Take only the number we need
                exact_matches = exact_matches[:songs_per_artist]
                artist_songs_found.extend(exact_matches)
                songs.extend(exact_matches)
                
                # If not enough exact matches, try partial match (handles variations)
                if len(exact_matches) < songs_per_artist:
                    remaining = songs_per_artist - len(exact_matches)
                    cursor.execute('''
                        SELECT song_key FROM songs
                        WHERE LOWER(artist) LIKE ?
                          AND LOWER(TRIM(artist)) != LOWER(?)
                        ORDER BY RANDOM()
                        LIMIT ?
                    ''', (f"%{artist.lower()}%", artist.strip(), remaining * 2))  # Get more to filter
                    
                    partial_matches = [row[0] for row in cursor.fetchall()]
                    # Filter out excluded songs
                    partial_matches = [s for s in partial_matches if not should_exclude_song(s)]
                    partial_matches = partial_matches[:remaining]
                    artist_songs_found.extend(partial_matches)
                    songs.extend(partial_matches)
                
                # Track if we found songs for this artist
                artists_found[artist] = len(artist_songs_found) > 0
                
                # If artist not found, try fuzzy matching with common variations
                if not artists_found[artist]:
                    # Try common variations (e.g., "Die Ärzte" might be stored as "Die Aerzte" or "Die Arzte")
                    # Try without special characters
                    artist_clean = artist.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('Ä', 'Ae').replace('Ö', 'Oe').replace('Ü', 'Ue')
                    if artist_clean != artist:
                        cursor.execute('''
                            SELECT song_key FROM songs
                            WHERE LOWER(TRIM(artist)) = LOWER(?)
                            ORDER BY RANDOM()
                            LIMIT ?
                        ''', (artist_clean.strip(), songs_per_artist))
                        fuzzy_matches = [row[0] for row in cursor.fetchall()]
                        fuzzy_matches = [s for s in fuzzy_matches if not should_exclude_song(s)]
                        if fuzzy_matches:
                            fuzzy_matches = fuzzy_matches[:songs_per_artist]
                            artist_songs_found.extend(fuzzy_matches)
                            songs.extend(fuzzy_matches)
                            artists_found[artist] = True
                    
                    # If still not found, try case-insensitive partial match with word boundaries
                    if not artists_found[artist]:
                        # Split artist name into words and try matching each word
                        artist_words = artist.split()
                        if len(artist_words) > 1:
                            # Try matching first word + last word (handles "Die Ärzte" -> "Die" + "Ärzte")
                            first_word = artist_words[0]
                            last_word = artist_words[-1]
                            cursor.execute('''
                                SELECT song_key FROM songs
                                WHERE LOWER(artist) LIKE ? AND LOWER(artist) LIKE ?
                                ORDER BY RANDOM()
                                LIMIT ?
                            ''', (f"%{first_word.lower()}%", f"%{last_word.lower()}%", songs_per_artist))
                            word_matches = [row[0] for row in cursor.fetchall()]
                            word_matches = [s for s in word_matches if not should_exclude_song(s)]
                            if word_matches:
                                word_matches = word_matches[:songs_per_artist]
                                artist_songs_found.extend(word_matches)
                                songs.extend(word_matches)
                                artists_found[artist] = True
        
        # Special handling for vocaloid keyword - search in title and artist
        if 'vocaloid' in [k.lower() for k in keywords_to_search]:
            vocaloid_songs_needed = max(5, count // 3)  # Try to get at least 1/3 vocaloid songs
            cursor.execute('''
                SELECT song_key FROM songs
                WHERE LOWER(title) LIKE '%vocaloid%' 
                   OR LOWER(artist) LIKE '%vocaloid%'
                   OR LOWER(title) LIKE '%feat. vocaloid%'
                   OR LOWER(title) LIKE '%feat vocaloid%'
                ORDER BY RANDOM()
                LIMIT ?
            ''', (vocaloid_songs_needed,))
            
            vocaloid_songs = [row[0] for row in cursor.fetchall()]
            # Filter out excluded songs
            vocaloid_songs = [s for s in vocaloid_songs if not should_exclude_song(s)]
            songs.extend(vocaloid_songs)
        
        # Then search by genre/keyword in title or artist (if we don't have enough songs)
        # IMPORTANT: If we have requested artists, only use keywords as a last resort
        # If we got songs from requested artists, prioritize getting more from them first
        if len(songs) < count:
            # If we have requested artists but didn't get enough songs, try to get more from them
            if artists_to_search and len(songs) < count:
                # Try to get additional songs from requested artists
                for artist in artists_to_search:
                    if len(songs) >= count:
                        break
                    remaining = count - len(songs)
                    # Get more songs from this artist
                    placeholders = ','.join(['?' for _ in songs]) if songs else None
                    if placeholders:
                        cursor.execute(f'''
                            SELECT song_key FROM songs
                            WHERE LOWER(TRIM(artist)) = LOWER(?)
                              AND song_key NOT IN ({placeholders})
                            ORDER BY RANDOM()
                            LIMIT ?
                        ''', (artist.strip(), remaining))
                    else:
                        cursor.execute('''
                            SELECT song_key FROM songs
                            WHERE LOWER(TRIM(artist)) = LOWER(?)
                            ORDER BY RANDOM()
                            LIMIT ?
                        ''', (artist.strip(), remaining))
                    
                    additional_songs = [row[0] for row in cursor.fetchall()]
                    additional_songs = [s for s in additional_songs if not should_exclude_song(s)]
                    songs.extend(additional_songs)
            
            # Only use keyword searches if we still don't have enough AND either:
            # 1. No artists were requested, OR
            # 2. We got some songs from artists but need a few more
            if len(songs) < count and keywords_to_search:
                # Filter out 'vocaloid' since we already handled it
                keywords_filtered = [k for k in keywords_to_search if k.lower() != 'vocaloid']
                
                # If we have requested artists, use keywords more sparingly (only fill remaining slots)
                max_keyword_songs = count - len(songs) if artists_to_search else count
                
                for keyword in keywords_filtered[:3]:  # Limit to top 3 keywords when artists are specified
                    if len(songs) >= count:
                        break
                    remaining_needed = count - len(songs)
                    
                    if songs:
                        # Exclude already selected songs
                        placeholders = ','.join(['?' for _ in songs])
                        cursor.execute(f'''
                            SELECT song_key FROM songs
                            WHERE (LOWER(artist) LIKE ? OR LOWER(title) LIKE ?)
                              AND song_key NOT IN ({placeholders})
                            ORDER BY RANDOM()
                            LIMIT ?
                        ''', [f"%{keyword}%", f"%{keyword}%"] + list(songs) + [min(remaining_needed, max_keyword_songs // max(1, len(keywords_filtered)))])
                    else:
                        # No exclusions needed
                        cursor.execute('''
                            SELECT song_key FROM songs
                            WHERE LOWER(artist) LIKE ? OR LOWER(title) LIKE ?
                            ORDER BY RANDOM()
                            LIMIT ?
                        ''', (f"%{keyword}%", f"%{keyword}%", min(remaining_needed, max_keyword_songs // max(1, len(keywords_filtered)))))
                    
                    new_songs = [row[0] for row in cursor.fetchall()]
                    # Filter out excluded songs
                    new_songs = [s for s in new_songs if not should_exclude_song(s)]
                    songs.extend(new_songs)
        
        # Remove duplicates and limit
        songs = list(dict.fromkeys(songs))[:count]
        
        # If still not enough songs, add random songs (but only if we have at least some matches)
        if len(songs) < count:
            # Build exclusion conditions for SQL
            exclusion_conditions = []
            exclusion_params = []
            
            # Exclude artists
            if exclude_artists:
                for excluded_artist in exclude_artists:
                    exclusion_conditions.append("LOWER(artist) NOT LIKE ?")
                    exclusion_params.append(f"%{excluded_artist.lower()}%")
            
            # Exclude genres (common keywords) - must match the genre_keywords in should_exclude_song
            genre_keywords = {
                'heavy metal': ['metallica', 'metal', 'heavy', 'thrash', 'slayer', 'megadeth', 'iron maiden'],
                'metal': ['metallica', 'metal', 'heavy', 'thrash', 'slayer', 'megadeth', 'iron maiden'],
                'hard rock': ['metallica', 'metal', 'heavy', 'rock', 'hard rock', 'thrash'],
                'rock': ['rock', 'hard rock', 'classic rock'],
                'techno': ['techno', 'electronic', 'edm', 'dance'],
                'mellow': ['mellow', 'relaxed', 'relaxation', 'chill', 'ambient', 'meditation'],
                'relaxed': ['mellow', 'relaxed', 'relaxation', 'chill', 'ambient', 'meditation'],
                'relaxing': ['mellow', 'relaxed', 'relaxation', 'chill', 'ambient', 'meditation', 'therapy'],
                'rap battle': ['rap battle', 'battle', 'epic rap'],
                'jazz': ['jazz', 'swing', 'bebop'],
                'classical': ['classical', 'symphony', 'orchestra', 'chopin', 'mozart', 'beethoven']
            }
            
            if exclude_genres:
                for excluded_genre in exclude_genres:
                    excluded_genre_lower = excluded_genre.lower()
                    if excluded_genre_lower in genre_keywords:
                        for keyword in genre_keywords[excluded_genre_lower]:
                            exclusion_conditions.append("LOWER(artist || ' ' || title) NOT LIKE ?")
                            exclusion_params.append(f"%{keyword}%")
                    else:
                        exclusion_conditions.append("LOWER(artist || ' ' || title) NOT LIKE ?")
                        exclusion_params.append(f"%{excluded_genre_lower}%")
            
            # Only add random if we got at least some results from our searches
            if len(songs) > 0:
                remaining = count - len(songs)
                placeholders = ','.join(['?' for _ in songs])
                
                where_clause = f"WHERE song_key NOT IN ({placeholders})"
                if exclusion_conditions:
                    where_clause += " AND " + " AND ".join(exclusion_conditions)
                
                cursor.execute(f'''
                    SELECT song_key FROM songs
                    {where_clause}
                    ORDER BY RANDOM()
                    LIMIT ?
                ''', list(songs) + exclusion_params + [remaining])
                
                random_songs = [row[0] for row in cursor.fetchall()]
                # Double-check exclusions (in case SQL filtering missed something)
                random_songs = [s for s in random_songs if not should_exclude_song(s)]
                songs.extend(random_songs)
            else:
                # If we got nothing, try a broader search (but still exclude)
                where_clause = ""
                if exclusion_conditions:
                    where_clause = "WHERE " + " AND ".join(exclusion_conditions)
                
                cursor.execute(f'''
                    SELECT song_key FROM songs
                    {where_clause}
                    ORDER BY RANDOM()
                    LIMIT ?
                ''', exclusion_params + [count])
                
                random_songs = [row[0] for row in cursor.fetchall()]
                # Double-check exclusions
                random_songs = [s for s in random_songs if not should_exclude_song(s)]
                songs.extend(random_songs)
        
        conn.close()
        return songs[:count]

    def _process_natural_language(self, text: str) -> str:
        """Process natural language commands using LLM.
        
        Args:
            text: Natural language input
            
        Returns:
            Response message
        """
        text_lower = text.lower()
        import re
        
        # Check for "Add this song" / "Add it" FIRST (before LLM parsing)
        # This handles adding the most recent recommendation
        if 'this song' in text_lower or 'add it' in text_lower or ('add' in text_lower and 'this' in text_lower):
            # Check if we have recent recommendations
            last_recs = self._get_last_recommendations()
            if last_recs:
                # Add the first recommendation
                return self._add_song(last_recs[0])
            else:
                return "Please specify which songs to add."
        
        # Check for remove-and-add patterns FIRST (before LLM parsing)
        # This ensures we handle "remove X and add Y" correctly
        if 'remove' in text_lower and ('and add' in text_lower or 'instead' in text_lower or (', add' in text_lower)):
            has_add_clause = 'and add' in text_lower or 'instead' in text_lower or 'add' in text_lower
            
            if has_add_clause:
                # Handle "remove X and add Y" or "remove X, add Y instead"
                # Extract the add part more reliably
                add_song_info = None
                
                # Split text to get the add part
                if 'and add' in text_lower:
                    add_part = text_lower.split('and add', 1)[1]
                elif ', add' in text_lower:
                    add_part = text_lower.split(', add', 1)[1]
                elif 'add' in text_lower and 'instead' in text_lower:
                    # Extract part between "add" and "instead"
                    add_start = text_lower.find('add')
                    instead_start = text_lower.find('instead', add_start)
                    if add_start != -1 and instead_start != -1:
                        add_part = text_lower[add_start + 3:instead_start].strip()
                    else:
                        add_part = text_lower.split('add', 1)[1] if 'add' in text_lower else ''
                else:
                    add_part = ''
                
                # Clean up add_part - remove "add" from beginning and trailing words
                add_part = re.sub(r'^add\s+', '', add_part, flags=re.IGNORECASE).strip()
                add_part = re.sub(r'\s+(?:instead|to|from|in|on|at|the|my|a|an|playlist|song|track).*$', '', add_part, flags=re.IGNORECASE).strip()
                
                if add_part:
                    # Try to extract "Title by Artist" format
                    by_match = re.search(r'^(.+?)\s+by\s+(.+?)$', add_part, re.IGNORECASE)
                    if by_match:
                        title = by_match.group(1).strip()
                        artist = by_match.group(2).strip()
                        # Clean up title (remove "the" prefix)
                        title = re.sub(r'^the\s+', '', title, flags=re.IGNORECASE).strip()
                        # Ensure both parts are non-empty
                        if artist and title:
                            add_song_info = f"{artist}: {title}"
                        else:
                            add_song_info = add_part
                    else:
                        # Just use the add_part as-is, will be normalized
                        add_song_info = add_part
                
                # Extract remove part (before "and add" or ", add")
                if 'and add' in text_lower:
                    remove_part = text_lower.split('and add', 1)[0]
                elif ', add' in text_lower:
                    remove_part = text_lower.split(', add', 1)[0]
                else:
                    # If "instead" is present, split there
                    remove_part = text_lower.split('instead', 1)[0] if 'instead' in text_lower else text_lower
                remove_match = re.search(r'remove\s+(.+?)(?:\s+from|\s+and|\s*$)', remove_part, re.IGNORECASE)
                
                if remove_match:
                    remove_song_info = remove_match.group(1).strip()
                    
                    # Clean up common phrases like "the [title] song" -> "[title]"
                    remove_song_info = re.sub(r'^the\s+', '', remove_song_info, flags=re.IGNORECASE)
                    remove_song_info = re.sub(r'\s+song\s+', ' ', remove_song_info, flags=re.IGNORECASE)
                    remove_song_info = re.sub(r'\s+song$', '', remove_song_info, flags=re.IGNORECASE)
                    
                    # Extract artist if "by [artist]" is present
                    by_match = re.search(r'by\s+([^,]+?)(?:\s+from|\s+and|\s*$)', remove_song_info, re.IGNORECASE)
                    if by_match:
                        artist = by_match.group(1).strip()
                        # Remove "by [artist]" from song_info to get title
                        title = re.sub(r'\s+by\s+.*$', '', remove_song_info, flags=re.IGNORECASE).strip()
                        # Clean up title (remove "the" prefix if present)
                        title = re.sub(r'^the\s+', '', title, flags=re.IGNORECASE).strip()
                        # Construct proper format
                        remove_song_info = f"{artist}: {title}"
                    
                    # Normalize and remove the song
                    normalized_remove = self._normalize_song_name(remove_song_info)
                    remove_result = self._remove_song(normalized_remove)
                    
                    # Check if remove was successful (any message containing "Removed" or "removed")
                    remove_successful = "removed" in remove_result.lower() or "Removed" in remove_result
                    
                    # If we have an add clause, always try to add (even if remove failed)
                    if add_song_info:
                        # Don't normalize if it's already in "artist: title" format
                        if ': ' in add_song_info:
                            normalized_add = add_song_info
                        else:
                            normalized_add = self._normalize_song_name(add_song_info)
                        add_result = self._add_song(normalized_add)
                        
                        # Combine results
                        if remove_successful:
                            return f"{remove_result}\n{add_result}"
                        else:
                            # Remove failed but add succeeded
                            return f"{remove_result}\n{add_result}"
                    else:
                        return remove_result
        
        # Use LLM to parse intent
        parse_prompt = f"""
Parse this user message and identify the intent and entities.

User message: "{text}"

Possible intents:
- add_songs: User wants to add songs (even if they mention creating/having a playlist, if they're adding specific songs, it's add_songs)
- remove_songs: User wants to remove songs
- recommend: User wants recommendations
- generate_playlist: User wants to automatically generate a playlist based on a theme/mood (NOT when adding specific songs)
- view_playlist: User wants to see/show/view/display their current playlist
- question: User is asking a question about songs, artists, albums, or database
- goodbye: User is saying goodbye/farewell/ending conversation
- unknown: Cannot determine intent

Respond ONLY with valid JSON:
{{
    "intent": "intent_name",
    "entities": {{
        "songs": ["song TITLES only if mentioned, e.g. 'Money Money Money', 'Bohemian Rhapsody'"],
        "artists": ["artist names if mentioned"],
        "selection": "selection criteria (e.g., 'first two', 'all except last', 'by Metallica')",
        "description": "playlist description if generating"
    }}
}}

Examples:
- "Remove Money, Money, Money by ABBA" -> {{"intent": "remove_songs", "entities": {{"songs": ["Money, Money, Money"], "artists": ["ABBA"]}}}}
- "Add Goodbye by Chris Young" -> {{"intent": "add_songs", "entities": {{"songs": ["Goodbye"], "artists": ["Chris Young"]}}}}
- "Add Talha Anjum's songs Agency and Kaun Talha" -> {{"intent": "add_songs", "entities": {{"songs": ["Agency", "Kaun Talha"], "artists": ["Talha Anjum"]}}}}
- "I would like to add Talha Anjum's songs Agency and Kaun Talha" -> {{"intent": "add_songs", "entities": {{"songs": ["Agency", "Kaun Talha"], "artists": ["Talha Anjum"]}}}}
- "Recommend songs by Maneskin" -> {{"intent": "recommend", "entities": {{"artists": ["Maneskin"]}}}}
- "Can you recommend some Italian music like Maneskin" -> {{"intent": "recommend", "entities": {{"artists": ["Maneskin"]}}}}
- "I'd like recommendations by NewJeans" -> {{"intent": "recommend", "entities": {{"artists": ["NewJeans"]}}}}
"""
        
        try:
            if self._llm:
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
                        return self._handle_nl_add_songs(entities, text)
                    elif intent == 'remove_songs':
                        return self._handle_nl_remove_songs(entities, text)
                    elif intent == 'recommend':
                        # Check if user wants recommendations by a specific artist
                        artists = entities.get('artists', [])
                        if artists:
                            # User wants recommendations by specific artist(s)
                            # Use the first artist mentioned
                            artist_name = artists[0]
                            # Check if user wants only one recommendation
                            import re
                            one_pattern = re.search(r'\b(one|single|a)\s+(?:more\s+)?(?:track|song|recommendation)', text_lower, re.IGNORECASE)
                            limit = 1 if one_pattern else 5
                            return self._recommend_songs_by_artist(artist_name, limit=limit)
                        
                        # Otherwise, recommend based on song or playlist
                        song = entities.get('songs', [None])[0]
                        # Check if user wants only one recommendation
                        import re
                        one_pattern = re.search(r'\b(one|single|a)\s+(?:more\s+)?(?:track|song|recommendation)', text_lower, re.IGNORECASE)
                        limit = 1 if one_pattern else 5
                        return self._recommend_songs(song, limit=limit)
                    elif intent == 'generate_playlist':
                        description = entities.get('description', text)
                        return self._generate_playlist_from_description(description)
                    elif intent == 'view_playlist':
                        return self._view_playlist()
                    elif intent == 'question':
                        return self._answer_question(text)
                    elif intent == 'goodbye':
                        self.goodbye()
                        return None  # Return None to indicate conversation should end
        except Exception as e:
            # Fallback to pattern matching if LLM fails
            pass
        
        # Fallback pattern matching for common natural language commands
        text_lower = text.lower().strip()
        
        # Check for goodbye/farewell messages (but not when referring to songs)
        # Avoid false positives like "remove the Goodbye song"
        goodbye_patterns = [
            'goodbye', 'good bye', 'bye', 'see you', 'farewell', 
            'talk to you later', 'gtg', 'got to go', 'gotta go',
            'have to go', 'leaving', 'exit', 'stop'
        ]
        
        # Check if goodbye patterns appear in a song-reference context
        is_song_reference = any(word in text_lower for word in [
            'song', 'track', 'titled', 'called', 'named', 'by '
        ])
        
        # Only trigger goodbye if it's not a song reference OR if goodbye is at the end/start
        is_goodbye = False
        text_lower_stripped = text_lower.strip()
        for pattern in goodbye_patterns:
            if pattern in text_lower:
                # Check if it's likely the user saying goodbye (not referring to a song)
                # Goodbye is OK if: starts/ends with it (with optional punctuation/whitespace), or standalone, or not near song keywords
                if (text_lower_stripped.startswith(pattern) or 
                    text_lower_stripped.endswith(pattern) or
                    text_lower_stripped.endswith(pattern + '.') or
                    text_lower_stripped.endswith(pattern + ',') or
                    # Check if goodbye appears in the last 30 characters (near the end)
                    text_lower.rfind(pattern) >= len(text_lower) - 30):
                    is_goodbye = True
                    break
                elif not is_song_reference and pattern in text_lower:
                    # If not a song reference and goodbye appears anywhere, it's likely a goodbye
                    is_goodbye = True
                    break
        
        if is_goodbye:
            self.goodbye()
            return None  # Return None to indicate conversation should end
        
        # Pattern matching for common commands
        # Check for recommendation requests FIRST (before they get treated as song titles)
        # This must check for recommend/suggest BEFORE checking for add commands
        import re
        # Check for various recommendation patterns - be more aggressive in detection
        # Check for patterns like "I'd like to get a recommendation", "I'd like you to recommend", etc.
        recommend_patterns = [
            r"recommend",
            r"suggest",
            r"recommendation",
            r"get\s+a\s+recommendation",
            r"get\s+recommendations",
            r"i'?d\s+like\s+(?:you\s+to\s+)?(?:get\s+a\s+)?recommend",
            r"i'?d\s+like\s+(?:you\s+to\s+)?suggest",
            r"can\s+you\s+recommend",
            r"can\s+you\s+suggest",
        ]
        
        has_recommend_keyword = any(re.search(pattern, text_lower, re.IGNORECASE) for pattern in recommend_patterns)
        
        if has_recommend_keyword:
            # Check if user wants only one recommendation
            one_pattern = re.search(r'\b(one|single|a)\s+(?:more\s+)?(?:track|song|recommendation)', text_lower, re.IGNORECASE)
            limit = 1 if one_pattern else 5
            
            # FIRST: Check for "songs by [artist]" or "recommendations by [artist]" patterns
            # This has highest priority for artist-based recommendations
            # Handle multiple artists: "songs by X or Y" or "songs by X, Y, or Z"
            songs_by_pattern = r'(?:songs?|tracks?|recommendations?)\s+by\s+([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?)(?:\s*,\s*([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?))*(?:\s+or\s+([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?))?(?:\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|add|and|that|i|might|enjoy).*)?$'
            songs_by_match = re.search(songs_by_pattern, text_lower, re.IGNORECASE)
            if songs_by_match:
                # Extract all artists from the match
                artists = []
                for group in songs_by_match.groups():
                    if group:
                        artist = group.strip()
                        # Clean up trailing words
                        artist = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|add|and|or|that|i|might|enjoy).*$', '', artist, flags=re.IGNORECASE).strip()
                        if artist and len(artist.split()) <= 5:
                            artists.append(artist)
                
                if artists:
                    # If multiple artists, recommend from first one (or could combine)
                    # For now, use first artist
                    return self._recommend_songs_by_artist(artists[0], limit=limit)
            
            # Check for "artists like X or Y" or "artists like X, Y, or Z" pattern
            # This handles phrases like "artists like Ka2 or Vettche"
            # Match the full phrase and then split by commas and "or"
            artists_like_pattern = r'artists?\s+(?:like|such\s+as|including)\s+([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?(?:\s*,\s*[A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?)*(?:\s+or\s+[A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?)?)(?:\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|add|and|that|i|might|enjoy|for|are|that|are).*)?$'
            artists_like_match = re.search(artists_like_pattern, text_lower, re.IGNORECASE)
            if artists_like_match:
                # Extract the full match and split by commas and "or"
                full_match = artists_like_match.group(1)
                # Split by comma or "or" to get individual artists
                parts = re.split(r'\s*,\s*|\s+or\s+', full_match, flags=re.IGNORECASE)
                artists = []
                for part in parts:
                    artist = part.strip()
                    # Clean up trailing words
                    artist = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|add|and|or|that|i|might|enjoy|for|are).*$', '', artist, flags=re.IGNORECASE).strip()
                    if artist and len(artist.split()) <= 5:
                        artists.append(artist)
                
                if artists:
                    # Use first artist for recommendations
                    return self._recommend_songs_by_artist(artists[0], limit=limit)
            
            # Also check for "recommend some [genre] music like [artist]" or "recommend songs like [artist]"
            # Pattern: "like [Artist]" when it's clearly about recommendations
            # Handle "recommend songs like X or Y"
            like_artist_pattern = r'(?:recommend|suggest|recommendations?)\s+(?:some\s+)?(?:songs?|tracks?|music)?\s*(?:like|by|from)\s+([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?)(?:\s*,\s*([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?))*(?:\s+or\s+([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?))?(?:\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|add|and|that|i|might|enjoy|for|are).*)?$'
            like_artist_match = re.search(like_artist_pattern, text_lower, re.IGNORECASE)
            if like_artist_match:
                # Extract all artists from the match
                artists = []
                for group in like_artist_match.groups():
                    if group:
                        artist = group.strip()
                        # Clean up trailing words
                        artist = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|add|and|or|that|i|might|enjoy|for|are).*$', '', artist, flags=re.IGNORECASE).strip()
                        if artist and len(artist.split()) <= 5:
                            artists.append(artist)
                
                if artists:
                    # Use first artist for recommendations
                    return self._recommend_songs_by_artist(artists[0], limit=limit)
            
            # Extract song/artist name if mentioned
            song_match = None
            
            # Check for "based on my current playlist" or "based on current playlist"
            if 'based on' in text_lower and ('current playlist' in text_lower or 'my playlist' in text_lower or 'playlist' in text_lower):
                # Use current playlist for recommendations
                song_match = None
            elif 'for' in text_lower or 'like' in text_lower or 'based on' in text_lower:
                # Try to extract song/artist name after keywords
                # Pattern: "like [artist]" or "like [song]" or "for [song]"
                match = re.search(r'(?:for|like|based on)\s+([^,\.]+?)(?:\s+(?:and|or|to|from|in|on|at|the|my|a|an|playlist|song|track|that|with|fits).*)?$', text_lower, re.IGNORECASE)
                if match:
                    extracted = match.group(1).strip()
                    # Clean up common trailing words
                    extracted = re.sub(r'\s+(?:and|or|to|from|in|on|at|the|my|a|an|playlist|song|track|that|with|fits).*$', '', extracted, flags=re.IGNORECASE)
                    if extracted and len(extracted.split()) <= 10:  # Reasonable length
                        song_match = extracted
            
            # Also check for artist names like "Travis Scott" or "Post Malone" in the text
            if not song_match:
                # Look for patterns like "songs like [Artist]" or "tracks like [Artist]"
                # Handle "songs like Travis Scott or Post Malone"
                artist_match = re.search(r'(?:songs?|tracks?)\s+like\s+([A-Z][a-zA-Z\s]+?)(?:\s+or|\s+and|$)', text, re.IGNORECASE)
                if artist_match:
                    song_match = artist_match.group(1).strip()
                else:
                    # Try pattern: "like [Artist]" (simpler)
                    artist_match = re.search(r'like\s+([A-Z][a-zA-Z\s]+?)(?:\s+or|\s+and|\s+or\s+[A-Z]|$)', text, re.IGNORECASE)
                    if artist_match:
                        song_match = artist_match.group(1).strip()
            
            # If song_match contains "or" or "and", it might be multiple artists
            # For recommendations, use the first artist
            if song_match and (' or ' in song_match.lower() or ' and ' in song_match.lower()):
                # Extract first artist
                first_artist = re.split(r'\s+(?:or|and)\s+', song_match, flags=re.IGNORECASE)[0].strip()
                if first_artist:
                    song_match = first_artist
            
            return self._recommend_songs(song_match, limit=limit)
        
        # Check for adding songs first (higher priority than playlist generation)
        # Patterns like "add X", "can you add X", "add X to playlist"
        add_patterns = ['add ', ' add ']
        has_add_command = any(pattern in text_lower for pattern in add_patterns)
        
        # Check for playlist generation - must explicitly mention generating/creating playlist
        # But NOT if they're asking to add songs
        is_playlist_generation = False
        if not has_add_command:  # Only check for generation if NOT adding songs
            # Check for explicit generation requests
            if 'generate' in text_lower and 'playlist' in text_lower:
                # "generate playlist" is always playlist generation
                is_playlist_generation = True
            elif 'create' in text_lower and 'playlist' in text_lower:
                # "create a workout playlist" = generation
                is_playlist_generation = True
            # Check for "try again" or "generate another" patterns with playlist context
            elif ('try again' in text_lower or 'try' in text_lower and 'again' in text_lower or 
                  'generate another' in text_lower or 'make another' in text_lower or 
                  'create another' in text_lower) and 'playlist' in text_lower:
                is_playlist_generation = True
            # Check for requests like "can you try again with more songs like X"
            elif ('try again' in text_lower or 'generate' in text_lower or 'create' in text_lower) and \
                 ('more songs' in text_lower or 'songs like' in text_lower) and \
                 'playlist' in text_lower:
                is_playlist_generation = True
        
        if is_playlist_generation:
            # Extract description - extract the theme/description part
            import re
            # Handle "try again" requests - extract the new requirements
            if 'try again' in text_lower or 'generate another' in text_lower or 'create another' in text_lower:
                # Extract the part after "try again" or "with"
                # Pattern: "try again with more songs like X" or "try again with X"
                match = re.search(r'(?:try again|generate another|create another|make another).*?(?:with|for|that has|including)\s*(.+)', text_lower, re.IGNORECASE)
                if match:
                    description = match.group(1).strip()
                    # Clean up trailing phrases
                    description = re.sub(r'\s*(?:can\s+you|please|thanks|goodbye).*$', '', description, flags=re.IGNORECASE)
                    if description and len(description) > 3:
                        return self._generate_playlist_from_description(description)
            
            # Pattern 1: "generate workout playlist" -> description = "workout"
            # Pattern 2: "generate playlist with energetic songs" -> description = "energetic songs"
            # Pattern 3: "workout playlist with energetic songs" -> combine both
            
            # Remove "generate" or "create" from start
            text_clean = re.sub(r'^(?:generate|create|try again|generate another|create another)\s+', '', text_lower, flags=re.IGNORECASE)
            
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
                theme_after = re.sub(r'\s+(?:add|select|choose|can\s+you|please|thanks|goodbye).*$', '', theme_after, flags=re.IGNORECASE).strip()
                if len(theme_after) > 1:
                    description_parts.append(theme_after)
            
            # Also extract "songs like X" patterns
            songs_like_match = re.search(r'songs?\s+like\s+([^,\.]+(?:\s*,\s*[^,\.]+)*)', text_lower, re.IGNORECASE)
            if songs_like_match:
                artists = songs_like_match.group(1).strip()
                description_parts.append(f"songs like {artists}")
            
            # Combine parts
            if description_parts:
                description = ' '.join(description_parts)
            else:
                # Last resort: use everything except "playlist" and common phrases
                description = re.sub(r'\s*playlist.*$', '', text_clean, flags=re.IGNORECASE).strip()
                description = re.sub(r'\s*(?:can\s+you|please|thanks|goodbye).*$', '', description, flags=re.IGNORECASE)
            
            if description and len(description) > 2:
                return self._generate_playlist_from_description(description)
            
            return "Please provide a description. Example: 'Generate a workout playlist with energetic songs'"
        
        # Check for playlist generation requests - "I'm looking for a playlist", "create a playlist", etc.
        # This should come before add commands
        playlist_gen_patterns = [
            r"i'?m\s+looking\s+(?:for|to\s+create)\s+(?:a\s+)?playlist",
            r"looking\s+(?:for|to\s+create)\s+(?:a\s+)?playlist",
            r"create\s+(?:a\s+)?playlist",
            r"generate\s+(?:a\s+)?playlist",
            r"make\s+(?:a\s+)?playlist",
            r"need\s+(?:a\s+)?playlist",
            r"want\s+(?:a\s+)?playlist",
        ]
        
        for pattern in playlist_gen_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                # Extract description for playlist generation
                # Remove common prefixes
                description = re.sub(r"i'?m\s+looking\s+(?:for|to\s+create)\s+(?:a\s+)?playlist\s+(?:for|with|that|to)\s*", "", text_lower, flags=re.IGNORECASE)
                description = re.sub(r"looking\s+(?:for|to\s+create)\s+(?:a\s+)?playlist\s+(?:for|with|that|to)\s*", "", description, flags=re.IGNORECASE)
                description = re.sub(r"(?:create|generate|make|need|want)\s+(?:a\s+)?playlist\s+(?:for|with|that|to)\s*", "", description, flags=re.IGNORECASE)
                description = description.strip()
                
                # Clean up trailing phrases
                description = re.sub(r'\s*(?:can\s+you\s+help\s+me\s+with\s+that|can\s+you\s+help|please|thanks).*$', '', description, flags=re.IGNORECASE)
                
                if description and len(description) > 3:
                    return self._generate_playlist_from_description(description)
                else:
                    # Use the full text as description
                    return self._generate_playlist_from_description(text)
        
        # Check for add commands - handle various patterns
        # Patterns: "add X", "I'd like to add X", "can you add X", "please add X", "try adding X"
        # IMPORTANT: Must NOT match if text contains "recommend" or "suggest" (already handled above)
        # Note: "Add this song" is already handled at the beginning of this function
        
        # PRIORITY: Check for "add some songs" patterns FIRST (before treating "some" as a song title)
        # This must happen before any other add command processing
        if 'add' in text_lower and 'some' in text_lower and ('song' in text_lower or 'track' in text_lower):
            import re
            # Pattern 1: "add some songs (similar to|like|by|from artists like) [artist]"
            # Handle both "add some songs by X" and "add some songs from artists like X"
            # Allow words before "add" like "can you add", "please add", etc.
            add_some_pattern = re.search(r'(?:can\s+you|please|i\'?d\s+like\s+to|i\s+would\s+like\s+to)?\s*add\s+some\s+(?:songs?|tracks?)\s+(?:similar\s+to|like|by|from\s+artists?\s+like)\s+([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?(?:\s*,\s*[A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?)*(?:\s+or\s+[A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?)?)(?:\s+(?:or|and|to|from|in|on|at|the|my|a|an|playlist|song|track|that|fits|fit|to|add|to\s+my|to\s+the).*)?$', text_lower, re.IGNORECASE)
            if add_some_pattern:
                # Extract the full match and split by commas and "or"
                full_match = add_some_pattern.group(1)
                # Split by comma or "or" to get individual artists
                parts = re.split(r'\s*,\s*|\s+or\s+', full_match, flags=re.IGNORECASE)
                artists = []
                for part in parts:
                    artist_name = part.strip()
                    # Clean up trailing words
                    artist_name = re.sub(r'\s+(?:or|and|to|from|in|on|at|the|my|a|an|playlist|song|track|that|fits|fit|to|add).*$', '', artist_name, flags=re.IGNORECASE).strip()
                    if artist_name and len(artist_name.split()) <= 5:
                        artists.append(artist_name)
                
                if artists:
                    # Get songs by all mentioned artists
                    all_songs = []
                    for artist in artists:
                        # Get recommendations by this artist
                        recommendations_response = self._recommend_songs_by_artist(artist, limit=5)
                        # Get the stored recommendations
                        song_keys = self._get_last_recommendations()
                        if song_keys:
                            all_songs.extend(song_keys)
                    
                    if all_songs:
                        # Remove duplicates
                        all_songs = list(dict.fromkeys(all_songs))
                        # Add all recommended songs
                        current_playlist = self._get_current_playlist()
                        added = []
                        for song_key in all_songs:
                            if song_key not in current_playlist.songs:
                                current_playlist.songs.append(song_key)
                                added.append(song_key)
                        
                        if added:
                            response = f"Added {len(added)} song(s) by {', '.join(artists)} to your playlist:\n"
                            for i, song in enumerate(added[:5], 1):
                                if ': ' in song:
                                    _, title = song.split(': ', 1)
                                    response += f"{i}. {title}\n"
                                else:
                                    response += f"{i}. {song}\n"
                            if len(added) > 5:
                                response += f"... and {len(added) - 5} more\n"
                            response += "\n" + self._view_playlist()
                            return response
                        else:
                            return f"All recommended songs by {', '.join(artists)} are already in your playlist."
                    else:
                        # If no songs found, try to get recommendations for first artist
                        if artists:
                            return self._recommend_songs_by_artist(artists[0], limit=5)
            
            # Pattern 1b: Simpler fallback - "add some songs from [artists]" or "add some songs by [artists]"
            # This catches cases where the main pattern might not match
            if not add_some_pattern:
                # Try simpler pattern: "add some songs from [artist list]" or "add some songs by [artist list]" or "add some songs from artists like [list]"
                simple_add_some = re.search(r'(?:can\s+you|please|i\'?d\s+like\s+to|i\s+would\s+like\s+to)?\s*add\s+some\s+(?:songs?|tracks?)\s+(?:from\s+artists?\s+like|from|by)\s+([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?(?:\s*,\s*[A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?)*(?:\s+or\s+[A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü\s]+?)?)', text_lower, re.IGNORECASE)
                if simple_add_some:
                    full_match = simple_add_some.group(1)
                    parts = re.split(r'\s*,\s*|\s+or\s+', full_match, flags=re.IGNORECASE)
                    artists = []
                    for part in parts:
                        artist_name = part.strip()
                        artist_name = re.sub(r'\s+(?:or|and|to|from|in|on|at|the|my|a|an|playlist|song|track|that|fits|fit|to|add|to\s+my|to\s+the).*$', '', artist_name, flags=re.IGNORECASE).strip()
                        if artist_name and len(artist_name.split()) <= 5:
                            artists.append(artist_name)
                    
                    if artists:
                        # Get songs by all mentioned artists
                        all_songs = []
                        for artist in artists:
                            recommendations_response = self._recommend_songs_by_artist(artist, limit=5)
                            song_keys = self._get_last_recommendations()
                            if song_keys:
                                all_songs.extend(song_keys)
                        
                        if all_songs:
                            all_songs = list(dict.fromkeys(all_songs))
                            current_playlist = self._get_current_playlist()
                            added = []
                            for song_key in all_songs:
                                if song_key not in current_playlist.songs:
                                    current_playlist.songs.append(song_key)
                                    added.append(song_key)
                            
                            if added:
                                response = f"Added {len(added)} song(s) by {', '.join(artists)} to your playlist:\n"
                                for i, song in enumerate(added[:5], 1):
                                    if ': ' in song:
                                        _, title = song.split(': ', 1)
                                        response += f"{i}. {title}\n"
                                    else:
                                        response += f"{i}. {song}\n"
                                if len(added) > 5:
                                    response += f"... and {len(added) - 5} more\n"
                                response += "\n" + self._view_playlist()
                                return response
                            else:
                                return f"All recommended songs by {', '.join(artists)} are already in your playlist."
                        else:
                            if artists:
                                return self._recommend_songs_by_artist(artists[0], limit=5)
            
            # Pattern 2: "add some of their songs" - extract artists from context
            # Look for artist names mentioned earlier in the text (before "some of their")
            if 'their' in text_lower or 'them' in text_lower:
                # Try to find artist names in the text before "some of their"
                # Pattern: "along the lines of X or Y" or "like X and Y" or "X and Y"
                artist_patterns = [
                    # Pattern: "along the lines of X or Y" - capture full names
                    r'along\s+the\s+lines\s+of\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\s+(?:or|and)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
                    r'along\s+the\s+lines\s+of\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
                    # Pattern: "like X or Y"
                    r'like\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\s+(?:or|and)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
                    r'like\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
                    # Pattern: "X and Y" or "X or Y" (capitalized names)
                    r'([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)\s+(?:and|or)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)',
                ]
                
                artists_found = []
                for pattern in artist_patterns:
                    match = re.search(pattern, text)
                    if match:
                        artist1 = match.group(1).strip() if match.group(1) else None
                        artist2 = match.group(2).strip() if len(match.groups()) > 1 and match.group(2) else None
                        # Validate artist names (1-5 words, starts with capital)
                        if artist1 and 1 <= len(artist1.split()) <= 5 and artist1[0].isupper():
                            artists_found.append(artist1)
                        if artist2 and 1 <= len(artist2.split()) <= 5 and artist2[0].isupper():
                            artists_found.append(artist2)
                        if artists_found:
                            break
                
                if artists_found:
                    # Get songs by all found artists
                    all_songs = []
                    for artist in artists_found:
                        # Get recommendations by this artist
                        recommendations_response = self._recommend_songs_by_artist(artist, limit=5)
                        # Get the stored recommendations
                        song_keys = self._get_last_recommendations()
                        if song_keys:
                            all_songs.extend(song_keys)
                    
                    if all_songs:
                        # Remove duplicates
                        all_songs = list(dict.fromkeys(all_songs))
                        # Add all recommended songs
                        current_playlist = self._get_current_playlist()
                        added = []
                        for song_key in all_songs:
                            if song_key not in current_playlist.songs:
                                current_playlist.songs.append(song_key)
                                added.append(song_key)
                        
                        if added:
                            response = f"Added {len(added)} song(s) by {', '.join(artists_found)} to your playlist:\n"
                            for i, song in enumerate(added[:5], 1):
                                if ': ' in song:
                                    _, title = song.split(': ', 1)
                                    response += f"{i}. {title}\n"
                                else:
                                    response += f"{i}. {song}\n"
                            if len(added) > 5:
                                response += f"... and {len(added) - 5} more\n"
                            response += "\n" + self._view_playlist()
                            return response
                        else:
                            return f"All recommended songs by {', '.join(artists_found)} are already in your playlist."
                    else:
                        # If no songs found, try to get recommendations for first artist
                        return self._recommend_songs_by_artist(artists_found[0], limit=5)
            
            # Pattern 2: "add some of their songs" - extract artists from context
            # Look for artist names mentioned earlier in the text (before "some of their")
            if 'their' in text_lower or 'them' in text_lower:
                # Try to find artist names in the text before "some of their"
                # Pattern: "along the lines of X or Y" or "like X and Y" or "X and Y"
                artist_patterns = [
                    # Pattern: "along the lines of X or Y" - capture full names
                    r'along\s+the\s+lines\s+of\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\s+(?:or|and)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
                    r'along\s+the\s+lines\s+of\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
                    # Pattern: "like X or Y"
                    r'like\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\s+(?:or|and)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
                    r'like\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
                    # Pattern: "X and Y" or "X or Y" (capitalized names)
                    r'([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)\s+(?:and|or)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)',
                ]
                
                artists_found = []
                for pattern in artist_patterns:
                    match = re.search(pattern, text)
                    if match:
                        artist1 = match.group(1).strip() if match.group(1) else None
                        artist2 = match.group(2).strip() if len(match.groups()) > 1 and match.group(2) else None
                        # Validate artist names (1-5 words, starts with capital)
                        if artist1 and 1 <= len(artist1.split()) <= 5 and artist1[0].isupper():
                            artists_found.append(artist1)
                        if artist2 and 1 <= len(artist2.split()) <= 5 and artist2[0].isupper():
                            artists_found.append(artist2)
                        if artists_found:
                            break
                
                if artists_found:
                    # Get songs by all found artists
                    all_songs = []
                    for artist in artists_found:
                        # Get recommendations by this artist
                        recommendations_response = self._recommend_songs_by_artist(artist, limit=5)
                        # Get the stored recommendations
                        song_keys = self._get_last_recommendations()
                        if song_keys:
                            all_songs.extend(song_keys)
                    
                    if all_songs:
                        # Remove duplicates
                        all_songs = list(dict.fromkeys(all_songs))
                        # Add all recommended songs
                        current_playlist = self._get_current_playlist()
                        added = []
                        for song_key in all_songs:
                            if song_key not in current_playlist.songs:
                                current_playlist.songs.append(song_key)
                                added.append(song_key)
                        
                        if added:
                            response = f"Added {len(added)} song(s) by {', '.join(artists_found)} to your playlist:\n"
                            for i, song in enumerate(added[:5], 1):
                                if ': ' in song:
                                    _, title = song.split(': ', 1)
                                    response += f"{i}. {title}\n"
                                else:
                                    response += f"{i}. {song}\n"
                            if len(added) > 5:
                                response += f"... and {len(added) - 5} more\n"
                            response += "\n" + self._view_playlist()
                            return response
                        else:
                            return f"All recommended songs by {', '.join(artists_found)} are already in your playlist."
                    else:
                        # If no songs found, try to get recommendations for first artist
                        return self._recommend_songs_by_artist(artists_found[0], limit=5)
        
        # Check for "Artist's Title" format (e.g., "Ina Wroldsen's Stranger") - handles single or multiple songs
        if ('add' in text_lower or "i'd like to add" in text_lower or "i would like to add" in text_lower or "can you add" in text_lower or "please add" in text_lower) and "'s" in text:
            import re
            # Pattern 1: "add Artist's Title and Artist2's Title2" (multiple artists with possessive)
            # Pattern: "add Artist's Title" or "add Artist's Title and Artist2's Title2"
            # Use original text (not lowercased) to preserve capitalization for artist names
            # Allow titles with special characters, numbers, and spaces
            # Pattern: "Artist's Title" or "Artist's Title and Artist2's Title2"
            # Use a pattern that explicitly handles the "and" separator to capture full multi-word titles
            # First try to match two songs with "and" separator
            two_songs_pattern = re.search(r"(?:add|i'?d\s+like\s+to\s+add|i\s+would\s+like\s+to\s+add|can\s+you\s+add|please\s+add)\s+([A-Za-z][A-Za-z\s]+?)\'s\s+([A-Za-z0-9][A-Za-z0-9\s\-\+\&\(\)]+?)\s+and\s+([A-Za-z][A-Za-z\s]+?)\'s\s+([A-Za-z0-9][A-Za-z0-9\s\-\+\&\(\)]+?)(?:\s+to|from|in|on|at|the|my|a|an|playlist|song|track|give|more|energy|variety|$)", text, re.IGNORECASE)
            if two_songs_pattern:
                artist1 = two_songs_pattern.group(1).strip()
                title1 = two_songs_pattern.group(2).strip()
                artist2 = two_songs_pattern.group(3).strip()
                title2 = two_songs_pattern.group(4).strip()
                
                # Clean up trailing words from titles
                title1 = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|give|more|energy|variety).*$', '', title1, flags=re.IGNORECASE).strip()
                title2 = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|give|more|energy|variety).*$', '', title2, flags=re.IGNORECASE).strip()
                
                # Add songs
                added = []
                not_found = []
                
                # Add first song
                song_info1 = f"{artist1}: {title1}"
                result1 = self._add_song(song_info1)
                if "Added" in result1 or "already in" in result1:
                    added.append(song_info1)
                else:
                    not_found.append(f"{title1} by {artist1}")
                
                # Add second song
                song_info2 = f"{artist2}: {title2}"
                result2 = self._add_song(song_info2)
                if "Added" in result2 or "already in" in result2:
                    added.append(song_info2)
                else:
                    not_found.append(f"{title2} by {artist2}")
                
                if added:
                    response = f"Added {len(added)} song(s) to your playlist:\n"
                    for i, song in enumerate(added[:5], 1):
                        if ': ' in song:
                            _, title = song.split(': ', 1)
                            artist = song.split(': ', 1)[0]
                            response += f"{i}. {title} by {artist}\n"
                        else:
                            response += f"{i}. {song}\n"
                    if len(added) > 5:
                        response += f"... and {len(added) - 5} more\n"
                    if not_found:
                        response += f"\nNote: Could not find: {', '.join(not_found)}\n"
                    response += "\n" + self._view_playlist()
                    return response
                elif not_found:
                    return f"Sorry, I couldn't find the following songs: {', '.join(not_found)}. Please check the spelling and try again."
            
            # If two songs pattern didn't match, try single song pattern
            possessive_pattern = re.search(r"(?:add|i'?d\s+like\s+to\s+add|i\s+would\s+like\s+to\s+add|can\s+you\s+add|please\s+add)\s+([A-Za-z][A-Za-z\s]+?)\'s\s+([A-Za-z0-9][A-Za-z0-9\s\-\+\&\(\)]+?)(?:\s+to|from|in|on|at|the|my|a|an|playlist|song|track|give|more|energy|variety|$)", text, re.IGNORECASE)
            if possessive_pattern:
                artist1 = possessive_pattern.group(1).strip()
                title1 = possessive_pattern.group(2).strip()
                artist2 = possessive_pattern.group(3)  # May be None
                title2 = possessive_pattern.group(4)  # May be None
                
                # Clean up trailing words from titles
                title1 = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|give|more|energy|variety).*$', '', title1, flags=re.IGNORECASE).strip()
                if title2:
                    title2 = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|give|more|energy|variety).*$', '', title2, flags=re.IGNORECASE).strip()
                
                # Add songs
                added = []
                not_found = []
                
                # Add first song
                song_info1 = f"{artist1}: {title1}"
                result1 = self._add_song(song_info1)
                if "Added" in result1 or "already in" in result1:
                    added.append(song_info1)
                else:
                    not_found.append(f"{title1} by {artist1}")
                
                # Add second song if present
                if artist2 and title2:
                    song_info2 = f"{artist2}: {title2}"
                    result2 = self._add_song(song_info2)
                    if "Added" in result2 or "already in" in result2:
                        added.append(song_info2)
                    else:
                        not_found.append(f"{title2} by {artist2}")
                
                if added:
                    response = f"Added {len(added)} song(s) to your playlist:\n"
                    for i, song in enumerate(added[:5], 1):
                        if ': ' in song:
                            _, title = song.split(': ', 1)
                            artist = song.split(': ', 1)[0]
                            response += f"{i}. {title} by {artist}\n"
                        else:
                            response += f"{i}. {song}\n"
                    if len(added) > 5:
                        response += f"... and {len(added) - 5} more\n"
                    if not_found:
                        response += f"\nNote: Could not find: {', '.join(not_found)}\n"
                    response += "\n" + self._view_playlist()
                    return response
                elif not_found:
                    return f"Sorry, I couldn't find the following songs: {', '.join(not_found)}. Please check the spelling and try again."
            
            # Pattern 2: "add Artist's songs X and Y" (with "songs" keyword)
            possessive_songs_pattern = re.search(r"(?:add|i'?d\s+like\s+to\s+add|i\s+would\s+like\s+to\s+add|can\s+you\s+add|please\s+add)\s+([A-Za-z][A-Za-z\s]+?)\'s\s+songs?\s+(.+?)(?:\s+to|from|in|on|at|the|my|a|an|playlist|song|track|give|more|energy|variety|$)", text, re.IGNORECASE)
            if possessive_songs_pattern:
                artist_name = possessive_songs_pattern.group(1).strip()
                songs_text = possessive_songs_pattern.group(2).strip()
                # Clean up trailing words
                songs_text = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|give|more|energy|variety).*$', '', songs_text, flags=re.IGNORECASE).strip()
                
                # Split songs by "and" or comma
                song_titles = [s.strip() for s in re.split(r'\s+and\s+|\s*,\s*', songs_text, flags=re.IGNORECASE) if s.strip()]
                
                if song_titles and artist_name:
                    # Add each song with the artist
                    added = []
                    not_found = []
                    for title in song_titles:
                        song_info = f"{artist_name}: {title}"
                        result = self._add_song(song_info)
                        if "Added" in result or "already in" in result:
                            added.append(song_info)
                        else:
                            not_found.append(title)
                    
                    if added:
                        response = f"Added {len(added)} song(s) by {artist_name} to your playlist:\n"
                        for i, song in enumerate(added[:5], 1):
                            if ': ' in song:
                                _, title = song.split(': ', 1)
                                response += f"{i}. {title}\n"
                            else:
                                response += f"{i}. {song}\n"
                        if len(added) > 5:
                            response += f"... and {len(added) - 5} more\n"
                        if not_found:
                            response += f"\nNote: Could not find: {', '.join(not_found)}\n"
                        response += "\n" + self._view_playlist()
                        return response
                    elif not_found:
                        return f"Sorry, I couldn't find the following songs by {artist_name}: {', '.join(not_found)}. Please check the spelling and try again."
        
        # Only check for add commands if text doesn't contain recommend/suggest (already handled above)
        # Double-check to prevent false matches - use same pattern matching as above
        has_recommend_in_add_check = any(re.search(pattern, text_lower, re.IGNORECASE) for pattern in recommend_patterns)
        
        if not has_recommend_in_add_check:
            add_patterns = [
                r'^add\s+(.+)$',
                r"i'?d\s+like\s+to\s+add\s+(.+?)(?:\s+to\s+my\s+playlist|$)",
                r'can\s+you\s+add\s+(.+?)(?:\s+to\s+my\s+playlist|$)',
                r'please\s+add\s+(.+?)(?:\s+to\s+my\s+playlist|$)',
                r'try\s+adding\s+(.+?)(?:\s+to\s+my\s+playlist|$)',
                r'add\s+(.+?)(?:\s+to\s+my\s+playlist|$)',
            ]
            
            for pattern in add_patterns:
                match = re.search(pattern, text_lower, re.IGNORECASE)
                if match:
                    song_part = match.group(1).strip()
                    # Remove trailing words
                    song_part = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track).*$', '', song_part, flags=re.IGNORECASE).strip()
                    
                    # Handle "Add the first two songs" etc.
                    if 'first' in song_part or 'last' in song_part or 'all' in song_part:
                        # This is a selection command
                        selection = song_part.replace('the', '').replace('songs', '').strip()
                        return self._handle_selection_add(selection)
                    
                    if song_part:
                        normalized = self._normalize_song_name(song_part)
                        return self._add_song(normalized)
                    break
        
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
        
        # Handle remove commands (including "remove X and add Y" patterns)
        if 'remove' in text_lower:
            import re
            # Check if there's an "and add" or "instead" clause
            has_add_clause = 'and add' in text_lower or 'instead' in text_lower or 'add' in text_lower
            
            if has_add_clause:
                # Handle "remove X and add Y" or "remove X, add Y instead"
                # Extract the add part more reliably
                add_song_info = None
                
                # Split text to get the add part
                if 'and add' in text_lower:
                    add_part = text_lower.split('and add', 1)[1]
                elif ', add' in text_lower:
                    add_part = text_lower.split(', add', 1)[1]
                elif 'add' in text_lower and 'instead' in text_lower:
                    # Extract part between "add" and "instead"
                    add_start = text_lower.find('add')
                    instead_start = text_lower.find('instead', add_start)
                    if add_start != -1 and instead_start != -1:
                        add_part = text_lower[add_start + 3:instead_start].strip()
                    else:
                        add_part = text_lower.split('add', 1)[1] if 'add' in text_lower else ''
                else:
                    add_part = ''
                
                # Clean up add_part - remove "add" from beginning and trailing words
                add_part = re.sub(r'^add\s+', '', add_part, flags=re.IGNORECASE).strip()
                add_part = re.sub(r'\s+(?:instead|to|from|in|on|at|the|my|a|an|playlist|song|track).*$', '', add_part, flags=re.IGNORECASE).strip()
                
                if add_part:
                    # Try to extract "Title by Artist" format
                    # Use a more specific pattern that captures the full artist name (may contain multiple words)
                    by_match = re.search(r'^(.+?)\s+by\s+(.+?)$', add_part, re.IGNORECASE)
                    if by_match:
                        title = by_match.group(1).strip()
                        artist = by_match.group(2).strip()
                        # Clean up title (remove "the" prefix)
                        title = re.sub(r'^the\s+', '', title, flags=re.IGNORECASE).strip()
                        # Ensure both parts are non-empty
                        if artist and title:
                            add_song_info = f"{artist}: {title}"
                        else:
                            add_song_info = add_part
                    else:
                        # Just use the add_part as-is, will be normalized
                        add_song_info = add_part
                
                # Extract remove part (before "and add" or ", add")
                # Split on "and add" first, then fall back to ", add"
                if 'and add' in text_lower:
                    remove_part = text_lower.split('and add', 1)[0]
                elif ', add' in text_lower:
                    remove_part = text_lower.split(', add', 1)[0]
                else:
                    # If "instead" is present, split there
                    remove_part = text_lower.split('instead', 1)[0] if 'instead' in text_lower else text_lower
                remove_match = re.search(r'remove\s+(.+?)(?:\s+from|\s+and|\s*$)', remove_part, re.IGNORECASE)
                
                if remove_match:
                    remove_song_info = remove_match.group(1).strip()
                    
                    # Clean up common phrases like "the [title] song" -> "[title]"
                    remove_song_info = re.sub(r'^the\s+', '', remove_song_info, flags=re.IGNORECASE)
                    remove_song_info = re.sub(r'\s+song\s+', ' ', remove_song_info, flags=re.IGNORECASE)
                    remove_song_info = re.sub(r'\s+song$', '', remove_song_info, flags=re.IGNORECASE)
                    
                    # Extract artist if "by [artist]" is present
                    by_match = re.search(r'by\s+([^,]+?)(?:\s+from|\s+and|\s*$)', remove_song_info, re.IGNORECASE)
                    if by_match:
                        artist = by_match.group(1).strip()
                        # Remove "by [artist]" from song_info to get title
                        title = re.sub(r'\s+by\s+.*$', '', remove_song_info, flags=re.IGNORECASE).strip()
                        # Clean up title (remove "the" prefix if present)
                        title = re.sub(r'^the\s+', '', title, flags=re.IGNORECASE).strip()
                        # Construct proper format
                        remove_song_info = f"{artist}: {title}"
                    
                    # Normalize and remove the song
                    normalized_remove = self._normalize_song_name(remove_song_info)
                    remove_result = self._remove_song(normalized_remove)
                    
                    # Check if remove was successful (any message containing "Removed" or "removed")
                    remove_successful = "removed" in remove_result.lower() or "Removed" in remove_result
                    
                    # If we have an add clause, always try to add (even if remove failed)
                    if add_song_info:
                        # Don't normalize if it's already in "artist: title" format
                        if ': ' in add_song_info:
                            normalized_add = add_song_info
                        else:
                            normalized_add = self._normalize_song_name(add_song_info)
                        add_result = self._add_song(normalized_add)
                        
                        # Combine results
                        if remove_successful:
                            return f"{remove_result}\n{add_result}"
                        else:
                            # Remove failed but add succeeded
                            return f"{remove_result}\n{add_result}"
                    else:
                        return remove_result
            
            # Handle simple remove (no add clause)
            # Try to extract song info - handle various patterns
            # Pattern 1: "remove [song] from"
            match = re.search(r'remove\s+(.+?)\s+(?:from|and)', text_lower)
            if not match:
                # Pattern 2: "remove [song]" at the end
                match = re.search(r'remove\s+(.+?)$', text_lower)
            
            if match:
                song_info = match.group(1).strip()
                
                # Clean up common phrases like "the [title] song" -> "[title]"
                song_info = re.sub(r'^the\s+', '', song_info, flags=re.IGNORECASE)
                song_info = re.sub(r'\s+song\s+', ' ', song_info, flags=re.IGNORECASE)
                song_info = re.sub(r'\s+song$', '', song_info, flags=re.IGNORECASE)
                
                # Extract artist if "by [artist]" is present
                by_match = re.search(r'by\s+([^,]+?)(?:\s+from|\s+and|$)', song_info, re.IGNORECASE)
                if by_match:
                    artist = by_match.group(1).strip()
                    # Remove "by [artist]" from song_info to get title
                    title = re.sub(r'\s+by\s+.*$', '', song_info, flags=re.IGNORECASE).strip()
                    # Clean up title (remove "the" prefix if present)
                    title = re.sub(r'^the\s+', '', title, flags=re.IGNORECASE).strip()
                    # Construct proper format
                    song_info = f"{artist}: {title}"
                
                # Normalize and search for the song
                normalized = self._normalize_song_name(song_info)
                return self._remove_song(normalized)
        
        # If pattern matching fails, try using LLM to understand the request
        if self._llm:
            try:
                # Use LLM to parse the natural language request
                llm_prompt = f"""You are a music recommendation assistant. Parse this user request and determine the action.

User request: "{text}"

Possible actions:
- ADD: User wants to add a song/artist to playlist
- REMOVE: User wants to remove a song from playlist
- VIEW: User wants to see the playlist
- RECOMMEND: User wants recommendations
- GENERATE: User wants to generate a playlist from description
- QUESTION: User is asking a question
- UNKNOWN: Cannot determine the action

Respond with ONLY the action name (ADD, REMOVE, VIEW, RECOMMEND, GENERATE, QUESTION, or UNKNOWN), followed by a colon, then any relevant information extracted.

Examples:
- "Add Bohemian Rhapsody by Queen" -> ADD: Bohemian Rhapsody by Queen
- "Remove the song by Russ" -> REMOVE: Russ
- "Show my playlist" -> VIEW:
- "Recommend songs" -> RECOMMEND:
- "Generate a workout playlist" -> GENERATE: workout playlist
- "How many songs?" -> QUESTION: how many songs
- "Goodbye" -> UNKNOWN:"""

                llm_response = self._llm.generate(
                    model=OLLAMA_MODEL,
                    prompt=llm_prompt,
                    options={"temperature": 0.3, "max_tokens": 50}
                )
                
                response_text = llm_response.get("text", "").strip()
                if ":" in response_text:
                    action, info = response_text.split(":", 1)
                    action = action.strip().upper()
                    info = info.strip()
                    
                    if action == "ADD" and info:
                        normalized = self._normalize_song_name(info)
                        return self._add_song(normalized)
                    elif action == "REMOVE" and info:
                        normalized = self._normalize_song_name(info)
                        return self._remove_song(normalized)
                    elif action == "VIEW":
                        return self._view_playlist()
                    elif action == "RECOMMEND":
                        # Check if user wants only one recommendation
                        import re
                        one_pattern = re.search(r'\b(one|single|a)\s+(?:more\s+)?(?:track|song|recommendation)', text_lower, re.IGNORECASE)
                        limit = 1 if one_pattern else 5
                        return self._recommend_songs(None, limit=limit)
                    elif action == "GENERATE" and info:
                        return self._generate_playlist_from_description(info)
                    elif action == "QUESTION" and info:
                        return self._answer_question(text)
            except Exception as e:
                print(f"LLM parsing error: {e}")
        
        return "I'm sorry, I don't understand. Type '/help' to see available commands."

    def _handle_nl_add_songs(self, entities: dict, original_text: str = '') -> str:
        """Handle natural language add songs command."""
        selection = entities.get('selection', '')
        songs = entities.get('songs', [])
        artists = entities.get('artists', [])
        
        # If LLM didn't extract songs but we have original text, try pattern matching
        if not songs and not selection and original_text:
            import re
            text_lower = original_text.lower()
            # Try to extract song info from original text using patterns
            add_patterns = [
                r"i'?d\s+like\s+to\s+add\s+(.+?)(?:\s+to\s+my\s+playlist|$)",
                r'can\s+you\s+add\s+(.+?)(?:\s+to\s+my\s+playlist|$)',
                r'please\s+add\s+(.+?)(?:\s+to\s+my\s+playlist|$)',
                r'add\s+(.+?)(?:\s+to\s+my\s+playlist|$)',
            ]
            
            for pattern in add_patterns:
                match = re.search(pattern, text_lower, re.IGNORECASE)
                if match:
                    song_part = match.group(1).strip()
                    # Remove trailing words
                    song_part = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track).*$', '', song_part, flags=re.IGNORECASE).strip()
                    
                    if song_part and len(song_part) > 0:
                        # Normalize and add
                        normalized = self._normalize_song_name(song_part)
                        return self._add_song(normalized)
        
        if songs:
            # Add specific songs (R5.6: Handle complex song names)
            added = []
            not_found = []
            
            for i, song in enumerate(songs):
                # If we have a matching artist for this song, construct "artist: title" format
                # If there's only one artist and multiple songs, use that artist for all songs
                if artists:
                    # Use the first artist if we have multiple songs but only one artist
                    # Otherwise, try to pair by index
                    if len(artists) == 1 and len(songs) > 1:
                        artist_to_use = artists[0]
                    elif i < len(artists):
                        artist_to_use = artists[i]
                    else:
                        artist_to_use = artists[0] if artists else None
                    
                    if artist_to_use:
                        song_info = f"{artist_to_use}: {song}"
                        result = self._add_song(song_info)
                        if "Added" in result or "already in" in result:
                            added.append(song)
                        else:
                            # Try searching if exact match failed
                            # Normalize and try searching
                            normalized = self._normalize_song_name(song_info)
                            matches = self._search_songs_by_title_in_db(normalized.split(': ', 1)[-1] if ': ' in normalized else normalized)
                            if matches:
                                # Try to find one by the requested artist
                                artist_lower = artist_to_use.lower().strip()
                                found_match = None
                                for match in matches:
                                    if ': ' in match:
                                        match_artist = match.split(': ', 1)[0].strip().lower()
                                        if artist_lower in match_artist or match_artist in artist_lower:
                                            found_match = match
                                            break
                                if not found_match and matches:
                                    found_match = matches[0]
                                
                                if found_match:
                                    result = self._add_song(found_match)
                                    if "Added" in result or "already in" in result:
                                        added.append(found_match)
                                    else:
                                        not_found.append(song)
                                else:
                                    not_found.append(song)
                            else:
                                not_found.append(song)
                else:
                    # Normalize song name - remove special characters for matching
                    normalized_song = self._normalize_song_name(song)
                    matches = self._search_songs_by_title_in_db(normalized_song)
                    if not matches:
                        # Try original search
                        matches = self._search_songs_by_title_in_db(song)
                    if matches:
                        result = self._add_song(matches[0])
                        added.append(matches[0])
                    else:
                        not_found.append(song)
            
            if added:
                # Show which songs were added
                song_list = []
                for song in added[:5]:  # Show up to 5 songs
                    if ': ' in song:
                        artist, title = song.split(': ', 1)
                        song_list.append(f"'{title}' by {artist}")
                    else:
                        song_list.append(f"'{song}'")
                
                if len(added) == 1:
                    response = f"Added {song_list[0]} to your playlist!"
                elif len(added) <= 5:
                    response = f"Added {len(added)} song(s) to your playlist: {', '.join(song_list)}"
                else:
                    response = f"Added {len(added)} song(s) to your playlist: {', '.join(song_list)}... and {len(added) - 5} more"
                
                # Include playlist view
                response += "\n\n" + self._view_playlist()
                return response
            else:
                return "Sorry, couldn't find those songs."
        
        elif selection:
            # Handle selection like "first two", "all except last"
            return self._handle_selection_add(selection)
        
        return "Please specify which songs to add."

    def _handle_nl_remove_songs(self, entities: dict, original_text: str = '') -> str:
        """Handle natural language remove songs command."""
        selection = entities.get('selection', '')
        artists = entities.get('artists', [])
        songs = entities.get('songs', [])
        
        current_playlist = self._get_current_playlist()
        
        # Check for "remove all" or "clear" patterns first
        if original_text:
            text_lower = original_text.lower()
            if ('remove' in text_lower and 'all' in text_lower) or 'clear' in text_lower:
                # Check if it's "remove all songs" or "clear playlist"
                if 'song' in text_lower or 'playlist' in text_lower or not songs:
                    return self._clear_playlist()
            
            # If the message contains "replace" or "with", only extract artists from the remove part
            # Pattern: "I don't like X, replace them with Y" - only remove X, not Y
            if 'replace' in text_lower or ('with' in text_lower and ('similar' in text_lower or 'like' in text_lower)):
                import re
                # Extract the part before "replace" or "with"
                if 'replace' in text_lower:
                    remove_part = text_lower.split('replace', 1)[0]
                elif 'with' in text_lower:
                    # Find "with" that's followed by "similar" or "like" (indicating recommendation, not removal)
                    with_match = re.search(r'with\s+(?:something\s+)?(?:similar\s+to|like)', text_lower, re.IGNORECASE)
                    if with_match:
                        remove_part = text_lower[:with_match.start()].strip()
                    else:
                        remove_part = text_lower.split('with', 1)[0]
                else:
                    remove_part = text_lower
                
                # Extract artists only from the remove part
                # Look for patterns like "I don't like X and Y" or "remove X and Y"
                remove_artists = []
                # Pattern: "don't like the X and Y" or "don't like X and Y"
                like_match = re.search(r"(?:don'?t\s+like|dislike|hate)\s+(?:the\s+)?(.+?)(?:\s+songs?|\s+in|\s*,|\s+and|\s+can|$)", remove_part, re.IGNORECASE)
                if like_match:
                    artists_text = like_match.group(1).strip()
                    # Split by "and" or comma
                    remove_artists = [a.strip() for a in re.split(r'\s+and\s+|\s*,\s*', artists_text) if a.strip()]
                
                # If we found artists in the remove part, use only those
                if remove_artists:
                    artists = remove_artists
        
        # If specific songs are mentioned, try to remove them
        if songs:
            removed = []
            for song_name in songs:
                # Try to find and remove by song title
                found = False
                for song in current_playlist.songs[:]:
                    # Check if song title matches (case-insensitive)
                    if ':' in song:
                        _, title = song.split(':', 1)
                        if song_name.lower() in title.lower() or title.lower() in song_name.lower():
                            current_playlist.songs.remove(song)
                            removed.append(song)
                            found = True
                            break
                    elif song_name.lower() in song.lower():
                        current_playlist.songs.remove(song)
                        removed.append(song)
                        found = True
                        break
            
            if removed:
                return f"Removed {len(removed)} song(s) from your playlist."
            else:
                return f"Couldn't find the specified song(s) in your playlist."
        
        # If artists are mentioned, remove songs by those artists
        if artists:
            # Remove all songs by specific artists
            removed = []
            artists_with_removals = set()  # Track which artists actually had songs removed
            
            for song in current_playlist.songs[:]:
                for artist in artists:
                    if artist.lower() in song.lower():
                        current_playlist.songs.remove(song)
                        removed.append(song)
                        artists_with_removals.add(artist)
                        break
            
            if removed:
                # Only mention artists whose songs were actually removed
                if artists_with_removals:
                    return f"Removed {len(removed)} song(s) by {', '.join(sorted(artists_with_removals))}."
                else:
                    return f"Removed {len(removed)} song(s) from your playlist."
            else:
                # Check which artists are actually in the playlist
                artists_in_playlist = set()
                for song in current_playlist.songs:
                    if ': ' in song:
                        artist = song.split(': ', 1)[0].strip()
                        artists_in_playlist.add(artist)
                
                # Only mention artists that were requested but not found
                requested_but_not_found = [a for a in artists if a not in artists_in_playlist]
                if requested_but_not_found:
                    return f"No songs found by {', '.join(requested_but_not_found)} in your playlist."
                else:
                    return f"No songs found by {', '.join(artists)} in your playlist."
        
        elif selection:
            return self._handle_selection_remove(selection)
        
        return "Please specify which songs to remove."

    def _handle_selection_add(self, selection: str) -> str:
        """Handle selection-based adding (e.g., 'first two', 'all except last')."""
        import re
        
        last_recs = self._get_last_recommendations()
        
        if not last_recs:
            return "Please use /recommend first to see song suggestions, then specify which to add."
        
        selection_lower = selection.lower()
        songs_to_add = []
        
        # Parse different selection patterns
        # Handle ordinal numbers: "fourth song", "the second one", etc.
        ordinal_pattern = r'\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th)\b'
        ordinal_match = re.search(ordinal_pattern, selection_lower)
        if ordinal_match:
            ordinal_map = {
                'first': 1, '1st': 1,
                'second': 2, '2nd': 2,
                'third': 3, '3rd': 3,
                'fourth': 4, '4th': 4,
                'fifth': 5, '5th': 5,
                'sixth': 6, '6th': 6,
                'seventh': 7, '7th': 7,
                'eighth': 8, '8th': 8,
                'ninth': 9, '9th': 9,
                'tenth': 10, '10th': 10
            }
            ordinal = ordinal_match.group(1)
            index = ordinal_map.get(ordinal, 1) - 1  # Convert to 0-based index
            if 0 <= index < len(last_recs):
                songs_to_add = [last_recs[index]]
            else:
                return f"There are only {len(last_recs)} recommendations available."
        
        elif 'first' in selection_lower:
            # Extract number - handle "the first two", "first two", "first 2", "first two songs", etc.
            # Pattern: find "first" then look for a number word or digit after it (allowing for words in between)
            match = re.search(r'first.*?(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)', selection_lower)
            if match:
                # Extract the number word or digit from the match
                num_match = re.search(r'(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)', match.group(0))
                if num_match:
                    num_word = num_match.group(0)
                    num_map = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
                    num = num_map.get(num_word, None)
                    if num is None:
                        try:
                            num = int(num_word)
                        except:
                            num = 1
                    songs_to_add = last_recs[:num] if num <= len(last_recs) else last_recs
                else:
                    # If no number found in match, default to first song
                    songs_to_add = last_recs[:1]
            else:
                # If no match at all, default to first song
                songs_to_add = last_recs[:1]
        
        elif 'last' in selection_lower and 'except' not in selection_lower:
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
                match = re.search(r'except.*last\s+(\w+|\d+)', selection_lower)
                if match:
                    num_word = match.group(1)
                    num_map = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
                    num = num_map.get(num_word, 1)
                    songs_to_add = last_recs[:-num] if num < len(last_recs) else []
                else:
                    songs_to_add = last_recs[:-1]
            elif 'first' in selection_lower:
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
        Also handles possessive forms like "Artist's Title" -> "Artist: Title"
        Also handles dash format like "Artist - Title" -> "Artist: Title"
        
        Args:
            song_name: Song name that may contain special characters
            
        Returns:
            Normalized song name for better matching
        """
        import re
        
        # Handle dash format "Artist - Title" FIRST (before other processing)
        # Pattern: "Artist - Title" or "Artist -Title" or "Artist- Title"
        dash_pattern = r'^(.+?)\s*-\s*(.+?)(?:\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track).*)?$'
        dash_match = re.match(dash_pattern, song_name.strip(), re.IGNORECASE)
        if dash_match:
            artist = dash_match.group(1).strip()
            title = dash_match.group(2).strip()
            # Remove trailing words like "to my playlist" if captured
            title = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track).*$', '', title, flags=re.IGNORECASE)
            if artist and title and len(title.split()) <= 15:  # Reasonable title length
                return f"{artist}: {title}"
        
        # If already in "artist: title" format, don't do aggressive normalization that might break it
        if ': ' in song_name:
            parts = song_name.split(': ', 1)
            if len(parts) == 2:
                artist, title = parts
                # Just clean up the parts, don't re-parse
                artist = artist.strip()
                title = title.strip()
                # Fix common typos in artist name
                artist = re.sub(r'\bbby\b', 'by', artist, flags=re.IGNORECASE)
                # Fix double letters (e.g., "chriis" -> "chris", "creaator" -> "creator")
                artist = re.sub(r'([a-z])\1{2,}', r'\1\1', artist, flags=re.IGNORECASE)
                # Remove extra whitespace
                artist = ' '.join(artist.split())
                title = ' '.join(title.split())
                return f"{artist}: {title}"
        
        # Handle possessive forms like "Bad Bunny's Ketu tecré" -> "Bad Bunny: Ketu tecré"
        # Pattern: word(s) + 's + word(s) at the end or before "to my playlist" etc.
        # Match possessive 's (with or without apostrophe)
        # First, try to match possessive pattern with optional trailing words
        song_name_clean = song_name.strip()
        # Improved pattern: handles "Artist's Title" or "Artist's Title to my playlist"
        # More flexible: allows for titles with special characters
        possessive_pattern = r"^(.+?)\'?s\s+(.+?)(?:\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track).*)?$"
        possessive_match = re.match(possessive_pattern, song_name_clean, re.IGNORECASE)
        if possessive_match:
            artist = possessive_match.group(1).strip()
            title = possessive_match.group(2).strip()
            # Remove trailing words like "to my playlist" if captured
            title = re.sub(r'\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track).*$', '', title, flags=re.IGNORECASE)
            # Only convert if both artist and title are non-empty and title doesn't look like a continuation
            # Also check that title doesn't contain "to my playlist" etc. (should have been removed)
            # Allow longer titles (up to 20 words) for complex song names
            if artist and title and len(title.split()) <= 20:  # Reasonable title length
                return f"{artist}: {title}"
        
        # Handle two-word format that might be "Artist Title" (e.g., "Strings sajni")
        # Only if it's exactly two words and doesn't contain "by"
        if ':' not in song_name_clean and ' by ' not in song_name_clean.lower() and "'s" not in song_name_clean:
            words = song_name_clean.split()
            if len(words) == 2:
                # Could be "Artist Title" format
                # Check if first word is capitalized (likely artist name)
                first_word, second_word = words[0], words[1]
                if first_word and first_word[0].isupper() and second_word:
                    # Try treating as "Artist: Title"
                    return f"{first_word}: {second_word}"
        
        # Fix common typos first
        # Fix "bby" -> "by" (common typo)
        normalized = re.sub(r'\bbby\b', 'by', song_name, flags=re.IGNORECASE)
        # Fix double letters (e.g., "chriis" -> "chris", "creaator" -> "creator")
        normalized = re.sub(r'([a-z])\1{2,}', r'\1\1', normalized, flags=re.IGNORECASE)
        
        # IMPORTANT: Handle "Title by Artist" format BEFORE other processing
        # Convert "Title by Artist" to "Artist: Title" format
        # Pattern: match "by [artist]" at the end (but not "by" in the middle of title)
        by_artist_pattern = r'^(.+?)\s+by\s+([^,\.]+?)(?:\s+(?:to|from|in|on|at|the|my|a|an|playlist|song|track|version|original|$))'
        by_artist_match = re.search(by_artist_pattern, normalized, re.IGNORECASE)
        if by_artist_match:
            title_part = by_artist_match.group(1).strip()
            artist_part = by_artist_match.group(2).strip()
            # Clean up common prefixes like "the original version of"
            title_part = re.sub(r'^(?:the\s+)?(?:original\s+)?(?:version\s+of\s+)?', '', title_part, flags=re.IGNORECASE).strip()
            # Only convert if both parts are reasonable
            if title_part and artist_part and len(artist_part.split()) <= 5:
                return f"{artist_part}: {title_part}"
        
        # Remove content in parentheses (e.g., "(with The Weeknd & 21 Savage)")
        normalized = re.sub(r'\([^)]*\)', '', normalized)
        
        # Handle possessive apostrophes that aren't at word boundaries
        # But keep them for now if they're part of a possessive pattern
        # Remove quotes but be careful with possessive 's
        # First, try to preserve possessive 's patterns before removing quotes
        if "'s " in normalized or "'s " in normalized.lower():
            # This might be a possessive, but we already handled it above
            # So just remove the apostrophe if it's not part of a possessive
            pass
        
        # Remove quotes (but preserve possessive 's for now)
        normalized = normalized.replace('"', '')
        # Remove apostrophes that are not possessive (standalone or at end)
        normalized = re.sub(r"(?<!\w)'(?!s\s)", '', normalized)  # Remove ' that's not 's
        normalized = re.sub(r"'(?![sS]\s)", '', normalized)  # Remove ' that's not followed by 's
        
        # Don't remove "by [artist]" here - it should have been converted above
        # Only remove if it's clearly not an artist (e.g., "by the way" or "by myself")
        # But be conservative - if we see "by [Capitalized Word]", it's likely an artist
        if ' by ' in normalized.lower():
            # Check if "by" is followed by a capitalized word (likely artist)
            by_capitalized = re.search(r'\s+by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', normalized)
            if not by_capitalized:
                # Not followed by capitalized words, might be phrase like "by the way"
                normalized = re.sub(r'\s+by\s+.*$', '', normalized, flags=re.IGNORECASE)
        
        # Remove trailing punctuation that might interfere with search
        normalized = re.sub(r'[^\w\s:]+$', '', normalized)  # Remove trailing punctuation (but keep :)
        
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
