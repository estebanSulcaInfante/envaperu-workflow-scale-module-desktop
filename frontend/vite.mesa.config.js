import { defineConfig, mergeConfig } from 'vite';
import stationConfig from './vite.config.js';

export default mergeConfig(stationConfig, defineConfig({
  build: {
    outDir: '../build/mesa-frontend',
    rollupOptions: { input: 'mesa.html' },
  },
}));
