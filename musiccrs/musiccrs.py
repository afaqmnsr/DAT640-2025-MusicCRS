"""MusicCRS conversational agent."""

import os
import ollama
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
        return """Here are the commands I understand:

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

    def _info(self) -> str:
        """Gives information about the agent."""
        return """I am MusicCRS, a conversational music recommender system. 

I can help you:
• Create and manage playlists
• Add and remove songs
• Get music recommendations
• Answer questions about music

Type '/help' to see all available commands!"""

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
