"""MusicCRS conversational agent."""

import json
import os
import ollama
import uuid
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
load_dotenv('config.env')

OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'https://ollama.ux.uis.no')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.3:70b')
OLLAMA_API_KEY = os.getenv('OLLAMA_API_KEY')


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
        self._database = self._load_database()  # Load Spotify Million Playlist Dataset
        
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
        utterance = AnnotatedUtterance(
            "It was nice talking to you. Bye",
            dialogue_acts=[DialogueAct(intent=self.stop_intent)],
            participant=DialogueParticipant.AGENT,
        )
        self._dialogue_connector.register_agent_utterance(utterance)

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
        elif utterance.text.startswith("/add "):
            song_info = utterance.text[5:]  # Remove "/add "
            response = self._add_song(song_info)
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
        elif utterance.text == "/quit":
            self.goodbye()
            return
        else:
            response = "I'm sorry, I don't understand that command."

        self._dialogue_connector.register_agent_utterance(
            AnnotatedUtterance(
                response,
                participant=DialogueParticipant.AGENT,
                dialogue_acts=dialogue_acts,
            )
        )

    # --- Response handlers ---

    def _help(self) -> str:
        """Provides help information about available commands."""
        help_text = """Here are the commands I understand:

**Basic Commands:**
• `/help` - Show this help message
• `/info` - Learn about MusicCRS
• `/quit` - End the conversation

**Playlist Commands:**
• `/add [artist]: [song]` - Add a song to current playlist
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

**Search & Discovery:**
• `/search [query]` - Search for songs by artist or title
• `/ask_llm [question]` - Ask the AI a question
• `/options` - See example options

Try typing a command to get started!"""

        # Add available songs to help (configurable limit for readability)
        available_songs = list(self._database.keys())[:self._help_song_limit]
        if available_songs:
            help_text += f"\n\n**Available Songs (first {self._help_song_limit}):**\n"
            for song in available_songs:
                help_text += f"• {song}\n"
            if len(self._database) > self._help_song_limit:
                help_text += f"... and {len(self._database) - self._help_song_limit} more songs in the database"
        
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

    def _load_database(self) -> Dict[str, Dict]:
        """Load Spotify Million Playlist Dataset.
        
        Returns:
            Dictionary mapping "artist: title" to song metadata
        """
        database = {}
        
        # Path to the downloaded dataset
        dataset_path = r"C:\Users\afaqm\.cache\kagglehub\datasets\himanshuwagh\spotify-million\versions\1\data"
        
        if not os.path.exists(dataset_path):
            raise FileNotFoundError(f"Spotify Million Playlist Dataset not found at {dataset_path}. Please ensure the dataset is downloaded.")
        
        try:
            # Load first few JSON files for demo (to avoid memory issues)
            json_files = [f for f in os.listdir(dataset_path) if f.endswith('.json')]
            
            if not json_files:
                raise FileNotFoundError("No JSON files found in dataset directory.")
            
            print(f"Loading Spotify Million Playlist Dataset from {len(json_files)} files...")
            
            # Process first 3 files for demo (to avoid memory issues)
            for filename in json_files[:3]:  # Process first 3 files
                filepath = os.path.join(dataset_path, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Extract tracks from playlists
                for playlist in data.get('playlists', []):
                    for track in playlist.get('tracks', []):
                        artist = track.get('artist_name', '').strip()
                        title = track.get('track_name', '').strip()
                        
                        if artist and title:
                            key = f"{artist}: {title}"
                            database[key] = {
                                'artist': artist,
                                'title': title,
                                'track_uri': track.get('track_uri', ''),
                                'album_name': track.get('album_name', ''),
                                'duration_ms': track.get('duration_ms', 0)
                            }
            
            print(f"Loaded {len(database)} unique songs from Spotify Million Playlist Dataset")
            return database
            
        except Exception as e:
            raise RuntimeError(f"Error loading Spotify Million Playlist Dataset: {e}")
    
    def _add_song(self, song_info: str) -> str:
        """Add a song to the current playlist.
        
        Args:
            song_info: Song in format "artist: title"
            
        Returns:
            Response message
        """
        song_key = song_info.strip()
        
        # Check if song exists in database
        if song_key not in self._database:
            return f"Sorry, '{song_key}' is not available in our database. Please check the spelling and try again."
        
        # Ensure we have a current playlist
        self._ensure_current_playlist()
        
        # Get current playlist
        current_playlist = self._get_current_playlist()
        
        # Check if song is already in playlist
        if song_key in current_playlist.songs:
            return f"'{song_key}' is already in your '{current_playlist.name}' playlist."
        
        # Add song to playlist
        current_playlist.songs.append(song_key)
        return f"Added '{song_key}' to your '{current_playlist.name}' playlist!"

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
        return f"Cleared your '{current_playlist.name}' playlist! Removed {song_count} {song_text}."

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

    def _search_songs(self, query: str) -> str:
        """Search for songs in the database by artist or title.
        
        Args:
            query: Search query (artist name, song title, or partial match)
            
        Returns:
            Formatted string with search results
        """
        if not query.strip():
            return "Please provide a search query. Example: /search Beatles"
        
        query_lower = query.lower().strip()
        results = []
        
        # Search through all songs in database
        for song_key in self._database.keys():
            song_lower = song_key.lower()
            
            # Check if query matches artist or title
            if query_lower in song_lower:
                results.append(song_key)
        
        # Sort results by relevance (exact matches first, then partial matches)
        def relevance_score(song):
            song_lower = song.lower()
            if song_lower.startswith(query_lower):
                return 0  # Highest priority
            elif song_lower.find(f" {query_lower}") != -1:
                return 1  # Second priority (word boundary match)
            else:
                return 2  # Lower priority (anywhere in string)
        
        results.sort(key=relevance_score)
        
        if not results:
            return f"No songs found matching '{query}'. Try searching for an artist name or song title."
        
        # Show all results (no limit) but format efficiently
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


if __name__ == "__main__":
    platform = FlaskSocketPlatform(MusicCRS)
    platform.start()
