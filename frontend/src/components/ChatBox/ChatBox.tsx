import React, { useState, useRef, useContext } from "react";
import {
  Card,
  CardContent,
  CardActions,
  TextField,
  IconButton,
  Box,
  Typography,
} from '@mui/material';
import {
  Send as SendIcon,
} from '@mui/icons-material';
import { AgentChatMessage, UserChatMessage } from "../ChatMessage";
import { ChatMessage } from "../../types";
import { ConfigContext } from "../../contexts/ConfigContext";

interface ChatBoxProps {
  messages?: ChatMessage[];
  onSendMessage?: (message: string) => void;
}

export default function ChatBox({ messages = [], onSendMessage }: ChatBoxProps) {
  const { config } = useContext(ConfigContext);
  const [inputValue, setInputValue] = useState<string>("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleInput = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (inputValue.trim() === "") return;
    
    // Send message via callback
    onSendMessage?.(inputValue);
    setInputValue("");
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  };

  // Handle command clicks - add command to input field
  const handleCommandClick = (command: string) => {
    setInputValue(command);
    if (inputRef.current) {
      inputRef.current.value = command;
      inputRef.current.focus();
    }
  };

  // Convert messages to display format
  const displayMessages = messages.map((message, index) => {
    if (!message.text) return null;
    
    const image_url = message.attachments?.find(
      (attachment) => attachment.type === "images"
    )?.payload.images?.[0];
    
    return (
      <AgentChatMessage
        key={`agent-${index}-${message.text.substring(0, 20)}`}
        feedback={config.useFeedback ? () => {} : null}
        message={message.text}
        image_url={image_url}
        onCommandClick={handleCommandClick}
      />
    );
  }).filter(Boolean);

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <CardContent sx={{ 
          flex: 1, 
          overflow: 'auto', 
          p: 2,
          minHeight: 0, // Important for flex scrolling
          '&::-webkit-scrollbar': {
            width: '8px',
          },
          '&::-webkit-scrollbar-track': {
            backgroundColor: '#f1f1f1',
            borderRadius: '4px',
          },
          '&::-webkit-scrollbar-thumb': {
            backgroundColor: '#c1c1c1',
            borderRadius: '4px',
            '&:hover': {
              backgroundColor: '#a8a8a8',
            },
          },
        }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {displayMessages}
          </Box>
        </CardContent>

        <CardActions sx={{ p: 2, borderTop: '1px solid #e0e0e0' }}>
          <Box component="form" onSubmit={handleInput} sx={{ display: 'flex', width: '100%', gap: 1 }}>
            <TextField
              fullWidth
              variant="outlined"
              placeholder="Type message"
              value={inputValue}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setInputValue(e.target.value)}
              inputRef={inputRef}
              size="small"
            />
            <IconButton type="submit" color="primary" disabled={!inputValue.trim()}>
              <SendIcon />
            </IconButton>
          </Box>
        </CardActions>
      </Card>
    </Box>
  );
}