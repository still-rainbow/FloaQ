import React from 'react';
import { createRoot } from 'react-dom/client';

// 순서가 중요하다: leaflet → 토큰 → 화면.
// 토큰이 leaflet 뒤에 와야 .leaflet-container 의 색을 우리 변수로 덮을 수 있다.
import 'leaflet/dist/leaflet.css';
import '@floaq/shared/tokens.css';
import './styles/web.css';

import App from './App';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
