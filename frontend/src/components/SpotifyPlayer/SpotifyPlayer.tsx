import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  IconButton,
  Slider,
  CircularProgress,
  Alert,
  Chip,
} from '@mui/material';
import {
  PlayArrow as PlayIcon,
  Pause as PauseIcon,
  SkipNext as NextIcon,
  SkipPrevious as PreviousIcon,
  VolumeUp as VolumeIcon,
} from '@mui/icons-material';

interface SpotifyTrackInfo {
  song_key: string;
  artist: string;
  title: string;
  album: string;
  duration_ms: number;
  spotify_track_id: string;
  spotify_uri: string;
  playable: boolean;
}

interface SpotifyPlayerProps {
  trackInfo?: SpotifyTrackInfo | null;
  onTrackEnd?: () => void;
  accessToken?: string | null;
}

declare global {
  interface Window {
    Spotify: any;
    onSpotifyWebPlaybackSDKReady: () => void;
  }
}

export default function SpotifyPlayer({ trackInfo, onTrackEnd, accessToken }: SpotifyPlayerProps) {
  const [player, setPlayer] = useState<any>(null);
  const [deviceId, setDeviceId] = useState<string>('');
  const [isPlaying, setIsPlaying] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [isActive, setIsActive] = useState(false);
  const [currentTrack, setCurrentTrack] = useState<any>(null);
  const [volume, setVolume] = useState(50);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSDKReady, setIsSDKReady] = useState(false);
  
  const positionIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Initialize Spotify Web Playback SDK
  useEffect(() => {
    const script = document.createElement('script');
    script.src = 'https://sdk.scdn.co/spotify-player.js';
    script.async = true;
    document.body.appendChild(script);

    window.onSpotifyWebPlaybackSDKReady = () => {
      console.log('Spotify Web Playback SDK Ready');
      setIsSDKReady(true);
    };

    return () => {
      document.body.removeChild(script);
    };
  }, []);

  // Initialize player when SDK is ready
  useEffect(() => {
    if (!isSDKReady) return;

    const spotifyPlayer = new window.Spotify.Player({
      name: 'MusicCRS Player',
      getOAuthToken: (cb: (token: string) => void) => {
        if (accessToken) {
          cb(accessToken);
        } else {
          console.warn('No Spotify access token available');
          cb('');
        }
      },
      volume: volume / 100,
    });

    setPlayer(spotifyPlayer);

    // Ready
    spotifyPlayer.addListener('ready', ({ device_id }: { device_id: string }) => {
      console.log('Ready with Device ID', device_id);
      setDeviceId(device_id);
    });

    // Not Ready
    spotifyPlayer.addListener('not_ready', ({ device_id }: { device_id: string }) => {
      console.log('Device ID has gone offline', device_id);
    });

    // Player state changed
    spotifyPlayer.addListener('player_state_changed', (state: any) => {
      if (!state) return;

      setCurrentTrack(state.track_window.current_track);
      setIsPaused(state.paused);
      setPosition(state.position);
      setDuration(state.duration);

      spotifyPlayer.getCurrentState().then((state: any) => {
        if (!state) {
          setIsActive(false);
        } else {
          setIsActive(state);
        }
      });
    });

    // Connect to the player
    spotifyPlayer.connect();

    return () => {
      spotifyPlayer.disconnect();
    };
  }, [isSDKReady, volume]);

  // Update position periodically
  useEffect(() => {
    if (isPlaying && !isPaused) {
      positionIntervalRef.current = setInterval(() => {
        setPosition(prev => prev + 1000);
      }, 1000);
    } else {
      if (positionIntervalRef.current) {
        clearInterval(positionIntervalRef.current);
        positionIntervalRef.current = null;
      }
    }

    return () => {
      if (positionIntervalRef.current) {
        clearInterval(positionIntervalRef.current);
      }
    };
  }, [isPlaying, isPaused]);

  // Play track when trackInfo changes
  useEffect(() => {
    if (trackInfo && trackInfo.playable && player && deviceId) {
      playTrack(trackInfo.spotify_uri);
    }
  }, [trackInfo, player, deviceId]);

  const playTrack = async (spotifyUri: string) => {
    if (!player || !deviceId) return;

    setIsLoading(true);
    setError(null);

    try {
      // In a real implementation, you'd make an API call to your backend
      // to start playback using the Spotify Web API
      console.log('Playing track:', spotifyUri);
      
      // For demo purposes, we'll simulate playback
      setTimeout(() => {
        setIsPlaying(true);
        setIsPaused(false);
        setIsLoading(false);
      }, 1000);
    } catch (err) {
      setError('Failed to play track');
      setIsLoading(false);
    }
  };

  const togglePlay = () => {
    if (!player) return;

    if (isPaused) {
      player.resume();
      setIsPaused(false);
    } else {
      player.pause();
      setIsPaused(true);
    }
  };

  const nextTrack = () => {
    if (!player) return;
    player.nextTrack();
  };

  const previousTrack = () => {
    if (!player) return;
    player.previousTrack();
  };

  const handleVolumeChange = (event: Event, newValue: number | number[]) => {
    const newVolume = newValue as number;
    setVolume(newVolume);
    if (player) {
      player.setVolume(newVolume / 100);
    }
  };

  const handlePositionChange = (event: Event, newValue: number | number[]) => {
    const newPosition = newValue as number;
    setPosition(newPosition);
    if (player) {
      player.seek(newPosition);
    }
  };

  const formatTime = (ms: number) => {
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  if (!isSDKReady) {
    return (
      <Card sx={{ maxWidth: 400, mx: 'auto', mt: 2 }}>
        <CardContent>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', p: 2 }}>
            <CircularProgress size={24} sx={{ mr: 1 }} />
            <Typography variant="body2">Loading Spotify Player...</Typography>
          </Box>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card sx={{ maxWidth: 400, mx: 'auto', mt: 2 }}>
        <CardContent>
          <Alert severity="error">{error}</Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card sx={{ maxWidth: 400, mx: 'auto', mt: 2 }}>
      <CardContent>
        {trackInfo ? (
          <>
            {/* Track Info */}
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
              <Box sx={{ flex: 1 }}>
                <Typography variant="h6" noWrap>
                  {trackInfo.title}
                </Typography>
                <Typography variant="body2" color="text.secondary" noWrap>
                  {trackInfo.artist}
                </Typography>
                {trackInfo.album && (
                  <Typography variant="caption" color="text.secondary">
                    {trackInfo.album}
                  </Typography>
                )}
              </Box>
              {trackInfo.playable ? (
                <Chip label="Playable" color="success" size="small" />
              ) : (
                <Chip label="Not Available" color="error" size="small" />
              )}
            </Box>

            {/* Progress Bar */}
            <Box sx={{ mb: 2 }}>
              <Slider
                value={position}
                min={0}
                max={duration || trackInfo.duration_ms}
                onChange={handlePositionChange}
                disabled={!trackInfo.playable}
                sx={{ color: '#1db954' }}
              />
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 0.5 }}>
                <Typography variant="caption">
                  {formatTime(position)}
                </Typography>
                <Typography variant="caption">
                  {formatTime(duration || trackInfo.duration_ms)}
                </Typography>
              </Box>
            </Box>

            {/* Controls */}
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', mb: 2 }}>
              <IconButton onClick={previousTrack} disabled={!trackInfo.playable}>
                <PreviousIcon />
              </IconButton>
              
              <IconButton 
                onClick={togglePlay} 
                disabled={!trackInfo.playable || isLoading}
                sx={{ 
                  backgroundColor: '#1db954', 
                  color: 'white',
                  '&:hover': { backgroundColor: '#1ed760' },
                  mx: 1
                }}
              >
                {isLoading ? (
                  <CircularProgress size={24} color="inherit" />
                ) : isPaused ? (
                  <PlayIcon />
                ) : (
                  <PauseIcon />
                )}
              </IconButton>
              
              <IconButton onClick={nextTrack} disabled={!trackInfo.playable}>
                <NextIcon />
              </IconButton>
            </Box>

            {/* Volume Control */}
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <VolumeIcon sx={{ mr: 1, color: 'text.secondary' }} />
              <Slider
                value={volume}
                min={0}
                max={100}
                onChange={handleVolumeChange}
                sx={{ flex: 1, color: '#1db954' }}
              />
            </Box>
          </>
        ) : (
          <Box sx={{ textAlign: 'center', p: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Select a song to play
            </Typography>
            {!accessToken && (
              <Box sx={{ mt: 2 }}>
                <Alert severity="info" sx={{ mb: 2 }}>
                  Spotify authentication required for playback
                </Alert>
                <Typography variant="body2" color="text.secondary">
                  Use /spotify_login in the chat to authenticate with Spotify
                </Typography>
              </Box>
            )}
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
