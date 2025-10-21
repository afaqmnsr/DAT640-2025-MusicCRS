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
} from '@mui/material';
import {
  QueueMusic as QueueIcon,
  MusicNote as MusicIcon,
  PlayArrow as PlayIcon,
} from '@mui/icons-material';

interface PlaylistMessageProps {
  songs: string[];
  totalSongs: number;
  playlistName?: string;
  onCommandClick?: (command: string) => void;
}

export default function PlaylistMessage({ songs, totalSongs, playlistName, onCommandClick }: PlaylistMessageProps) {
  const formatSongDisplay = (song: string) => {
    const [artist, title] = song.split(':');
    return {
      artist: artist?.trim() || 'Unknown Artist',
      title: title?.trim() || 'Unknown Title',
      full: song
    };
  };

  const getArtistInitials = (artist: string) => {
    return artist
      .split(' ')
      .map(word => word.charAt(0))
      .join('')
      .toUpperCase()
      .slice(0, 2);
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
          {/* Compact Header */}
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 1.5 }}>
            <QueueIcon sx={{ mr: 0.5, color: '#1db954', fontSize: 20 }} />
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: '#1db954' }}>
              Your Current Playlist: {playlistName || 'Current Playlist'}
            </Typography>
            <Chip
              label={`${totalSongs} song${totalSongs !== 1 ? 's' : ''}`}
              size="small"
              sx={{
                ml: 1,
                backgroundColor: '#1db954',
                color: 'white',
                fontWeight: 'bold',
                height: 20,
                fontSize: '0.7rem'
              }}
            />
          </Box>

          {songs.length === 0 ? (
            <Box sx={{ textAlign: 'center', py: 2 }}>
              <MusicIcon sx={{ fontSize: 32, color: '#404040', mb: 1 }} />
              <Typography variant="body2" color="text.secondary">
                Your playlist is empty
              </Typography>
            </Box>
          ) : (
            <>
              <List dense sx={{ py: 0 }}>
                {songs.map((song, index) => {
                  const { artist, title } = formatSongDisplay(song);
                  return (
                    <ListItem
                      key={index}
                      sx={{
                        py: 1,
                        px: 1.5,
                        borderRadius: 1,
                        mb: 0.5,
                        '&:hover': {
                          backgroundColor: 'rgba(29, 185, 84, 0.05)',
                        }
                      }}
                    >
                      <ListItemIcon sx={{ minWidth: 30 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Typography
                            variant="caption"
                            sx={{
                              fontWeight: 'bold',
                              color: '#1db954',
                              minWidth: 16,
                              textAlign: 'center',
                              fontSize: '0.7rem'
                            }}
                          >
                            {index + 1}
                          </Typography>
                          <Avatar
                            sx={{
                              width: 24,
                              height: 24,
                              backgroundColor: '#1db954',
                              fontSize: '0.6rem',
                              fontWeight: 'bold'
                            }}
                          >
                            {getArtistInitials(artist)}
                          </Avatar>
                        </Box>
                      </ListItemIcon>
                      <ListItemText
                        sx={{ ml: 1 }}
                        primary={
                          <Typography variant="body2" sx={{ fontWeight: 'bold', color: '#333', fontSize: '0.85rem', lineHeight: 1.1 }}>
                            {title}
                          </Typography>
                        }
                        secondary={
                          <Typography variant="caption" sx={{ color: '#666', fontSize: '0.75rem', lineHeight: 1.0 }}>
                            {artist}
                          </Typography>
                        }
                      />
                    </ListItem>
                  );
                })}
              </List>
              
              <Box sx={{ display: 'flex', justifyContent: 'center', gap: 0.5, mt: 1 }}>
                <Chip
                  label="/view"
                  size="small"
                  onClick={() => onCommandClick && onCommandClick('/view')}
                  sx={{
                    backgroundColor: '#1db954',
                    color: 'white',
                    cursor: 'pointer',
                    height: 20,
                    fontSize: '0.7rem',
                    '&:hover': {
                      backgroundColor: '#1ed760',
                    }
                  }}
                />
                <Chip
                  label="/clear"
                  size="small"
                  onClick={() => onCommandClick && onCommandClick('/clear')}
                  sx={{
                    backgroundColor: '#ff4444',
                    color: 'white',
                    cursor: 'pointer',
                    height: 20,
                    fontSize: '0.7rem',
                    '&:hover': {
                      backgroundColor: '#ff6666',
                    }
                  }}
                />
              </Box>
            </>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
