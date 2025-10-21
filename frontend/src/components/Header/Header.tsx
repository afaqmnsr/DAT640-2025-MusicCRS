import React from 'react';
import {
  AppBar,
  Toolbar,
  Typography,
  Box,
  IconButton,
  Avatar,
  Chip,
} from '@mui/material';
import {
  MusicNote as MusicIcon,
  QueueMusic as QueueIcon,
  SmartToy as RobotIcon,
} from '@mui/icons-material';

interface HeaderProps {
  username?: string;
}

export default function Header({ username }: HeaderProps) {
  return (
    <AppBar 
      position="static" 
      sx={{ 
        backgroundColor: '#1db954',
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
      }}
    >
      <Toolbar sx={{ justifyContent: 'space-between', py: 1 }}>
        {/* Left side - Logo and Title */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <MusicIcon sx={{ fontSize: 28, color: 'white' }} />
            <Typography 
              variant="h5" 
              component="h1" 
              sx={{ 
                fontWeight: 'bold',
                color: 'white',
                letterSpacing: '0.5px',
              }}
            >
              MusicCRS
            </Typography>
          </Box>
          <Chip
            label="Music Recommendation System"
            size="small"
            sx={{
              backgroundColor: 'rgba(255,255,255,0.2)',
              color: 'white',
              fontWeight: 500,
              fontSize: '0.75rem',
            }}
          />
        </Box>

        {/* Right side - User info */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <QueueIcon sx={{ fontSize: 20, color: 'rgba(255,255,255,0.8)' }} />
            <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.9)' }}>
              Playlist Manager
            </Typography>
          </Box>
          
          {username && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Avatar sx={{ width: 32, height: 32, backgroundColor: 'rgba(255,255,255,0.2)' }}>
                <RobotIcon sx={{ fontSize: 18 }} />
              </Avatar>
              <Typography variant="body2" sx={{ color: 'white', fontWeight: 500 }}>
                {username}
              </Typography>
            </Box>
          )}
        </Box>
      </Toolbar>
    </AppBar>
  );
}