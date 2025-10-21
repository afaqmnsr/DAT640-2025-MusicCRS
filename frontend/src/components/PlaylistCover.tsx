import React, { useState, useEffect, useRef } from 'react';
import { Box, Avatar, Typography, CircularProgress, Dialog, DialogContent, IconButton } from '@mui/material';
import { MusicNote as MusicIcon, ImageNotSupported as NoImageIcon, Close as CloseIcon } from '@mui/icons-material';
import { useSocket } from '../contexts/SocketContext';

interface PlaylistCoverProps {
  playlistName: string;
  songCount: number;
  size?: 'small' | 'medium' | 'large';
  showSongCount?: boolean;
  songs?: string[]; // Add songs prop to get album artwork
  generatedCoverImage?: string | null; // Generated cover image from parent
}

const PlaylistCover = React.memo(({ 
  playlistName, 
  songCount, 
  size = 'medium',
  showSongCount = true,
  songs = [],
  generatedCoverImage: propGeneratedCoverImage
}: PlaylistCoverProps) => {
  const [isGeneratingImage, setIsGeneratingImage] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const { sendMessage } = useSocket();
  const hasRequestedCover = useRef<string | null>(null);
  
  // Use the generated cover image from props
  const generatedImage = propGeneratedCoverImage;

  // Debug logging to track updates
  console.log('PlaylistCover render:', { 
    playlistName, 
    songCount, 
    size, 
    showSongCount,
    generatedImage: generatedImage ? 'present' : 'null',
    isGeneratingImage,
    imageError
  });

  // Generate playlist cover using the backend service via socket
  const generatePlaylistCover = async () => {
    if (!playlistName || songs.length === 0) return;
    
    try {
      console.log('Requesting cover generation for:', playlistName, 'with', songs.length, 'songs');
      setIsGeneratingImage(true);
      setImageError(false);
      
      // Send cover generation request via socket
      sendMessage({ message: `/cover ${playlistName}` });
      
    } catch (error) {
      console.log('Error requesting playlist cover:', error);
      setImageError(true);
      setIsGeneratingImage(false);
    }
  };

  // Generate cover when playlist changes and no image is available
  useEffect(() => {
    const requestKey = `${playlistName}-${songs.length}`;
    
    if (playlistName && songs.length > 0 && !generatedImage && !isGeneratingImage && !imageError && hasRequestedCover.current !== requestKey) {
      console.log('Requesting cover generation for:', playlistName, 'with', songs.length, 'songs');
      hasRequestedCover.current = requestKey;
      generatePlaylistCover();
    }
  }, [playlistName, songs.length, generatedImage, isGeneratingImage, imageError]);

  // Handle when generated cover image prop changes
  useEffect(() => {
    if (propGeneratedCoverImage) {
      console.log('Received generated cover image from parent');
      setIsGeneratingImage(false);
      setImageError(false);
    }
  }, [propGeneratedCoverImage]);

  // Lightbox handlers
  const handleOpenLightbox = () => {
    if (generatedImage) {
      setLightboxOpen(true);
    }
  };

  const handleCloseLightbox = () => {
    setLightboxOpen(false);
  };

  // Generate a consistent color based on playlist name
  const generateColorFromName = (name: string): string => {
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    
    // Convert hash to HSL values for better color generation
    const hue = Math.abs(hash) % 360;
    const saturation = 70 + (Math.abs(hash) % 25); // 70-95% saturation
    const lightness = 40 + (Math.abs(hash) % 25); // 40-65% lightness
    
    return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
  };

  // Generate gradient colors with better contrast
  const primaryColor = generateColorFromName(playlistName);
  const secondaryColor = generateColorFromName(playlistName + 'secondary');
  const accentColor = generateColorFromName(playlistName + 'accent');

  // Size configurations
  const sizeConfig = {
    small: { width: 60, height: 60, fontSize: '1.5rem', iconSize: 20 },
    medium: { width: 120, height: 120, fontSize: '2.5rem', iconSize: 40 },
    large: { width: 200, height: 200, fontSize: '4rem', iconSize: 80 }
  };

  const config = sizeConfig[size];

  // Get playlist initials
  const getInitials = (name: string): string => {
    return name
      .split(' ')
      .map(word => word.charAt(0))
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  // Generate a pattern based on song count
  const getPatternStyle = (): React.CSSProperties => {
    const patternSize = size === 'small' ? 8 : size === 'medium' ? 12 : 16;
    const opacity = 0.1;
    
    return {
      backgroundImage: `
        radial-gradient(circle at 25% 25%, rgba(255,255,255,${opacity}) ${patternSize}px, transparent ${patternSize}px),
        radial-gradient(circle at 75% 75%, rgba(255,255,255,${opacity}) ${patternSize}px, transparent ${patternSize}px),
        radial-gradient(circle at 50% 10%, rgba(255,255,255,${opacity}) ${patternSize}px, transparent ${patternSize}px),
        radial-gradient(circle at 10% 50%, rgba(255,255,255,${opacity}) ${patternSize}px, transparent ${patternSize}px),
        radial-gradient(circle at 90% 20%, rgba(255,255,255,${opacity}) ${patternSize}px, transparent ${patternSize}px)
      `,
      backgroundSize: `${patternSize * 2}px ${patternSize * 2}px`,
    };
  };

  return (
    <>
      <Box
        sx={{
          width: config.width,
          height: config.height,
          borderRadius: 3,
          background: generatedImage 
            ? `url(${generatedImage})` 
            : `linear-gradient(135deg, ${primaryColor} 0%, ${secondaryColor} 50%, ${accentColor} 100%)`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          backgroundRepeat: 'no-repeat',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
          overflow: 'hidden',
          boxShadow: '0 8px 24px rgba(0,0,0,0.2), 0 4px 8px rgba(0,0,0,0.1)',
          border: '3px solid rgba(255,255,255,0.3)',
          transition: 'transform 0.2s ease, box-shadow 0.2s ease',
          cursor: generatedImage ? 'pointer' : 'default',
          '&:hover': {
            transform: 'scale(1.02)',
            boxShadow: '0 12px 32px rgba(0,0,0,0.25), 0 6px 12px rgba(0,0,0,0.15)',
          },
          ...(!generatedImage ? getPatternStyle() : {}),
        }}
        onClick={handleOpenLightbox}
      >
      {/* Generated image overlay for better text readability */}
      {generatedImage && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'linear-gradient(135deg, rgba(0,0,0,0.3) 0%, rgba(0,0,0,0.1) 50%, rgba(0,0,0,0.4) 100%)',
            zIndex: 1,
          }}
        />
      )}


      {/* Loading indicator */}
      {isGeneratingImage && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'rgba(0,0,0,0.5)',
            zIndex: 4,
          }}
        >
          <CircularProgress size={20} sx={{ color: 'white' }} />
        </Box>
      )}

      {/* Main content */}
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 2,
          textAlign: 'center',
        }}
      >
        {/* Show initials only if no generated image or error */}
        {(!generatedImage || imageError) && (
          <Typography
            sx={{
              fontSize: config.fontSize,
              fontWeight: '900',
              color: 'white',
              textShadow: '0 3px 6px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.2)',
              lineHeight: 1,
              mb: size === 'small' ? 0.5 : 1,
              letterSpacing: '0.05em',
              fontFamily: 'system-ui, -apple-system, sans-serif',
            }}
          >
            {getInitials(playlistName)}
          </Typography>
        )}

        {/* Music icon - show only if no generated image */}
        {(!generatedImage || imageError) && (
          <MusicIcon
            sx={{
              fontSize: config.iconSize,
              color: 'rgba(255,255,255,0.9)',
              filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.4))',
              opacity: 0.8,
            }}
          />
        )}

        {/* Show error icon if image generation failed */}
        {imageError && (
          <NoImageIcon
            sx={{
              fontSize: config.iconSize * 0.6,
              color: 'rgba(255,255,255,0.7)',
              position: 'absolute',
              top: 4,
              right: 4,
              zIndex: 3,
            }}
          />
        )}
      </Box>

      {/* Song count badge */}
      {showSongCount && (
        <Box
          sx={{
            position: 'absolute',
            bottom: 6,
            right: 6,
            backgroundColor: songCount > 0 ? 'rgba(0,0,0,0.8)' : 'rgba(0,0,0,0.5)',
            color: 'white',
            borderRadius: '50%',
            width: size === 'small' ? 22 : size === 'medium' ? 28 : 36,
            height: size === 'small' ? 22 : size === 'medium' ? 28 : 36,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: size === 'small' ? '0.75rem' : size === 'medium' ? '0.9rem' : '1.1rem',
            fontWeight: 'bold',
            zIndex: 3,
            border: '2px solid rgba(255,255,255,0.3)',
            boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
            opacity: songCount > 0 ? 1 : 0.7,
          }}
        >
          {songCount}
        </Box>
      )}

      {/* Enhanced overlay gradient for depth - only if no generated image */}
      {!generatedImage && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'linear-gradient(135deg, rgba(255,255,255,0.15) 0%, rgba(0,0,0,0.1) 50%, rgba(0,0,0,0.2) 100%)',
            zIndex: 1,
          }}
        />
      )}

      {/* Subtle inner glow - only if no generated image */}
      {!generatedImage && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'radial-gradient(circle at 30% 30%, rgba(255,255,255,0.2) 0%, transparent 50%)',
            zIndex: 1,
          }}
        />
      )}
    </Box>

    {/* Lightbox Dialog */}
    <Dialog
      open={lightboxOpen}
      onClose={handleCloseLightbox}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: {
          backgroundColor: 'transparent',
          boxShadow: 'none',
          maxHeight: '90vh',
        }
      }}
    >
      <DialogContent
        sx={{
          padding: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'rgba(0, 0, 0, 0.9)',
          position: 'relative',
        }}
      >
        {/* Close button */}
        <IconButton
          onClick={handleCloseLightbox}
          sx={{
            position: 'absolute',
            top: 16,
            right: 16,
            color: 'white',
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            zIndex: 1,
            '&:hover': {
              backgroundColor: 'rgba(0, 0, 0, 0.7)',
            },
          }}
        >
          <CloseIcon />
        </IconButton>

        {/* Large cover image */}
        {generatedImage && (
          <Box
            sx={{
              width: '100%',
              height: '100%',
              minHeight: '400px',
              backgroundImage: `url(${generatedImage})`,
              backgroundSize: 'contain',
              backgroundRepeat: 'no-repeat',
              backgroundPosition: 'center',
              borderRadius: 2,
            }}
          />
        )}

        {/* Playlist info overlay */}
        <Box
          sx={{
            position: 'absolute',
            bottom: 16,
            left: 16,
            right: 16,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            borderRadius: 2,
            padding: 2,
            color: 'white',
            textAlign: 'center',
          }}
        >
          <Typography variant="h5" sx={{ fontWeight: 'bold', mb: 1 }}>
            {playlistName}
          </Typography>
          <Typography variant="body1" sx={{ opacity: 0.9 }}>
            {songCount} {songCount === 1 ? 'song' : 'songs'}
          </Typography>
        </Box>
      </DialogContent>
    </Dialog>
    </>
  );
});

PlaylistCover.displayName = 'PlaylistCover';

export default PlaylistCover;
