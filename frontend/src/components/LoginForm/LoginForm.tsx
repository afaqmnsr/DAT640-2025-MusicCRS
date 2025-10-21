import { useContext, useEffect, useState } from "react";
import { useSocket } from "../../contexts/SocketContext";
import {
  Card,
  CardHeader,
  CardContent,
  TextField,
  Button,
  Typography,
  Box,
  Alert,
} from '@mui/material';
import { UserContext } from "../../contexts/UserContext";
import { ConfigContext } from "../../contexts/ConfigContext";

const LoginForm = () => {
  const { config } = useContext(ConfigContext);
  const { setUser } = useContext(UserContext);
  const { login, register, onAuthentication } = useSocket();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const handleAnonymousLogin = () => {
    setUser({ username: "Anonymous", isAnonymous: true });
  };

  const handleLogin = () => {
    login(username, password);
  };

  const handleRegister = () => {
    register(username, password);
  };

  useEffect(() => {
    onAuthentication((success: boolean, error: string) => {
      if (success) {
        setUser({ username, isAnonymous: false });
      } else {
        setErrorMessage(error);
      }
    });
  }, [onAuthentication, setUser, setErrorMessage, username]);

  return (
    <Box sx={{ 
      display: 'flex', 
      justifyContent: 'center', 
      alignItems: 'center', 
      minHeight: '100%',
      p: 2 
    }}>
      <Card
        sx={{ 
          borderRadius: 3,
          maxWidth: 400,
          width: '100%',
          boxShadow: 3
        }}
      >
        <CardHeader
          title={config.name}
          sx={{
            backgroundColor: '#1db954',
            color: 'white',
            '& .MuiCardHeader-title': {
              fontWeight: 'bold',
              fontSize: '1.2rem'
            }
          }}
        />

        <CardContent sx={{ p: 3 }}>
          <Typography variant="h5" component="h2" sx={{ mb: 3, fontWeight: 'bold' }}>
            Login
          </Typography>
          
          <TextField
            fullWidth
            label="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            sx={{ mb: 2 }}
            variant="outlined"
          />
          
          <TextField
            fullWidth
            type="password"
            label="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            sx={{ mb: 2 }}
            variant="outlined"
          />
          
          {errorMessage && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {errorMessage}
            </Alert>
          )}
          
          <Box sx={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            gap: 1,
            mt: 3 
          }}>
            <Button 
              variant="outlined" 
              onClick={handleRegister}
              sx={{ flex: 1 }}
            >
              Register
            </Button>
            <Button 
              variant="contained" 
              onClick={handleLogin}
              sx={{ flex: 1 }}
            >
              Sign In
            </Button>
            <Button 
              variant="text" 
              onClick={handleAnonymousLogin}
              sx={{ flex: 1 }}
            >
              Anonymous
            </Button>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
};

export default LoginForm;
