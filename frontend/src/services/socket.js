import { io } from 'socket.io-client';

const socket = io({
  transports: ['polling'],
  autoConnect: true,
  reconnection: true,
  reconnectionDelay: 1000,
  reconnectionAttempts: Infinity
});

socket.on('connect', () => {
  console.log('[WS] ✅ Conectado al servidor');
});

socket.on('disconnect', (reason) => {
  console.log('[WS] ❌ Desconectado:', reason);
});

socket.on('connect_error', (err) => {
  console.log('[WS] Error de conexión:', err.message);
});

export default socket;
