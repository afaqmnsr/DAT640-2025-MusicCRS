import { useContext, useState, useCallback, useEffect } from "react";
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { Box } from '@mui/material';
import { ConfigContext } from "./contexts/ConfigContext";
import { UserContext } from "./contexts/UserContext";
import ChatBox from "./components/ChatBox/ChatBox";
import LoginForm from "./components/LoginForm/LoginForm";
import ChatWidget from "./components/Widget/ChatWidget";
import PlaylistPanel from "./components/PlaylistPanel/PlaylistPanel";
import Header from "./components/Header/Header";
import SpotifyPlayer from "./components/SpotifyPlayer/SpotifyPlayer";
import { useSocket } from "./contexts/SocketContext";
import { ChatMessage } from "./types";

// Create light theme
const lightTheme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#1db954',
    },
    secondary: {
      main: '#1ed760',
    },
    background: {
      default: '#ffffff',
      paper: '#f5f5f5',
    },
  },
});

export default function App() {
  const { config } = useContext(ConfigContext);
  const { user } = useContext(UserContext);
  const { startConversation, sendMessage, onMessage } = useSocket();
  const [playlist, setPlaylist] = useState<string[]>([]);
  const [availableSongs, setAvailableSongs] = useState<string[]>([]);
  const [playlistList, setPlaylistList] = useState<string[]>(['My Playlist']);
  const [currentPlaylist, setCurrentPlaylist] = useState<string>('My Playlist');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [allPlaylists, setAllPlaylists] = useState<{[key: string]: string[]}>({});
  const [generatedCoverImages, setGeneratedCoverImages] = useState<{[playlistName: string]: string}>({});
  const [searchResults, setSearchResults] = useState<string[]>([]);
  const [currentTrackInfo, setCurrentTrackInfo] = useState<any>(null);
  const [spotifyAccessToken, setSpotifyAccessToken] = useState<string | null>(null);

  // Initialize socket connection and load song database immediately
  useEffect(() => {
    startConversation();
    
    // Check for Spotify authentication
    checkSpotifyAuth();
    
    // Load available songs automatically to enable search functionality
    const timer = setTimeout(() => {
      sendMessage({ message: '/help' });
    }, 1000);
    
    // Fallback: if no songs loaded after 5 seconds, try again
    const fallbackTimer = setTimeout(() => {
      if (availableSongs.length === 0) {
        console.log('No songs loaded, retrying...');
        sendMessage({ message: '/help' });
      }
    }, 5000);
    
    return () => {
      clearTimeout(timer);
      clearTimeout(fallbackTimer);
    };
  }, [startConversation, sendMessage, availableSongs.length]);

  // Check Spotify authentication status
  const checkSpotifyAuth = async () => {
    try {
      const response = await fetch('http://localhost:5000/auth/status');
      const data = await response.json();
      
      if (data.authenticated) {
        console.log('✅ Spotify authenticated:', data.token);
        // Get the full token
        const tokenResponse = await fetch('http://localhost:5000/auth/token');
        const tokenData = await tokenResponse.json();
        setSpotifyAccessToken(tokenData.access_token);
      } else {
        console.log('⚠️ Spotify authentication required');
        console.log('🔗 Visit: http://localhost:5000/auth/login');
      }
    } catch (error) {
      console.log('⚠️ Spotify auth server not running:', error);
      console.log('🚀 Start MusicCRS server to enable authentication');
    }
  };

  // Handle all socket messages in App component
  useEffect(() => {
    onMessage((message: ChatMessage) => {
      console.log('App received message:', message.text); // Debug log
      
      // Add all messages to chat history for display (mark as agent messages)
      const agentMessage: ChatMessage = {
        ...message,
        participant: 'agent',
        timestamp: new Date().toISOString()
      };
      setChatMessages(prev => [...prev, agentMessage]);
      
      // Handle song database loading - now loads all songs
      if (message.text && (message.text.includes("**Sample Songs (showing") || message.text.includes("**Available Songs"))) {
        // Extract available songs from help command response
        const lines = message.text.split('\n');
        const songs: string[] = [];
        let inSongsSection = false;
        
        for (const line of lines) {
          if (line.includes("**Sample Songs (showing") || line.includes("**Available Songs")) {
            inSongsSection = true;
            continue;
          }
          if (inSongsSection && line.startsWith("• ")) {
            const song = line.replace("• ", "").trim();
            if (song) {
              songs.push(song);
            }
          } else if (inSongsSection && line.includes("... and")) {
            // Stop parsing when we hit the "... and X more songs" line
            break;
          }
        }
        
        if (songs.length > 0) {
          console.log('Loaded', songs.length, 'songs from database'); // Debug log
          setAvailableSongs(songs);
        }
      }
      
      // Handle cover generation messages
      if (message.text && message.text.includes('Generated cover image for playlist')) {
        console.log('App received cover generation message');
        
        // Extract playlist name from the message
        const playlistMatch = message.text.match(/Generated cover image for playlist '(.+?)'/);
        const playlistName = playlistMatch ? playlistMatch[1] : currentPlaylist;
        
        // Extract base64 image data from the response
        const lines = message.text.split('\n');
        let imageData: string | null = null;
        
        for (const line of lines) {
          if (line.includes('data:image/png;base64,')) {
            imageData = line.trim();
            break;
          }
        }
        
        if (imageData) {
          console.log('App found image data, setting generated cover image for playlist:', playlistName);
          setGeneratedCoverImages(prev => ({
            ...prev,
            [playlistName]: imageData as string
          }));
        } else {
          console.log('App: No image data found in cover message');
        }
        return; // Don't process as playlist update
      }
      
      // Handle Spotify track info responses
      if (message.text && message.text.includes("SPOTIFY_TRACK_INFO:")) {
        console.log('Spotify track info received:', message.text); // Debug log
        
        try {
          const jsonMatch = message.text.match(/SPOTIFY_TRACK_INFO:\s*(.+)/);
          if (jsonMatch) {
            const trackData = JSON.parse(jsonMatch[1]);
            console.log('Parsed track data:', trackData); // Debug log
            setCurrentTrackInfo(trackData);
          }
        } catch (error) {
          console.error('Error parsing Spotify track info:', error);
        }
        
        return; // Skip other processing
      }
      
      // Handle search results - extract songs and update search results
      if (message.text && (message.text.includes("Found") && message.text.includes("songs matching") || 
          message.text.includes("No songs found matching"))) {
        console.log('Search results received, processing...'); // Debug log
        
        // Extract songs from search results
        const lines = message.text.split('\n');
        const songs: string[] = [];
        let inResultsSection = false;
        
        for (const line of lines) {
          // Look for numbered list items (1. Artist: Song)
          const match = line.match(/^\d+\.\s*(.+)$/);
          if (match) {
            songs.push(match[1].trim());
          }
        }
        
        if (songs.length > 0) {
          console.log('Extracted', songs.length, 'songs from search results'); // Debug log
          setSearchResults(songs);
        } else {
          setSearchResults([]);
        }
        
        return; // Skip all playlist processing for search results
      }
      
      // Handle playlist clear
      if (message.text && message.text.includes("Cleared your") && message.text.includes("playlist!")) {
        console.log('App clearing playlist'); // Debug log
        
        // Extract playlist name from clear message
        const clearMatch = message.text.match(/Cleared your '(.+?)' playlist!/);
        if (clearMatch) {
          const clearedPlaylistName = clearMatch[1];
          console.log('Cleared playlist:', clearedPlaylistName); // Debug log
          
          // Update allPlaylists to reflect the cleared playlist
          setAllPlaylists(prev => {
            const updatedPlaylists = { ...prev };
            updatedPlaylists[clearedPlaylistName] = []; // Clear the songs
            console.log('Updated allPlaylists after clear:', updatedPlaylists); // Debug log
            return updatedPlaylists;
          });
          
          // Clear the current playlist display
          setPlaylist([]);
        }
        
        // Don't process as regular playlist update
        return;
      }
      
      // Handle playlist creation
      if (message.text && message.text.includes("Created new playlist") && message.text.includes("and switched to it")) {
        console.log('Playlist created, updating state...'); // Debug log
        
        // Extract playlist name from creation message
        const createMatch = message.text.match(/Created new playlist '(.+?)' and switched to it/);
        if (createMatch) {
          const newPlaylistName = createMatch[1];
          console.log('Created new playlist:', newPlaylistName); // Debug log
          
          // Update current playlist
          setCurrentPlaylist(newPlaylistName);
          
          // Add new playlist to playlist list
          setPlaylistList(prev => {
            if (!prev.includes(newPlaylistName)) {
              const updatedList = [...prev, newPlaylistName];
              console.log('Added new playlist to list:', newPlaylistName, 'Updated list:', updatedList); // Debug log
              return updatedList;
            }
            return prev;
          });
          
          // Initialize new playlist as empty in allPlaylists
          setAllPlaylists(prev => {
            const newPlaylists = { ...prev };
            newPlaylists[newPlaylistName] = []; // New playlist starts empty
            console.log('Initialized new playlist as empty:', newPlaylistName); // Debug log
            return newPlaylists;
          });
          
          // Clear the current playlist display
          setPlaylist([]);
        }
        
        // Don't process as regular playlist update
        return;
      }
      
      // Handle playlist updates
      if (message.text && message.text.includes("**Your Current Playlist:")) {
        console.log('App parsing playlist update:', message.text); // Debug log
        const lines = message.text.split('\n');
        const songs: string[] = [];
        let playlistName = '';
        
        // Extract playlist name from the header
        const headerMatch = message.text.match(/\*\*Your Current Playlist: (.+?)\*\*/);
        if (headerMatch) {
          playlistName = headerMatch[1].trim();
        }
        
        for (const line of lines) {
          const match = line.match(/^\d+\. (.+)$/);
          if (match) {
            songs.push(match[1]);
          }
        }
        console.log('App parsed songs:', songs, 'for playlist:', playlistName); // Debug log
        console.log('Setting playlist state to:', songs); // Debug log
        setPlaylist(songs);
        
        // Update the songs for the specific playlist in allPlaylists
        if (playlistName) {
          setAllPlaylists(prev => {
            console.log('Updating allPlaylists for playlist:', playlistName, 'with songs:', songs); // Debug log
            console.log('Previous allPlaylists state:', prev); // Debug log
            const updated = {
              ...prev,
              [playlistName]: songs
            };
            console.log('Updated allPlaylists state:', updated); // Debug log
            return updated;
          });
        }
      } else if (message.text && message.text.includes("Your playlist is empty")) {
        console.log('App received empty playlist message - updating UI to show empty playlist'); // Debug log
        // Update the UI to show empty playlist
        setPlaylist([]);
        // Don't update allPlaylists here - this is just an informational message
        // The actual state changes were already handled by the add/remove messages
      } else if (message.text && message.text.includes("Added '")) {
        // When a song is added, refresh the playlist view
        console.log('Song added, refreshing playlist...', message.text); // Debug log
        setTimeout(() => {
          console.log('Sending /view command...'); // Debug log
          sendMessage({ message: '/view' });
        }, 500);
      } else if (message.text && message.text.includes("Removed '")) {
        // When a song is removed, update the allPlaylists state directly
        console.log('Song removed, updating allPlaylists state...'); // Debug log
        
        // Extract the song name from the removal message
        const removeMatch = message.text.match(/Removed '(.+?)' from your '(.+?)' playlist!/);
        if (removeMatch) {
          const removedSong = removeMatch[1];
          const playlistName = removeMatch[2];
          console.log('Removed song:', removedSong, 'from playlist:', playlistName); // Debug log
          
          // Update allPlaylists to remove the song
          setAllPlaylists(prev => {
            const updatedPlaylists = { ...prev };
            if (updatedPlaylists[playlistName]) {
              updatedPlaylists[playlistName] = updatedPlaylists[playlistName].filter(song => song !== removedSong);
              console.log('Updated allPlaylists after removal:', updatedPlaylists); // Debug log
            }
            return updatedPlaylists;
          });
          
          // Update the current playlist display
          setPlaylist(prev => prev.filter(song => song !== removedSong));
        }
      } else if (message.text && message.text.includes("Switched to playlist")) {
        // Parse playlist switch confirmation and refresh the playlist view
        console.log('Playlist switched, refreshing...'); // Debug log
        
        // Extract the playlist name from the switch message
        const switchMatch = message.text.match(/Switched to playlist '(.+?)'/);
        if (switchMatch) {
          const playlistName = switchMatch[1];
          console.log('Switched to playlist:', playlistName); // Debug log
          setCurrentPlaylist(playlistName);
          
          // Restore songs for the switched playlist if we have them
          setAllPlaylists(prev => {
            const existingSongs = prev[playlistName] || [];
            console.log('Restoring songs for playlist:', playlistName, 'songs:', existingSongs); // Debug log
            console.log('Current allPlaylists state before switch:', prev); // Debug log
            setPlaylist(existingSongs);
            
            // Ensure the playlist exists in allPlaylists
            if (!prev[playlistName]) {
              const updatedPlaylists = { ...prev };
              updatedPlaylists[playlistName] = existingSongs;
              console.log('Added missing playlist to allPlaylists:', playlistName, 'with songs:', existingSongs); // Debug log
              return updatedPlaylists;
            }
            
            console.log('Keeping allPlaylists unchanged for existing playlist:', playlistName); // Debug log
            return prev; // Keep allPlaylists unchanged if playlist already exists
          });
        }
        
        // Don't send /view immediately - let the user's action trigger it
        // This prevents overwriting the playlist data with server data
      } else if (message.text && message.text.includes("Renamed playlist")) {
        // Handle playlist rename - move songs from old name to new name
        console.log('Playlist renamed, updating song storage...'); // Debug log
        
        const renameMatch = message.text.match(/Renamed playlist '(.+?)' to '(.+?)'/);
        if (renameMatch) {
          const oldName = renameMatch[1];
          const newName = renameMatch[2];
          console.log('Renamed playlist from:', oldName, 'to:', newName); // Debug log
          
          // Move songs from old playlist name to new playlist name
          setAllPlaylists(prev => {
            const songs = prev[oldName] || [];
            const newPlaylists = { ...prev };
            delete newPlaylists[oldName]; // Remove old name
            newPlaylists[newName] = songs; // Add with new name
            console.log('Moved songs from', oldName, 'to', newName, ':', songs); // Debug log
            return newPlaylists;
          });
          
          // Update current playlist if it was the renamed one
          if (currentPlaylist === oldName) {
            setCurrentPlaylist(newName);
          }
        }
        
        setTimeout(() => {
          sendMessage({ message: '/view' });
        }, 500);
      } else if (message.text && message.text.includes("Deleted playlist")) {
        // Parse playlist deletion and refresh the playlist view
        console.log('Playlist deleted, refreshing...'); // Debug log
        
        // Extract the playlist name that was deleted and the new current playlist
        const deleteMatch = message.text.match(/Deleted playlist '(.+?)'.*Switched to '(.+?)'/);
        if (deleteMatch) {
          const deletedPlaylist = deleteMatch[1];
          const newCurrentPlaylist = deleteMatch[2];
          console.log('Deleted playlist:', deletedPlaylist, 'Switched to:', newCurrentPlaylist); // Debug log
          setCurrentPlaylist(newCurrentPlaylist);
          
          // Remove deleted playlist from allPlaylists
          setAllPlaylists(prev => {
            const newPlaylists = { ...prev };
            delete newPlaylists[deletedPlaylist];
            console.log('Removed deleted playlist from allPlaylists:', deletedPlaylist); // Debug log
            return newPlaylists;
          });
        }
        
        // Always refresh the playlist view after deletion
        setTimeout(() => {
          sendMessage({ message: '/view' });
        }, 500);
      }
      
      // Handle playlist list updates
      if (message.text && message.text.includes("**Your Playlists:**")) {
        console.log('App parsing playlist list:', message.text); // Debug log
        const lines = message.text.split('\n');
        const playlists: string[] = [];
        let newCurrentPlaylist = '';
        
        for (const line of lines) {
          // Look for playlist entries like "1. ddd (current) - 0 songs" or "• My Playlist (5 songs) - Current"
          const playlistMatch = line.match(/^\d+\.\s*(.+?)\s*\(current\)\s*-\s*\d+\s*songs?/);
          const playlistMatchNoCurrent = line.match(/^\d+\.\s*(.+?)\s*-\s*\d+\s*songs?/);
          const bulletMatch = line.match(/•\s*(.+?)\s*\((\d+)\s*songs?\)(?:\s*-\s*Current)?/);
          
          if (playlistMatch) {
            const playlistName = playlistMatch[1].trim();
            playlists.push(playlistName);
            newCurrentPlaylist = playlistName;
          } else if (playlistMatchNoCurrent) {
            const playlistName = playlistMatchNoCurrent[1].trim();
            playlists.push(playlistName);
          } else if (bulletMatch) {
            const playlistName = bulletMatch[1].trim();
            const isCurrent = line.includes('Current');
            playlists.push(playlistName);
            if (isCurrent) {
              newCurrentPlaylist = playlistName;
            }
          }
        }
        
        // Notify parent component about playlist updates
        if (playlists.length > 0) {
          setPlaylistList(playlists);
          // If we found a current playlist, notify about that too
          if (newCurrentPlaylist && newCurrentPlaylist !== currentPlaylist) {
            console.log('Updating current playlist from list:', newCurrentPlaylist); // Debug log
            setCurrentPlaylist(newCurrentPlaylist);
          }
        }
      }
    });
  }, [onMessage, sendMessage]);

  const handleSendMessage = useCallback((message: string) => {
    // Add user message to chat display immediately
    const userMessage: ChatMessage = {
      text: message,
      participant: 'user',
      timestamp: new Date().toISOString()
    };
    setChatMessages(prev => [...prev, userMessage]);
    
    // Send message to backend
    sendMessage({ message });
  }, [sendMessage]);

  const handleClearChat = useCallback(() => {
    setChatMessages([]);
  }, []);

  
  return (
    <ThemeProvider theme={lightTheme}>
      <CssBaseline />
      <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <Header username={user?.username} />
        
        {/* Main Content */}
        <Box sx={{ display: 'flex', flex: 1 }}>
          {/* Chat Area - Floating widget takes minimal space */}
          <Box sx={{ width: 0, minWidth: 0 }}>
            <ChatWidget>
              {!user && config.useLogin ? (
                <LoginForm />
              ) : (
                <ChatBox 
                  messages={chatMessages}
                  onSendMessage={handleSendMessage}
                  onClearChat={handleClearChat}
                />
              )}
            </ChatWidget>
          </Box>
          
          {/* Playlist Panel - Takes full remaining space */}
          <Box sx={{ flex: 1, borderLeft: '1px solid #e0e0e0', display: 'flex', flexDirection: 'column' }}>
            <PlaylistPanel
              playlist={playlist}
              availableSongs={availableSongs}
              playlistList={playlistList}
              currentPlaylist={currentPlaylist}
              allPlaylists={allPlaylists}
              generatedCoverImage={generatedCoverImages[currentPlaylist] || null}
              searchResults={searchResults}
            />
            
            {/* Spotify Player - Show when track info is available */}
            {currentTrackInfo && (
              <Box sx={{ borderTop: '1px solid #e0e0e0', height: '120px' }}>
                <SpotifyPlayer 
                  trackInfo={currentTrackInfo}
                  accessToken={spotifyAccessToken}
                />
              </Box>
            )}
          </Box>
        </Box>
      </Box>
    </ThemeProvider>
  );
}
