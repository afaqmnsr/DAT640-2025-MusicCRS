import { Box, Typography, Avatar, Paper } from '@mui/material';
import { SmartToy as RobotIcon, Person as PersonIcon } from '@mui/icons-material';
import Feedback from "./Feedback";
import HelpMessage from "./HelpMessage";
import PlaylistMessage from "./PlaylistMessage";
import PlaylistManagementMessage from "./PlaylistManagementMessage";

function UserChatMessage({ message }: { message: string }): JSX.Element {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1, maxWidth: '70%' }}>
        <Paper
          sx={{
            p: 2,
            backgroundColor: '#e3f2fd',
            borderRadius: '15px 15px 5px 15px',
          }}
        >
          <Typography variant="body2">{message}</Typography>
        </Paper>
        <Avatar sx={{ width: 32, height: 32, backgroundColor: '#1db954' }}>
          <PersonIcon />
        </Avatar>
      </Box>
    </Box>
  );
}

function AgentChatMessage({
  message,
  image_url,
  feedback,
  onCommandClick,
}: {
  message: string;
  image_url?: string;
  feedback: ((message: string, event: string) => void) | null;
  onCommandClick?: (command: string) => void;
}): JSX.Element {
  // Check if this is the welcome message
  const isWelcomeMessage = message.includes("Hello! I'm MusicCRS") && 
                          message.includes("Type '/help' to see what I can do!");

  if (isWelcomeMessage) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1, maxWidth: '70%' }}>
          <Avatar sx={{ width: 32, height: 32, backgroundColor: '#1db954' }}>
            <RobotIcon />
          </Avatar>
          <Paper
            sx={{
              p: 2,
              backgroundColor: '#f5f5f5',
              borderRadius: '15px 15px 15px 5px',
              position: 'relative',
            }}
          >
            {feedback && <Feedback message={message} on_feedback={feedback} />}
            <Typography variant="body2">
              Hello! I'm MusicCRS, your music recommendation assistant. I can help you create and manage playlists. Type{' '}
              <Box
                component="span"
                onClick={() => onCommandClick && onCommandClick('/help')}
                sx={{
                  color: '#1db954',
                  cursor: 'pointer',
                  textDecoration: 'underline',
                  fontWeight: 'bold',
                  '&:hover': {
                    color: '#1ed760',
                    backgroundColor: 'rgba(29, 185, 84, 0.1)',
                    borderRadius: '4px',
                    padding: '2px 4px',
                  }
                }}
              >
                '/help'
              </Box>
              {' '}to see what I can do!
            </Typography>
          </Paper>
        </Box>
      </Box>
    );
  }

  // Check if this is a playlist management message (create, delete, list)
  const isPlaylistManagementMessage = message.includes("Created new playlist") ||
                                     message.includes("Deleted playlist") ||
                                     (message.includes("**Your Playlists:**") && !message.includes("Your Current Playlist"));

  if (isPlaylistManagementMessage) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, maxWidth: '100%' }}>
          <Avatar sx={{ width: 32, height: 32, backgroundColor: '#1db954' }}>
            <RobotIcon />
          </Avatar>
          <Box sx={{ flex: 1 }}>
            {feedback && <Feedback message={message} on_feedback={feedback} />}
            <PlaylistManagementMessage 
              message={message}
              onCommandClick={onCommandClick}
            />
          </Box>
        </Box>
      </Box>
    );
  }

  // Check if this is a playlist message - more robust detection
  const isPlaylistMessage = message.includes("Your Current Playlist") || 
                           message.includes("Current Playlist") ||
                           (message.includes("playlist") && message.includes("Total songs"));

  if (isPlaylistMessage) {
    // Extract songs from the message
    const songs: string[] = [];
    let totalSongs = 0;
    let playlistName: string | undefined = undefined; // No hardcoded default
    
    const lines = message.split('\n');
    let inPlaylistSection = false;
    
    for (const line of lines) {
      // More flexible playlist detection
      if (line.includes("Your Current Playlist") || line.includes("Current Playlist")) {
        inPlaylistSection = true;
        
        // Try multiple patterns to extract playlist name and count
        const patterns = [
          // Pattern 1: "Your Current Playlist: PlaylistName Total songs: X"
          /Your Current Playlist:\s*(.+?)(?:\s+Total songs?:?\s*(\d+))?/i,
          // Pattern 2: "**Your Current Playlist: PlaylistName**"
          /\*\*Your Current Playlist:\s*(.+?)\*\*/i,
          // Pattern 3: "Current Playlist: PlaylistName"
          /Current Playlist:\s*(.+?)(?:\s+Total songs?:?\s*(\d+))?/i,
        ];
        
        for (const pattern of patterns) {
          const match = line.match(pattern);
          if (match) {
            playlistName = match[1].trim();
            if (match[2]) {
              totalSongs = parseInt(match[2]);
            }
            break;
          }
        }
        continue;
      }
      
      if (inPlaylistSection) {
        // Match numbered list items (1. Artist: Song)
        const match = line.match(/^\d+\.\s*(.+)$/);
        if (match) {
          songs.push(match[1].trim());
        }
        
        // Also try to extract total count from any line
        if (!totalSongs) {
          const countMatch = line.match(/Total songs?:?\s*(\d+)/i);
          if (countMatch) {
            totalSongs = parseInt(countMatch[1]);
          }
        }
      }
    }

    // Fallback: if we couldn't extract total songs, use songs array length
    if (!totalSongs && songs.length > 0) {
      totalSongs = songs.length;
    }

    return (
      <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, maxWidth: '100%' }}>
          <Avatar sx={{ width: 32, height: 32, backgroundColor: '#1db954' }}>
            <RobotIcon />
          </Avatar>
          <Box sx={{ flex: 1 }}>
            {feedback && <Feedback message={message} on_feedback={feedback} />}
            <PlaylistMessage 
              songs={songs}
              totalSongs={totalSongs}
              playlistName={playlistName}
              onCommandClick={onCommandClick}
            />
          </Box>
        </Box>
      </Box>
    );
  }

  // Check if this is a help message (more specific detection)
  const isHelpMessage = (message.includes("Here are the commands I understand:") && 
                       message.includes("**Basic Commands:**") && 
                       message.includes("**Playlist Commands:**") &&
                       message.includes("**Available Songs (first 10):**")) ||
                       (message.includes("Here are the commands I understand:") && 
                       message.includes("**Basic Commands:**") && 
                       message.includes("**Playlist Commands:**"));

  if (isHelpMessage) {
    // Extract sample songs from the message
    const sampleSongs: string[] = [];
    let totalSongsCount = 0;
    
    // Parse the message to extract songs
    const lines = message.split('\n');
    let inSampleSection = false;
    
    for (const line of lines) {
      if (line.includes('Available Songs (first 10):')) {
        inSampleSection = true;
        continue;
      }
      
      if (inSampleSection) {
        if (line.includes('... and') && line.includes('more songs')) {
          // Extract total count
          const match = line.match(/... and (\d+(?:,\d+)*) more songs/);
          if (match) {
            totalSongsCount = parseInt(match[1].replace(/,/g, ''));
          }
          break;
        }
        
        if (line.trim().startsWith('•')) {
          const song = line.trim().substring(1).trim();
          if (song) {
            sampleSongs.push(song);
          }
        }
      }
    }

    return (
      <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, maxWidth: '100%' }}>
          <Avatar sx={{ width: 32, height: 32, backgroundColor: '#1db954' }}>
            <RobotIcon />
          </Avatar>
          <Box sx={{ flex: 1 }}>
            {feedback && <Feedback message={message} on_feedback={feedback} />}
            <HelpMessage 
              onCommandClick={onCommandClick} 
              sampleSongs={sampleSongs}
              totalSongsCount={totalSongsCount}
            />
          </Box>
        </Box>
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1, maxWidth: '70%' }}>
        <Avatar sx={{ width: 32, height: 32, backgroundColor: '#1db954' }}>
          <RobotIcon />
        </Avatar>
        <Paper
          sx={{
            p: 2,
            backgroundColor: '#f5f5f5',
            borderRadius: '15px 15px 15px 5px',
            position: 'relative',
          }}
        >
          {feedback && <Feedback message={message} on_feedback={feedback} />}
          {!!image_url && (
            <Box sx={{ display: 'flex', justifyContent: 'center', mb: 1 }}>
              <Box
                component="img"
                src={image_url}
                alt=""
                sx={{ 
                  width: "200px", 
                  height: "auto", 
                  borderRadius: "8px",
                  maxWidth: "100%"
                }}
              />
            </Box>
          )}
          <Typography
            variant="body2"
            dangerouslySetInnerHTML={{
              __html: message,
            }}
          />
        </Paper>
      </Box>
    </Box>
  );
}

export { UserChatMessage, AgentChatMessage };