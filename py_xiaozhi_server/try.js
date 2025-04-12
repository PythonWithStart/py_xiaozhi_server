// 浏览器控制台测试
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onmessage = (e) => console.log('Received:', e.data);
ws.send('test message');