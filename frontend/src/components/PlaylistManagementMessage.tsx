import React from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Avatar,
  Chip,
  Divider,
  Alert,
} from '@mui/material';
import {
  QueueMusic as QueueIcon,
  MusicNote as MusicIcon,
  Add as AddIcon,
  Delete as DeleteIcon,
  CheckCircle as CheckIcon,
  SwapHoriz as SwitchIcon,
} from '@mui/icons-material';
import PlaylistCover from './PlaylistCover';

interface PlaylistInfo {
  name: string;
  isCurrent: boolean;
  songCount: number;
}

interface PlaylistManagementMessageProps {
  message: string;
  onCommandClick?: (command: string) => void;
}

export default function PlaylistManagementMessage({ message, onCommandClick }: PlaylistManagementMessageProps) {
  // Parse different types of playlist management messages
  const parsePlaylistMessage = () => {
    // Check for playlist creation
    if (message.includes("Created new playlist") && message.includes("switched to it")) {
      const createMatch = message.match(/Created new playlist '(.+?)' and switched to it!/);
      const playlistName = createMatch ? createMatch[1] : 'Unknown';
      
      // Extract playlist list if present
      const playlists = extractPlaylistList(message);
      
      return {
        type: 'create',
        playlistName,
        playlists,
        message: `Created new playlist '${playlistName}' and switched to it!`
      };
    }
    
    // Check for playlist deletion
    if (message.includes("Deleted playlist") && message.includes("Switched to")) {
      const deleteMatch = message.match(/Deleted playlist '(.+?)'.*Switched to '(.+?)'/);
      const deletedPlaylist = deleteMatch ? deleteMatch[1] : 'Unknown';
      const switchedToPlaylist = deleteMatch ? deleteMatch[2] : 'Unknown';
      
      // Extract playlist list if present
      const playlists = extractPlaylistList(message);
      
      return {
        type: 'delete',
        deletedPlaylist,
        switchedToPlaylist,
        playlists,
        message: `Deleted playlist '${deletedPlaylist}' and switched to '${switchedToPlaylist}'`
      };
    }
    
    // Check for playlist list
    if (message.includes("**Your Playlists:**")) {
      const playlists = extractPlaylistList(message);
      return {
        type: 'list',
        playlists,
        message: 'Your Playlists'
      };
    }
    
    return null;
  };

  const extractPlaylistList = (text: string): PlaylistInfo[] => {
    const playlists: PlaylistInfo[] = [];
    const lines = text.split('\n');
    
    for (const line of lines) {
      // Match patterns like "1. My Playlist (current) - 0 songs" or "1. My Playlist - 0 songs"
      const match = line.match(/^\d+\.\s*(.+?)\s*(?:\(current\))?\s*-\s*(\d+)\s*songs?/);
      if (match) {
        const name = match[1].trim();
        const songCount = parseInt(match[2]);
        const isCurrent = line.includes('(current)');
        
        playlists.push({
          name,
          isCurrent,
          songCount
        });
      }
    }
    
    return playlists;
  };

  const parsedMessage = parsePlaylistMessage();
  
  if (!parsedMessage) {
    // Fallback to regular message display
    return (
      <Card sx={{ 
        backgroundColor: '#f8f9fa',
        border: '1px solid #e9ecef',
        borderRadius: 1.5,
        boxShadow: 'none'
      }}>
        <CardContent sx={{ p: 2 }}>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
            {message}
          </Typography>
        </CardContent>
      </Card>
    );
  }

  const getIconForType = (type: string) => {
    switch (type) {
      case 'create': return <AddIcon sx={{ color: '#1db954' }} />;
      case 'delete': return <DeleteIcon sx={{ color: '#ff4444' }} />;
      case 'list': return <QueueIcon sx={{ color: '#1db954' }} />;
      default: return <QueueIcon sx={{ color: '#1db954' }} />;
    }
  };

  const getAlertSeverity = (type: string) => {
    switch (type) {
      case 'create': return 'success';
      case 'delete': return 'warning';
      case 'list': return 'info';
      default: return 'info';
    }
  };

  return (
    <Box sx={{ maxWidth: '100%', p: 0.5 }}>
      <Card sx={{ 
        backgroundColor: '#f8f9fa',
        border: '1px solid #e9ecef',
        borderRadius: 1.5,
        boxShadow: 'none'
      }}>
        <CardContent sx={{ p: 2 }}>
          {/* Header */}
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
            {getIconForType(parsedMessage.type)}
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold', ml: 1, color: '#333' }}>
              {parsedMessage.type === 'create' && 'Playlist Created'}
              {parsedMessage.type === 'delete' && 'Playlist Deleted'}
              {parsedMessage.type === 'list' && 'Your Playlists'}
            </Typography>
          </Box>

          {/* Status Alert */}
          <Alert 
            severity={getAlertSeverity(parsedMessage.type)} 
            sx={{ mb: 2, fontSize: '0.85rem' }}
          >
            {parsedMessage.type === 'create' && (
              <>
                <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                  ✅ Created playlist '{parsedMessage.playlistName}'
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                  Switched to the new playlist automatically
                </Typography>
              </>
            )}
            {parsedMessage.type === 'delete' && (
              <>
                <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                  🗑️ Deleted playlist '{parsedMessage.deletedPlaylist}'
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                  Switched to '{parsedMessage.switchedToPlaylist}' automatically
                </Typography>
              </>
            )}
            {parsedMessage.type === 'list' && (
              <Typography variant="body2">
                Here are all your playlists:
              </Typography>
            )}
          </Alert>

          {/* Playlist List */}
          {parsedMessage.playlists && parsedMessage.playlists.length > 0 && (
            <Box>
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 1, color: '#333' }}>
                Playlist Overview
              </Typography>
              <List dense sx={{ py: 0 }}>
                {parsedMessage.playlists.map((playlist, index) => (
                  <ListItem
                    key={index}
                    sx={{
                      py: 1,
                      px: 1.5,
                      borderRadius: 1,
                      backgroundColor: playlist.isCurrent ? 'rgba(29, 185, 84, 0.1)' : 'transparent',
                      border: playlist.isCurrent ? '1px solid #1db954' : '1px solid transparent',
                      mb: 0.5,
                      '&:hover': {
                        backgroundColor: 'rgba(29, 185, 84, 0.05)',
                      }
                    }}
                  >
                    <ListItemIcon sx={{ minWidth: 40 }}>
                      <PlaylistCover
                        playlistName={playlist.name}
                        songCount={playlist.songCount}
                        size="small"
                        showSongCount={false}
                      />
                    </ListItemIcon>
                    <ListItemText
                      sx={{ ml: 1 }}
                      primary={
                        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <Typography variant="body2" sx={{ 
                            fontWeight: playlist.isCurrent ? 'bold' : 'normal', 
                            color: playlist.isCurrent ? '#1db954' : '#333',
                            fontSize: '0.85rem'
                          }}>
                            {playlist.name}
                            {playlist.isCurrent && ' (Current)'}
                          </Typography>
                          {playlist.isCurrent && (
                            <CheckIcon sx={{ color: '#1db954', fontSize: 16 }} />
                          )}
                        </Box>
                      }
                      secondary={
                        <Typography variant="caption" sx={{ color: '#666', fontSize: '0.75rem' }}>
                          {playlist.songCount} {playlist.songCount === 1 ? 'song' : 'songs'}
                        </Typography>
                      }
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}

          {/* Action Buttons */}
          <Box sx={{ display: 'flex', justifyContent: 'center', gap: 1, mt: 2 }}>
            <Chip
              label="/list"
              size="small"
              onClick={() => onCommandClick && onCommandClick('/list')}
              sx={{
                backgroundColor: '#1db954',
                color: 'white',
                cursor: 'pointer',
                height: 24,
                fontSize: '0.75rem',
                '&:hover': {
                  backgroundColor: '#1ed760',
                }
              }}
            />
            <Chip
              label="/create"
              size="small"
              onClick={() => onCommandClick && onCommandClick('/create')}
              sx={{
                backgroundColor: '#2196f3',
                color: 'white',
                cursor: 'pointer',
                height: 24,
                fontSize: '0.75rem',
                '&:hover': {
                  backgroundColor: '#1976d2',
                }
              }}
            />
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
