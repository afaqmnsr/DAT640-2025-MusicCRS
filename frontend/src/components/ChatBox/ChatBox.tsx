import React, { useState, useRef, useContext } from "react";
import {
  Card,
  CardContent,
  CardActions,
  TextField,
  IconButton,
  Box,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Button,
} from '@mui/material';
import {
  Send as SendIcon,
  Clear as ClearIcon,
} from '@mui/icons-material';
import { AgentChatMessage, UserChatMessage } from "../ChatMessage";
import { ChatMessage } from "../../types";
import { ConfigContext } from "../../contexts/ConfigContext";

interface ChatBoxProps {
  messages?: ChatMessage[];
  onSendMessage?: (message: string) => void;
  onClearChat?: () => void;
}

export default function ChatBox({ messages = [], onSendMessage, onClearChat }: ChatBoxProps) {
  const { config } = useContext(ConfigContext);
  const [inputValue, setInputValue] = useState<string>("");
  const [showClearDialog, setShowClearDialog] = useState<boolean>(false);
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

  // Handle clear chat with confirmation
  const handleClearChatClick = () => {
    setShowClearDialog(true);
  };

  const handleConfirmClear = () => {
    onClearChat?.();
    setShowClearDialog(false);
  };

  const handleCancelClear = () => {
    setShowClearDialog(false);
  };

  // Convert messages to display format
  const displayMessages = messages.map((message, index) => {
    if (!message.text) return null;
    
    // Check if this is a user message (has participant field or is from user)
    const isUserMessage = message.participant === 'user';
    
    if (isUserMessage) {
      return (
        <UserChatMessage
          key={`user-${index}-${message.text.substring(0, 20)}`}
          message={message.text}
        />
      );
    }
    
    // Agent message
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
            <IconButton 
              type="button" 
              color="secondary" 
              onClick={handleClearChatClick}
              disabled={messages.length === 0}
              title="Clear chat history"
            >
              <ClearIcon />
            </IconButton>
            <IconButton type="submit" color="primary" disabled={!inputValue.trim()}>
              <SendIcon />
            </IconButton>
          </Box>
        </CardActions>
      </Card>

      {/* Clear Chat Confirmation Dialog */}
      <Dialog
        open={showClearDialog}
        onClose={handleCancelClear}
        aria-labelledby="clear-dialog-title"
        aria-describedby="clear-dialog-description"
      >
        <DialogTitle id="clear-dialog-title">
          Clear Chat History
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="clear-dialog-description">
            Are you sure you want to clear all chat messages? This action cannot be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelClear} color="primary">
            Cancel
          </Button>
          <Button onClick={handleConfirmClear} color="error" variant="contained">
            Clear Chat
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}