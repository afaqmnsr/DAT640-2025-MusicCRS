import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Box,
  List,
  ListItem,
  ListItemText,
  IconButton,
  Typography,
  TextField,
  InputAdornment,
  Chip,
  Button,
  Divider,
  Paper,
  Avatar,
  Tooltip,
  Badge,
  CircularProgress,
  Alert,
  Fade,
  Select,
  MenuItem,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Menu,
  ListItemIcon,
} from '@mui/material';
import {
  Search as SearchIcon,
  Add as AddIcon,
  Delete as DeleteIcon,
  PlayArrow as PlayIcon,
  MusicNote as MusicIcon,
  Clear as ClearIcon,
  Refresh as RefreshIcon,
  QueueMusic as QueueIcon,
  Create as CreateIcon,
  Edit as EditIcon,
  MoreVert as MoreVertIcon,
  Check as CheckIcon,
  Close as CloseIcon,
} from '@mui/icons-material';
import { useSocket } from '../../contexts/SocketContext';
import PlaylistCover from '../PlaylistCover';

interface PlaylistSidebarProps {
  playlist: string[];
  availableSongs: string[];
  playlistList: string[];
  currentPlaylist: string;
  allPlaylists: {[key: string]: string[]};
  generatedCoverImage?: string | null;
  searchResults?: string[];
}

interface PlaylistInfo {
  name: string;
  songs: string[];
}

export default function PlaylistSidebar({
  playlist,
  availableSongs,
  playlistList,
  currentPlaylist: propCurrentPlaylist,
  allPlaylists,
  generatedCoverImage,
  searchResults: propSearchResults = [],
}: PlaylistSidebarProps) {
  const { sendMessage } = useSocket();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<string[]>([]);
  const [showSearchResults, setShowSearchResults] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Playlist management state
  const [playlists, setPlaylists] = useState<PlaylistInfo[]>([]);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newPlaylistName, setNewPlaylistName] = useState('');
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renamePlaylistName, setRenamePlaylistName] = useState('');
  const [playlistToRename, setPlaylistToRename] = useState('');
  const [menuAnchor, setMenuAnchor] = useState<null | HTMLElement>(null);
  
  // Confirmation dialog state
  const [songDeleteDialogOpen, setSongDeleteDialogOpen] = useState(false);
  const [songToDelete, setSongToDelete] = useState<string>('');
  const [playlistDeleteDialogOpen, setPlaylistDeleteDialogOpen] = useState(false);
  const [playlistToDelete, setPlaylistToDelete] = useState<string>('');
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Use the current playlist from props
  const currentPlaylist = propCurrentPlaylist;

  // Update playlists when playlistList prop changes
  useEffect(() => {
    console.log('PlaylistPanel updating playlists:', { playlistList, currentPlaylist, allPlaylists }); // Debug log
    const updatedPlaylists = playlistList.map(name => ({
      name,
      songs: allPlaylists[name] || []
    }));
    
    // Ensure currentPlaylist is always included in the playlists array
    if (currentPlaylist && !playlistList.includes(currentPlaylist)) {
      updatedPlaylists.push({
        name: currentPlaylist,
        songs: allPlaylists[currentPlaylist] || []
      });
    }
    
    console.log('PlaylistPanel updated playlists:', updatedPlaylists); // Debug log
    setPlaylists(updatedPlaylists);
  }, [playlistList, currentPlaylist, allPlaylists]);

  // Update search results when prop changes
  useEffect(() => {
    if (propSearchResults.length > 0) {
      setSearchResults(propSearchResults);
      setShowSearchResults(true);
      console.log('Updated search results from prop:', propSearchResults.length, 'songs'); // Debug log
    }
  }, [propSearchResults]);

  // Enhanced search functionality - uses backend search for unlimited songs
  const searchSongs = useCallback((query: string) => {
    if (!query.trim()) {
      setSearchResults([]);
      setShowSearchResults(false);
      return;
    }

    // Use backend search command for comprehensive results from entire database
    sendMessage({ message: `/search ${query}` });
    
    // Show search results from backend (propSearchResults) if available
    if (propSearchResults.length > 0) {
      setSearchResults(propSearchResults);
      setShowSearchResults(true);
      console.log('Using backend search results:', propSearchResults.length, 'songs'); // Debug log
    } else {
      // Fallback to local search if no backend results yet
      const searchTerm = query.toLowerCase();
      const localResults = availableSongs
        .filter(song => {
          const songLower = song.toLowerCase();
          const [artist, title] = songLower.split(':');
          return songLower.includes(searchTerm) || 
                 artist?.trim().includes(searchTerm) ||
                 title?.trim().includes(searchTerm);
        })
        .slice(0, 20); // Show fewer local results since we have backend search

      setSearchResults(localResults);
      setShowSearchResults(localResults.length > 0);
      console.log('Using local search results:', localResults.length, 'songs'); // Debug log
    }
  }, [availableSongs, sendMessage, propSearchResults]);

  // Handle search input changes with debouncing
  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setSearchQuery(value);
    
    // Clear previous timeout
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    
    // Debounce search to avoid too many requests
    searchTimeoutRef.current = setTimeout(() => {
      searchSongs(value);
    }, 300); // 300ms delay
  }, [searchSongs]);

  // Add song to playlist
  const handleAddSong = useCallback((song: string) => {
    console.log('Adding song:', song); // Debug log
    console.log('Song format check - contains colon:', song.includes(':')); // Debug log
    setIsLoading(true);
    setError(null);
    
    const command = `/add ${song}`;
    console.log('Sending command:', command); // Debug log
    sendMessage({ message: command });
    
    // Clear search
    setSearchQuery('');
    setSearchResults([]);
    setShowSearchResults(false);
    
    // The ChatBox will handle refreshing the playlist automatically
    setTimeout(() => {
      setIsLoading(false);
    }, 500);
  }, [sendMessage]);

  // Play song
  const handlePlaySong = useCallback((song: string) => {
    console.log('Playing song:', song); // Debug log
    sendMessage({ message: `/play ${song}` });
  }, [sendMessage]);

  // Show song deletion confirmation dialog
  const handleRemoveSongClick = useCallback((song: string) => {
    setSongToDelete(song);
    setSongDeleteDialogOpen(true);
  }, []);

  // Confirm song deletion
  const handleConfirmSongDelete = useCallback(() => {
    if (songToDelete) {
      setIsLoading(true);
      sendMessage({ message: `/remove ${songToDelete}` });
      
      // The ChatBox will handle refreshing the playlist automatically
      setTimeout(() => {
        setIsLoading(false);
      }, 500);
    }
    setSongDeleteDialogOpen(false);
    setSongToDelete('');
  }, [sendMessage, songToDelete]);

  // Cancel song deletion
  const handleCancelSongDelete = useCallback(() => {
    setSongDeleteDialogOpen(false);
    setSongToDelete('');
  }, []);

  // Clear entire playlist
  const handleClearPlaylist = useCallback(() => {
    setIsLoading(true);
    sendMessage({ message: '/clear' });
    
    // Auto-refresh playlist after clearing
    setTimeout(() => {
      sendMessage({ message: '/view' });
      setIsLoading(false);
    }, 500);
  }, [sendMessage]);

  // Refresh playlist
  const handleRefreshPlaylist = useCallback(() => {
    sendMessage({ message: '/view' });
  }, [sendMessage]);

  // Playlist management functions
  const handleCreatePlaylist = useCallback(() => {
    if (newPlaylistName.trim()) {
      console.log('Creating playlist:', newPlaylistName.trim()); // Debug log
      sendMessage({ message: `/create ${newPlaylistName.trim()}` });
      setCreateDialogOpen(false);
      setNewPlaylistName('');
    }
  }, [sendMessage, newPlaylistName]);

  const handleSwitchPlaylist = useCallback((playlistName: string) => {
    if (playlistName !== currentPlaylist) {
      sendMessage({ message: `/switch ${playlistName}` });
      // The backend will respond with updated playlist list and current playlist
    }
  }, [sendMessage, currentPlaylist]);

  const handleRenamePlaylist = useCallback(() => {
    if (renamePlaylistName.trim() && playlistToRename) {
      sendMessage({ message: `/rename ${playlistToRename} ${renamePlaylistName.trim()}` });
      setRenameDialogOpen(false);
      setRenamePlaylistName('');
      setPlaylistToRename('');
      // Refresh playlist list
      setTimeout(() => {
        sendMessage({ message: '/list' });
      }, 500);
    }
  }, [sendMessage, renamePlaylistName, playlistToRename]);

  // Show playlist deletion confirmation dialog
  const handleDeletePlaylistClick = useCallback((playlistName: string) => {
    setPlaylistToDelete(playlistName);
    setPlaylistDeleteDialogOpen(true);
  }, []);

  // Confirm playlist deletion
  const handleConfirmPlaylistDelete = useCallback(() => {
    if (playlistToDelete && playlists.length > 1) {
      sendMessage({ message: `/delete ${playlistToDelete}` });
      // Refresh playlist list
      setTimeout(() => {
        sendMessage({ message: '/list' });
      }, 500);
    }
    setPlaylistDeleteDialogOpen(false);
    setPlaylistToDelete('');
  }, [sendMessage, playlistToDelete, playlists.length]);

  // Cancel playlist deletion
  const handleCancelPlaylistDelete = useCallback(() => {
    setPlaylistDeleteDialogOpen(false);
    setPlaylistToDelete('');
  }, []);

  const handleMenuOpen = useCallback((event: React.MouseEvent<HTMLElement>) => {
    setMenuAnchor(event.currentTarget);
  }, []);

  const handleMenuClose = useCallback(() => {
    setMenuAnchor(null);
  }, []);

  // Load available songs
  const handleLoadSongs = useCallback(() => {
    sendMessage({ message: '/help' });
  }, [sendMessage]);

  // Format song display
  const formatSongDisplay = (song: string) => {
    const [artist, title] = song.split(':');
    return {
      artist: artist?.trim() || 'Unknown Artist',
      title: title?.trim() || 'Unknown Title',
      full: song
    };
  };

  // Get artist initials for avatar
  const getArtistInitials = (artist: string) => {
    return artist
      .split(' ')
      .map(word => word.charAt(0))
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  return (
    <Box sx={{ 
      height: '100%', 
      backgroundColor: '#ffffff', 
      color: '#333333',
      display: 'flex',
      flexDirection: 'column'
    }}>
        {/* Header */}
        <Box sx={{ p: 2, pb: 1, flexShrink: 0, borderBottom: '1px solid #e0e0e0' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <QueueIcon sx={{ mr: 1, color: '#1db954' }} />
              <Typography variant="h6" component="h2" sx={{ fontWeight: 'bold' }}>
                Music Playlist
              </Typography>
            </Box>
            <IconButton
              onClick={handleMenuOpen}
              size="small"
              sx={{ color: '#1db954' }}
            >
              <MoreVertIcon />
            </IconButton>
          </Box>
          
          {/* Action Buttons */}
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <Button
              variant="contained"
              startIcon={<RefreshIcon />}
              onClick={handleRefreshPlaylist}
              size="small"
              sx={{ backgroundColor: '#1db954', '&:hover': { backgroundColor: '#1ed760' } }}
            >
              Refresh
            </Button>
            <Button
              variant="outlined"
              startIcon={<CreateIcon />}
              onClick={() => setCreateDialogOpen(true)}
              size="small"
              sx={{ borderColor: '#1db954', color: '#1db954' }}
            >
              New
            </Button>
            <Button
              variant="outlined"
              startIcon={<ClearIcon />}
              onClick={handleClearPlaylist}
              disabled={playlist.length === 0}
              size="small"
              sx={{ borderColor: '#ff4444', color: '#ff4444' }}
            >
              Clear
            </Button>
          </Box>
        </Box>

        {/* Main Content - Horizontal Layout */}
        <Box sx={{ 
          flex: 1, 
          display: 'flex', 
          overflow: 'hidden',
          minHeight: 0
        }}>
          {/* Left Side - Playlists */}
          <Box sx={{ 
            width: '40%', 
            borderRight: '1px solid #e0e0e0',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden'
          }}>
            {/* Playlist Cover */}
            <Box sx={{ 
              px: 2, 
              py: 2, 
              textAlign: 'center', 
              borderBottom: '1px solid #e0e0e0',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '120px' // Fixed height to prevent spacing issues
            }}>
              <PlaylistCover
                playlistName={currentPlaylist}
                songCount={playlist.length}
                size="small"
                showSongCount={true}
                songs={playlist} // Pass songs for album artwork
                generatedCoverImage={generatedCoverImage}
              />
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1, textAlign: 'center' }}>
                {playlist.length} songs in {currentPlaylist || 'My Playlist'}
              </Typography>
              {playlist.length > 0 && (
                <Box sx={{ mt: 1, display: 'flex', justifyContent: 'center', gap: 2 }}>
                  <Chip 
                    label={`${new Set(playlist.map(song => song.split(':')[0].trim())).size} artists`}
                    size="small"
                    sx={{ 
                      backgroundColor: '#e8f5e8', 
                      color: '#1db954', 
                      fontSize: '0.7rem',
                      height: '20px'
                    }}
                  />
                  <Chip 
                    label={`${playlist.length > 0 ? Math.round((new Set(playlist.map(song => song.split(':')[0].trim())).size / playlist.length) * 100) : 0}% diverse`}
                    size="small"
                    sx={{ 
                      backgroundColor: '#e8f5e8', 
                      color: '#1db954', 
                      fontSize: '0.7rem',
                      height: '20px'
                    }}
                  />
                </Box>
              )}
            </Box>
            
            {/* Playlist List */}
            <Box sx={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <Typography variant="subtitle1" sx={{ px: 2, py: 2, pb: 1, fontWeight: 'bold', color: '#333333' }}>
                Your Playlists
              </Typography>
              <Box sx={{ flex: 1, overflow: 'auto', px: 2 }}>
                {playlists.length === 0 ? (
                  <Box sx={{ textAlign: 'center', py: 4 }}>
                    <MusicIcon sx={{ fontSize: 48, color: '#404040', mb: 1 }} />
                    <Typography variant="body2" color="text.secondary">
                      No playlists yet
                    </Typography>
                  </Box>
                ) : (
                  <List sx={{ p: 0 }}>
                    {playlists.map((playlistItem) => (
                      <ListItem
                        key={playlistItem.name}
                        onClick={() => handleSwitchPlaylist(playlistItem.name)}
                        sx={{
                          cursor: 'pointer',
                          borderRadius: 1,
                          mb: 1,
                          backgroundColor: playlistItem.name === currentPlaylist ? '#e8f5e8' : 'transparent',
                          border: playlistItem.name === currentPlaylist ? '1px solid #1db954' : '1px solid transparent',
                          '&:hover': {
                            backgroundColor: playlistItem.name === currentPlaylist ? '#e8f5e8' : '#f5f5f5',
                          },
                        }}
                      >
                        <ListItemIcon sx={{ minWidth: 36 }}>
                          <MusicIcon sx={{ color: playlistItem.name === currentPlaylist ? '#1db954' : '#666666' }} />
                        </ListItemIcon>
                        <ListItemText
                          primary={playlistItem.name}
                          secondary={`${playlistItem.songs.length} songs`}
                          primaryTypographyProps={{
                            sx: { 
                              color: playlistItem.name === currentPlaylist ? '#1db954' : '#333333', 
                              fontSize: '0.9rem',
                              fontWeight: playlistItem.name === currentPlaylist ? 'bold' : 'normal'
                            },
                          }}
                          secondaryTypographyProps={{
                            sx: { color: '#666666', fontSize: '0.8rem' },
                          }}
                        />
                      </ListItem>
                    ))}
                  </List>
                )}
              </Box>
            </Box>
          </Box>

          {/* Right Side - Songs */}
          <Box sx={{ 
            flex: 1, 
            display: 'flex', 
            flexDirection: 'column',
            overflow: 'hidden'
          }}>
            {/* Search Section */}
            <Box sx={{ px: 2, py: 2, pb: 2.5, borderBottom: '1px solid #e0e0e0' }}>
              <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 'bold', color: '#333333' }}>
                Add Songs
              </Typography>
              <TextField
                fullWidth
                placeholder="Search songs, artists..."
                value={searchQuery}
                onChange={handleSearchChange}
                size="small"
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon sx={{ color: '#b3b3b3' }} />
                    </InputAdornment>
                  ),
                }}
                sx={{
                  '& .MuiOutlinedInput-root': {
                    backgroundColor: '#ffffff',
                    '& fieldset': {
                      borderColor: '#cccccc',
                    },
                    '&:hover fieldset': {
                      borderColor: '#1db954',
                    },
                    '&.Mui-focused fieldset': {
                      borderColor: '#1db954',
                    },
                  },
                }}
              />

              {/* Loading Indicator for Song Database */}
              {availableSongs.length === 0 && (
                <Box sx={{ mt: 1, textAlign: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    Loading song database...
                  </Typography>
                  <CircularProgress size={16} sx={{ mt: 0.5, color: '#1db954' }} />
                  <Button 
                    size="small" 
                    onClick={() => sendMessage({ message: '/help' })}
                    sx={{ mt: 1, fontSize: '0.75rem' }}
                  >
                    Retry
                  </Button>
                </Box>
              )}

              {/* Search Results */}
              <Fade in={showSearchResults}>
                <Box sx={{ 
                  mt: 1, 
                  maxHeight: '200px', 
                  overflowY: 'auto',
                  '&::-webkit-scrollbar': {
                    width: '6px',
                  },
                  '&::-webkit-scrollbar-track': {
                    backgroundColor: '#f1f1f1',
                    borderRadius: '3px',
                  },
                  '&::-webkit-scrollbar-thumb': {
                    backgroundColor: '#c1c1c1',
                    borderRadius: '3px',
                    '&:hover': {
                      backgroundColor: '#a8a8a8',
                    },
                  },
                }}>
                  {searchResults.map((song, index) => {
                    const { artist, title } = formatSongDisplay(song);
                    return (
                      <Box
                        key={index}
                        sx={{
                          p: 1.5,
                          mb: 0.5,
                          backgroundColor: '#ffffff',
                          cursor: 'pointer',
                          border: '1px solid #e0e0e0',
                          borderRadius: 1,
                          '&:hover': {
                            backgroundColor: '#f0f0f0',
                          },
                        }}
                        onClick={() => handleAddSong(song)}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center' }}>
                          <Avatar
                            sx={{
                              width: 32,
                              height: 32,
                              backgroundColor: '#1db954',
                              mr: 1.5,
                              fontSize: '0.7rem',
                            }}
                          >
                            {getArtistInitials(artist)}
                          </Avatar>
                          <Box sx={{ flex: 1 }}>
                            <Typography variant="body2" sx={{ color: '#333333', fontWeight: 'bold', lineHeight: 1.2 }}>
                              {title}
                            </Typography>
                            <Typography variant="caption" sx={{ color: '#666666', lineHeight: 1.2 }}>
                              {artist}
                            </Typography>
                          </Box>
                          <Tooltip title="Play song">
                            <IconButton 
                              size="small" 
                              sx={{ color: '#1db954', mr: 0.5 }}
                              onClick={(e) => {
                                e.stopPropagation();
                                handlePlaySong(song);
                              }}
                            >
                              <PlayIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title="Add to playlist">
                            <IconButton 
                              size="small" 
                              sx={{ color: '#1db954' }}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleAddSong(song);
                              }}
                            >
                              <AddIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        </Box>
                      </Box>
                    );
                  })}
                </Box>
              </Fade>
            </Box>

            {/* Playlist Statistics */}
            {playlist.length > 0 && (
              <Box sx={{ px: 2, py: 2, borderBottom: '1px solid #e0e0e0', backgroundColor: '#f8f9fa' }}>
                <Typography variant="subtitle2" sx={{ mb: 1.5, fontWeight: 'bold', color: '#333333', display: 'flex', alignItems: 'center', gap: 1 }}>
                  <QueueIcon fontSize="small" />
                  Playlist Statistics
                </Typography>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                  {/* Basic Stats */}
                  <Box sx={{ display: 'flex', flexDirection: 'column', minWidth: '80px' }}>
                    <Typography variant="h6" sx={{ color: '#1db954', fontWeight: 'bold', lineHeight: 1 }}>
                      {playlist.length}
                    </Typography>
                    <Typography variant="caption" sx={{ color: '#666666', fontSize: '0.7rem' }}>
                      Total Songs
                    </Typography>
                  </Box>
                  
                  {/* Unique Artists */}
                  <Box sx={{ display: 'flex', flexDirection: 'column', minWidth: '80px' }}>
                    <Typography variant="h6" sx={{ color: '#1db954', fontWeight: 'bold', lineHeight: 1 }}>
                      {new Set(playlist.map(song => song.split(':')[0].trim())).size}
                    </Typography>
                    <Typography variant="caption" sx={{ color: '#666666', fontSize: '0.7rem' }}>
                      Unique Artists
                    </Typography>
                  </Box>
                  
                  {/* Diversity Score */}
                  <Box sx={{ display: 'flex', flexDirection: 'column', minWidth: '80px' }}>
                    <Typography variant="h6" sx={{ color: '#1db954', fontWeight: 'bold', lineHeight: 1 }}>
                      {playlist.length > 0 ? Math.round((new Set(playlist.map(song => song.split(':')[0].trim())).size / playlist.length) * 100) : 0}%
                    </Typography>
                    <Typography variant="caption" sx={{ color: '#666666', fontSize: '0.7rem' }}>
                      Diversity
                    </Typography>
                  </Box>
                  
                  {/* Top Artist */}
                  {(() => {
                    const artistCounts: {[key: string]: number} = {};
                    playlist.forEach(song => {
                      const artist = song.split(':')[0].trim();
                      artistCounts[artist] = (artistCounts[artist] || 0) + 1;
                    });
                    const topArtist = Object.entries(artistCounts).sort(([,a], [,b]) => b - a)[0];
                    return topArtist ? (
                      <Box sx={{ display: 'flex', flexDirection: 'column', minWidth: '120px' }}>
                        <Typography variant="body2" sx={{ color: '#333333', fontWeight: 'bold', lineHeight: 1, fontSize: '0.8rem' }}>
                          {topArtist[0]}
                        </Typography>
                        <Typography variant="caption" sx={{ color: '#666666', fontSize: '0.7rem' }}>
                          Top Artist ({topArtist[1]} songs)
                        </Typography>
                      </Box>
                    ) : null;
                  })()}
                </Box>
              </Box>
            )}

            {/* Current Playlist Songs */}
            <Box sx={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <Typography variant="subtitle1" sx={{ p: 2, pb: 1, fontWeight: 'bold', color: '#333333' }}>
                Current Playlist
              </Typography>
              
              {playlist.length === 0 ? (
                <Box sx={{ textAlign: 'center', py: 4, px: 2 }}>
                  <MusicIcon sx={{ fontSize: 48, color: '#404040', mb: 1 }} />
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Your playlist is empty
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Search for songs above to add them
                  </Typography>
                </Box>
              ) : (
                <Box sx={{ flex: 1, overflow: 'auto', px: 2 }}>
                  <List sx={{ p: 0 }}>
                    {playlist.map((song, index) => {
                      const { artist, title } = formatSongDisplay(song);
                      return (
                        <ListItem
                          key={index}
                          sx={{
                            backgroundColor: '#f5f5f5',
                            mb: 0.5,
                            borderRadius: 1,
                            border: '1px solid #e0e0e0',
                            px: 1.5,
                            py: 0.5,
                            '&:hover': {
                              backgroundColor: '#eeeeee',
                            },
                          }}
                        >
                          <Avatar
                            sx={{
                              width: 28,
                              height: 28,
                              backgroundColor: '#1db954',
                              mr: 1.5,
                              fontSize: '0.6rem',
                            }}
                          >
                            {getArtistInitials(artist)}
                          </Avatar>
                          <ListItemText
                            primary={title}
                            secondary={artist}
                            primaryTypographyProps={{
                              sx: { color: '#333333', fontSize: '0.85rem', lineHeight: 1.2 },
                            }}
                            secondaryTypographyProps={{
                              sx: { color: '#666666', fontSize: '0.75rem', lineHeight: 1.2 },
                            }}
                          />
                          <Tooltip title="Play song">
                            <IconButton
                              onClick={() => handlePlaySong(song)}
                              disabled={isLoading}
                              size="small"
                              sx={{ color: '#1db954', ml: 0.5 }}
                            >
                              <PlayIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title="Remove from playlist">
                            <IconButton
                              onClick={() => handleRemoveSongClick(song)}
                              disabled={isLoading}
                              size="small"
                              sx={{ color: '#ff4444', ml: 0.5 }}
                            >
                              <DeleteIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        </ListItem>
                      );
                    })}
                  </List>
                </Box>
              )}
            </Box>
          </Box>
        </Box>

        {/* Loading Indicator */}
        {isLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
            <CircularProgress size={24} sx={{ color: '#1db954' }} />
            <Typography variant="body2" sx={{ ml: 1, color: '#666666' }}>
              Updating playlist...
            </Typography>
          </Box>
        )}

        {/* Error Display */}
        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}

        {/* Create Playlist Dialog */}
        <Dialog open={createDialogOpen} onClose={() => setCreateDialogOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>Create New Playlist</DialogTitle>
          <DialogContent>
            <TextField
              autoFocus
              margin="dense"
              label="Playlist Name"
              fullWidth
              variant="outlined"
              value={newPlaylistName}
              onChange={(e) => setNewPlaylistName(e.target.value)}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  handleCreatePlaylist();
                }
              }}
              sx={{
                '& .MuiOutlinedInput-notchedOutline': {
                  borderColor: '#1db954',
                },
                '&:hover .MuiOutlinedInput-notchedOutline': {
                  borderColor: '#1ed760',
                },
                '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
                  borderColor: '#1db954',
                },
              }}
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setCreateDialogOpen(false)} color="inherit">
              Cancel
            </Button>
            <Button 
              onClick={handleCreatePlaylist} 
              variant="contained"
              sx={{ backgroundColor: '#1db954', '&:hover': { backgroundColor: '#1ed760' } }}
              disabled={!newPlaylistName.trim()}
            >
              Create
            </Button>
          </DialogActions>
        </Dialog>

        {/* Rename Playlist Dialog */}
        <Dialog open={renameDialogOpen} onClose={() => setRenameDialogOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>Rename Playlist</DialogTitle>
          <DialogContent>
            <TextField
              autoFocus
              margin="dense"
              label="New Playlist Name"
              fullWidth
              variant="outlined"
              value={renamePlaylistName}
              onChange={(e) => setRenamePlaylistName(e.target.value)}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  handleRenamePlaylist();
                }
              }}
              sx={{
                '& .MuiOutlinedInput-notchedOutline': {
                  borderColor: '#1db954',
                },
                '&:hover .MuiOutlinedInput-notchedOutline': {
                  borderColor: '#1ed760',
                },
                '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
                  borderColor: '#1db954',
                },
              }}
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setRenameDialogOpen(false)} color="inherit">
              Cancel
            </Button>
            <Button 
              onClick={handleRenamePlaylist} 
              variant="contained"
              sx={{ backgroundColor: '#1db954', '&:hover': { backgroundColor: '#1ed760' } }}
              disabled={!renamePlaylistName.trim()}
            >
              Rename
            </Button>
          </DialogActions>
        </Dialog>

        {/* Playlist Management Menu */}
        <Menu
          anchorEl={menuAnchor}
          open={Boolean(menuAnchor)}
          onClose={handleMenuClose}
          PaperProps={{
            sx: {
              minWidth: 200,
            }
          }}
        >
          <MenuItem onClick={() => {
            setCreateDialogOpen(true);
            handleMenuClose();
          }}>
            <ListItemIcon>
              <CreateIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Create New Playlist</ListItemText>
          </MenuItem>
          <MenuItem onClick={() => {
            sendMessage({ message: '/list' });
            handleMenuClose();
          }}>
            <ListItemIcon>
              <QueueIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>List All Playlists</ListItemText>
          </MenuItem>
          <Divider />
          <MenuItem 
            onClick={() => {
              setPlaylistToRename(currentPlaylist);
              setRenamePlaylistName(currentPlaylist);
              setRenameDialogOpen(true);
              handleMenuClose();
            }}
            disabled={playlists.length === 0}
          >
            <ListItemIcon>
              <EditIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Rename Current Playlist</ListItemText>
          </MenuItem>
          <MenuItem 
            onClick={() => {
              handleDeletePlaylistClick(currentPlaylist);
              handleMenuClose();
            }}
            disabled={playlists.length <= 1}
            sx={{ color: '#ff4444' }}
          >
            <ListItemIcon>
              <DeleteIcon fontSize="small" sx={{ color: '#ff4444' }} />
            </ListItemIcon>
            <ListItemText>Delete Current Playlist</ListItemText>
          </MenuItem>
        </Menu>

        {/* Song Deletion Confirmation Dialog */}
        <Dialog 
          open={songDeleteDialogOpen} 
          onClose={handleCancelSongDelete}
          maxWidth="sm" 
          fullWidth
        >
          <DialogTitle sx={{ color: '#ff4444' }}>
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <DeleteIcon sx={{ mr: 1 }} />
              Remove Song
            </Box>
          </DialogTitle>
          <DialogContent>
            <Typography variant="body1">
              Are you sure you want to remove this song from your playlist?
            </Typography>
            {songToDelete && (
              <Box sx={{ mt: 2, p: 2, backgroundColor: '#f5f5f5', borderRadius: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                  {songToDelete.split(':')[1]?.trim() || 'Unknown Title'}
                </Typography>
                <Typography variant="body2" sx={{ color: '#666666' }}>
                  {songToDelete.split(':')[0]?.trim() || 'Unknown Artist'}
                </Typography>
              </Box>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={handleCancelSongDelete} color="inherit">
              Cancel
            </Button>
            <Button 
              onClick={handleConfirmSongDelete} 
              variant="contained"
              sx={{ backgroundColor: '#ff4444', '&:hover': { backgroundColor: '#d32f2f' } }}
            >
              Remove Song
            </Button>
          </DialogActions>
        </Dialog>

        {/* Playlist Deletion Confirmation Dialog */}
        <Dialog 
          open={playlistDeleteDialogOpen} 
          onClose={handleCancelPlaylistDelete}
          maxWidth="sm" 
          fullWidth
        >
          <DialogTitle sx={{ color: '#ff4444' }}>
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <DeleteIcon sx={{ mr: 1 }} />
              Delete Playlist
            </Box>
          </DialogTitle>
          <DialogContent>
            <Typography variant="body1" sx={{ mb: 2 }}>
              Are you sure you want to delete this playlist? This action cannot be undone.
            </Typography>
            {playlistToDelete && (
              <Box sx={{ p: 2, backgroundColor: '#f5f5f5', borderRadius: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                  {playlistToDelete}
                </Typography>
                <Typography variant="body2" sx={{ color: '#666666' }}>
                  {playlists.find(p => p.name === playlistToDelete)?.songs.length || 0} songs
                </Typography>
              </Box>
            )}
            <Alert severity="warning" sx={{ mt: 2 }}>
              If this is your current playlist, you will be switched to another playlist automatically.
            </Alert>
          </DialogContent>
          <DialogActions>
            <Button onClick={handleCancelPlaylistDelete} color="inherit">
              Cancel
            </Button>
            <Button 
              onClick={handleConfirmPlaylistDelete} 
              variant="contained"
              sx={{ backgroundColor: '#ff4444', '&:hover': { backgroundColor: '#d32f2f' } }}
            >
              Delete Playlist
            </Button>
          </DialogActions>
        </Dialog>
    </Box>
  );
}
