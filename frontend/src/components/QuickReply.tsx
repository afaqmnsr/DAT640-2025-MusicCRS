import { Button } from '@mui/material';

export default function QuickReplyButton({
  text,
  message,
  click,
}: {
  text: string;
  message: string;
  click: (message: string) => void;
}): JSX.Element {
  const handleClick = () => {
    click(message);
  };

  return (
    <Button 
      variant="outlined" 
      size="small" 
      color="secondary" 
      onClick={handleClick}
      sx={{ textTransform: 'none' }}
    >
      {text}
    </Button>
  );
}
