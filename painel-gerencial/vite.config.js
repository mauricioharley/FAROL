import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base '/gerencial/': o painel-nginx (sidecar TLS) serve este app sob esse
// caminho, atras do mesmo dominio do painel tecnico - sem isso, os assets
// gerados pelo build (JS/CSS com hash no nome) resolveriam a partir de "/"
// e quebrariam atras do proxy.
export default defineConfig({
  base: '/gerencial/',
  plugins: [react()],
  build: {
    outDir: 'dist',
  },
});
