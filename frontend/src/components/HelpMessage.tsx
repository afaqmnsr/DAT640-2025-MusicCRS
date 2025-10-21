import React from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Divider,
  Chip,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Paper,
} from '@mui/material';
import {
  Help as HelpIcon,
  MusicNote as MusicIcon,
  PlaylistAdd as PlaylistIcon,
  Chat as ChatIcon,
  Info as InfoIcon,
  ExitToApp as ExitIcon,
  Add as AddIcon,
  Remove as RemoveIcon,
  Visibility as ViewIcon,
  Clear as ClearIcon,
  Psychology as AIIcon,
  MoreHoriz as OptionsIcon,
  PlayArrow as PlayIcon,
  QueueMusic as QueueIcon,
  Edit as EditIcon,
  Image as ImageIcon,
} from '@mui/icons-material';

interface HelpMessageProps {
  onCommandClick?: (command: string) => void;
  sampleSongs?: string[];
  totalSongsCount?: number;
}

export default function HelpMessage({ onCommandClick, sampleSongs = [], totalSongsCount = 0 }: HelpMessageProps) {
  const basicCommands = [
    { command: '/help', description: 'Show this help message', icon: <HelpIcon /> },
    { command: '/info', description: 'Learn about MusicCRS', icon: <InfoIcon /> },
    { command: '/quit', description: 'End the conversation', icon: <ExitIcon /> },
  ];

  const playlistCommands = [
    { command: '/add [artist]: [song]', description: 'Add a song to current playlist (full format)', icon: <AddIcon /> },
    { command: '/add [song]', description: 'Add a song by title only (with disambiguation)', icon: <AddIcon /> },
    { command: '/remove [artist]: [song]', description: 'Remove a song from current playlist', icon: <RemoveIcon /> },
    { command: '/view', description: 'View current playlist', icon: <ViewIcon /> },
    { command: '/clear', description: 'Clear the current playlist', icon: <ClearIcon /> },
  ];

  const playlistManagementCommands = [
    { command: '/create [playlist_name]', description: 'Create a new playlist', icon: <AddIcon /> },
    { command: '/switch [playlist_name]', description: 'Switch to an existing playlist', icon: <PlayIcon /> },
    { command: '/list', description: 'List all your playlists', icon: <QueueIcon /> },
    { command: '/delete [playlist_name]', description: 'Delete a playlist', icon: <ClearIcon /> },
    { command: '/rename [old_name] [new_name]', description: 'Rename a playlist', icon: <EditIcon /> },
    { command: '/cover [playlist_name]', description: 'Generate a cover image for a playlist', icon: <ImageIcon /> },
  ];

  const otherFeatures = [
    { command: '/search [query]', description: 'Search for songs by artist or title', icon: <MusicIcon /> },
    { command: '/ask [question]', description: 'Ask questions about songs and artists', icon: <ChatIcon /> },
    { command: '/ask_llm [question]', description: 'Ask the AI a question', icon: <AIIcon /> },
    { command: '/options', description: 'See example options', icon: <OptionsIcon /> },
  ];

  const handleCommandClick = (command: string) => {
    if (onCommandClick) {
      onCommandClick(command);
    }
  };

  return (
    <Box sx={{ maxWidth: '100%', p: 1 }}>
      <Card sx={{ 
        backgroundColor: '#f8f9fa',
        border: '1px solid #e9ecef',
        borderRadius: 2,
        boxShadow: 'none'
      }}>
        <CardContent sx={{ p: 3 }}>
          {/* Header */}
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 3 }}>
            <MusicIcon sx={{ mr: 1, color: '#1db954', fontSize: 28 }} />
            <Typography variant="h6" sx={{ fontWeight: 'bold', color: '#1db954' }}>
              Welcome to MusicCRS!
            </Typography>
          </Box>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Here are the commands I understand. Click on any command to use it:
          </Typography>

          {/* Basic Commands */}
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1, display: 'flex', alignItems: 'center' }}>
              <ChatIcon sx={{ mr: 1, fontSize: 20 }} />
              Basic Commands
            </Typography>
            <List dense sx={{ py: 0 }}>
              {basicCommands.map((cmd, index) => (
                <ListItem key={index} sx={{ py: 0.5, px: 0 }}>
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    {cmd.icon}
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Chip
                          label={cmd.command}
                          size="small"
                          onClick={() => handleCommandClick(cmd.command)}
                          sx={{
                            backgroundColor: '#1db954',
                            color: 'white',
                            cursor: 'pointer',
                            '&:hover': {
                              backgroundColor: '#1ed760',
                            },
                            fontSize: '0.75rem',
                            height: 24
                          }}
                        />
                        <Typography variant="body2" color="text.secondary">
                          {cmd.description}
                        </Typography>
                      </Box>
                    }
                  />
                </ListItem>
              ))}
            </List>
          </Box>

          <Divider sx={{ my: 2 }} />

          {/* Playlist Commands */}
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1, display: 'flex', alignItems: 'center' }}>
              <PlaylistIcon sx={{ mr: 1, fontSize: 20 }} />
              Playlist Commands
            </Typography>
            <List dense sx={{ py: 0 }}>
              {playlistCommands.map((cmd, index) => (
                <ListItem key={index} sx={{ py: 0.5, px: 0 }}>
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    {cmd.icon}
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Chip
                          label={cmd.command}
                          size="small"
                          onClick={() => handleCommandClick(cmd.command)}
                          sx={{
                            backgroundColor: '#1db954',
                            color: 'white',
                            cursor: 'pointer',
                            '&:hover': {
                              backgroundColor: '#1ed760',
                            },
                            fontSize: '0.75rem',
                            height: 24
                          }}
                        />
                        <Typography variant="body2" color="text.secondary">
                          {cmd.description}
                        </Typography>
                      </Box>
                    }
                  />
                </ListItem>
              ))}
            </List>
          </Box>

          <Divider sx={{ my: 2 }} />

          {/* Playlist Management */}
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1, display: 'flex', alignItems: 'center' }}>
              <QueueIcon sx={{ mr: 1, fontSize: 20 }} />
              Playlist Management
            </Typography>
            <List dense sx={{ py: 0 }}>
              {playlistManagementCommands.map((cmd, index) => (
                <ListItem key={index} sx={{ py: 0.5, px: 0 }}>
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    {cmd.icon}
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Chip
                          label={cmd.command}
                          size="small"
                          onClick={() => handleCommandClick(cmd.command)}
                          sx={{
                            backgroundColor: '#1db954',
                            color: 'white',
                            cursor: 'pointer',
                            '&:hover': {
                              backgroundColor: '#1ed760',
                            },
                            fontSize: '0.75rem',
                            height: 24
                          }}
                        />
                        <Typography variant="body2" color="text.secondary">
                          {cmd.description}
                        </Typography>
                      </Box>
                    }
                  />
                </ListItem>
              ))}
            </List>
          </Box>

          <Divider sx={{ my: 2 }} />

          {/* Other Features */}
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1, display: 'flex', alignItems: 'center' }}>
              <AIIcon sx={{ mr: 1, fontSize: 20 }} />
              Other Features
            </Typography>
            <List dense sx={{ py: 0 }}>
              {otherFeatures.map((cmd, index) => (
                <ListItem key={index} sx={{ py: 0.5, px: 0 }}>
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    {cmd.icon}
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Chip
                          label={cmd.command}
                          size="small"
                          onClick={() => handleCommandClick(cmd.command)}
                          sx={{
                            backgroundColor: '#1db954',
                            color: 'white',
                            cursor: 'pointer',
                            '&:hover': {
                              backgroundColor: '#1ed760',
                            },
                            fontSize: '0.75rem',
                            height: 24
                          }}
                        />
                        <Typography variant="body2" color="text.secondary">
                          {cmd.description}
                        </Typography>
                      </Box>
                    }
                  />
                </ListItem>
              ))}
            </List>
          </Box>

          <Divider sx={{ my: 2 }} />

          {/* Available Songs */}
          {sampleSongs.length > 0 && (
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1, display: 'flex', alignItems: 'center' }}>
                <MusicIcon sx={{ mr: 1, fontSize: 20 }} />
                Available Songs (first 10)
              </Typography>
              <Paper sx={{ 
                backgroundColor: '#f5f5f5', 
                p: 2, 
                maxHeight: 200, 
                overflow: 'auto',
                border: '1px solid #e0e0e0'
              }}>
                <List dense>
                  {sampleSongs.map((song, index) => (
                    <ListItem key={index} sx={{ py: 0.25, px: 0 }}>
                      <ListItemText
                        primary={
                          <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                            • {song}
                          </Typography>
                        }
                      />
                    </ListItem>
                  ))}
                  {totalSongsCount > 0 && (
                    <ListItem sx={{ py: 0.25, px: 0 }}>
                      <ListItemText
                        primary={
                          <Typography variant="body2" sx={{ fontSize: '0.8rem', fontStyle: 'italic', color: 'text.secondary' }}>
                            ... and {totalSongsCount.toLocaleString()} more songs in the database
                          </Typography>
                        }
                      />
                    </ListItem>
                  )}
                </List>
              </Paper>
            </Box>
          )}

          <Box sx={{ mt: 2, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              Try typing a command or click on any command above to get started!
            </Typography>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
