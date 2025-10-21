import { useEffect, useState, useRef } from "react";
import { IconButton, Box } from '@mui/material';
import { ThumbUp, ThumbDown } from '@mui/icons-material';

export default function Feedback({
  message,
  on_feedback,
}: {
  message: string;
  on_feedback: (message: string, event: string) => void;
}): JSX.Element {
  const [liked, setLiked] = useState<boolean | null>(null);
  const thumbsUp = useRef<HTMLButtonElement>(null);
  const thumbsDown = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!!thumbsUp.current) {
      thumbsUp.current.addEventListener("click", () => {
        setLiked(true);
        on_feedback(message, "thumbs_up");
      });
    }
  }, [thumbsUp, on_feedback, message]);

  useEffect(() => {
    if (!!thumbsDown.current) {
      thumbsDown.current.addEventListener("click", () => {
        setLiked(false);
        on_feedback(message, "thumbs_down");
      });
    }
  }, [thumbsDown, on_feedback, message]);

  return (
    <Box sx={{ 
      display: 'flex', 
      justifyContent: 'flex-end',
      gap: 0.5
    }}>
      <IconButton 
        ref={thumbsUp}
        size="small"
        sx={{ 
          color: liked === true ? '#1db954' : 'text.secondary',
          '&:hover': {
            backgroundColor: 'rgba(29, 185, 84, 0.1)'
          }
        }}
      >
        <ThumbUp fontSize="small" />
      </IconButton>
      <IconButton 
        ref={thumbsDown}
        size="small"
        sx={{ 
          color: liked === false ? '#ff4444' : 'text.secondary',
          '&:hover': {
            backgroundColor: 'rgba(255, 68, 68, 0.1)'
          }
        }}
      >
        <ThumbDown fontSize="small" />
      </IconButton>
    </Box>
  );
}
