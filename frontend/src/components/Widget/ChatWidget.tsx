import { useState, MouseEvent, ReactNode } from "react";
import { Box, Fab, Slide, Paper, IconButton, Typography } from '@mui/material';
import { SmartToy as RobotIcon, Close as CloseIcon, Chat as ChatIcon } from '@mui/icons-material';

export default function ChatWidget({ children }: { children: ReactNode }) {
  const [isChatBoxOpen, setIsChatBoxOpen] = useState<boolean>(false);

  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    setIsChatBoxOpen(!isChatBoxOpen);
  }

  function handleClose() {
    setIsChatBoxOpen(false);
  }

  return (
    <Box sx={{ position: 'relative', height: '100vh' }}>
      {/* Chat Widget Icon */}
      <Fab
        color="primary"
        onClick={handleClick}
        sx={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          zIndex: 1000,
          transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
          '&:hover': {
            transform: 'scale(1.1)',
            boxShadow: '0 8px 25px rgba(0,0,0,0.15)',
          },
          ...(isChatBoxOpen && {
            transform: 'rotate(180deg)',
            backgroundColor: '#ff4444',
            '&:hover': {
              backgroundColor: '#ff3333',
            },
          }),
        }}
      >
        {isChatBoxOpen ? <CloseIcon /> : <ChatIcon />}
      </Fab>
      
      {/* Chat Box */}
      <Slide 
        direction="up" 
        in={isChatBoxOpen} 
        mountOnEnter 
        unmountOnExit
        timeout={300}
      >
        <Paper
          elevation={8}
          sx={{
            position: 'fixed',
            bottom: 100,
            right: 24,
            width: 400,
            height: 600,
            zIndex: 999,
            borderRadius: 3,
            overflow: 'hidden',
            boxShadow: '0 20px 40px rgba(0,0,0,0.15)',
            border: '1px solid rgba(255,255,255,0.2)',
            backdropFilter: 'blur(10px)',
            backgroundColor: 'rgba(255,255,255,0.95)',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* Chat Header */}
          <Box sx={{ 
            p: 2, 
            borderBottom: '1px solid #e0e0e0',
            backgroundColor: 'primary.main',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between'
          }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <RobotIcon />
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                Music Assistant
              </Typography>
            </Box>
            <IconButton 
              onClick={handleClose}
              sx={{ 
                color: 'white',
                '&:hover': {
                  backgroundColor: 'rgba(255,255,255,0.1)',
                }
              }}
            >
              <CloseIcon />
            </IconButton>
          </Box>
          
          {/* Chat Content */}
          <Box sx={{ flex: 1, overflow: 'hidden' }}>
            {children}
          </Box>
        </Paper>
      </Slide>
    </Box>
  );
}
