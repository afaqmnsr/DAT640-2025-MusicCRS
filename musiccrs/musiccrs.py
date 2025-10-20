"""MusicCRS conversational agent."""

import json
import os
import ollama
from typing import Dict, List
from dialoguekit.core.annotated_utterance import AnnotatedUtterance
from dialoguekit.core.dialogue_act import DialogueAct
from dialoguekit.core.intent import Intent
from dialoguekit.core.slot_value_annotation import SlotValueAnnotation
from dialoguekit.core.utterance import Utterance
from dialoguekit.participant.agent import Agent
from dialoguekit.participant.participant import DialogueParticipant
from dialoguekit.platforms import FlaskSocketPlatform

# Load environment variables from config.env
from dotenv import load_dotenv
load_dotenv('config.env')

OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'https://ollama.ux.uis.no')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.3:70b')
OLLAMA_API_KEY = os.getenv('OLLAMA_API_KEY')

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

        self._playlist = []  # Stores the current playlist
        self._database = self._load_database()  # Load Spotify Million Playlist Dataset

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
• `/add [artist]: [song]` - Add a song to playlist
• `/remove [artist]: [song]` - Remove a song from playlist
• `/view` - View current playlist
• `/clear` - Clear the playlist

**Other Features:**
• `/ask_llm [question]` - Ask the AI a question
• `/options` - See example options

Try typing a command to get started!"""

        # Add available songs to help (limit to first 10 for readability)
        available_songs = list(self._database.keys())[:10]
        if available_songs:
            help_text += "\n\n**Available Songs (sample):**\n"
            for song in available_songs:
                help_text += f"• {song}\n"
            if len(self._database) > 10:
                help_text += f"... and {len(self._database) - 10} more songs in the database"
        
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
        """Add a song to the playlist.
        
        Args:
            song_info: Song in format "artist: title"
            
        Returns:
            Response message
        """
        song_key = song_info.strip()
        
        # Check if song exists in database
        if song_key not in self._database:
            return f"Sorry, '{song_key}' is not available in our database. Please check the spelling and try again."
        
        # Check if song is already in playlist
        if song_key in self._playlist:
            return f"'{song_key}' is already in your playlist."
        
        # Add song to playlist
        self._playlist.append(song_key)
        return f"Added '{song_key}' to your playlist!"

    def _remove_song(self, song_info: str) -> str:
        """Remove a song from the playlist.
        
        Args:
            song_info: Song in format "artist: title"
            
        Returns:
            Response message
        """
        song_key = song_info.strip()
        
        # Check if song is in playlist
        if song_key not in self._playlist:
            return f"'{song_key}' is not in your playlist."
        
        # Remove song from playlist
        self._playlist.remove(song_key)
        return f"Removed '{song_key}' from your playlist!"

    def _view_playlist(self) -> str:
        """View the current playlist.
        
        Returns:
            Formatted playlist
        """
        if not self._playlist:
            return "Your playlist is empty. Use '/add [artist]: [title]' to add songs!"
        
        playlist_text = "**Your Current Playlist:**\n\n"
        for i, song in enumerate(self._playlist, 1):
            playlist_text += f"{i}. {song}\n"
        
        playlist_text += f"\nTotal songs: {len(self._playlist)}"
        return playlist_text

    def _clear_playlist(self) -> str:
        """Clear the entire playlist.
        
        Returns:
            Response message
        """
        if not self._playlist:
            return "Your playlist is already empty."
        
        song_count = len(self._playlist)
        self._playlist.clear()
        return f"Cleared your playlist! Removed {song_count} songs."

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

    def _options(self, options: list[str]) -> str:
        """Presents options to the user."""
        return (
            "Here are some options:\n<ol>\n"
            + "\n".join([f"<li>{option}</li>" for option in options])
            + "</ol>\n"
        )


if __name__ == "__main__":
    platform = FlaskSocketPlatform(MusicCRS)
    platform.start()
