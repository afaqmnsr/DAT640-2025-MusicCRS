import { ReactNode } from "react";
import { Box } from '@mui/material';

export default function ChatEmbedded({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ height: '100%', display: 'flex' }}>
      <Box sx={{ flex: 1 }}>
        {children}
      </Box>
    </Box>
  );
}
