import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Serve index.html for all unknown routes (SPA support)
    proxy: {
      '/rag': {
        target: process.env.VITE_API_BASE_URL || 'http://localhost:5100',
        changeOrigin: true,
      },
    },
  },
  // Library build mode (npm run build:lib)
  ...(mode === 'lib' && {
    build: {
      lib: {
        entry:    path.resolve(__dirname, 'src/index.ts'),
        name:     'QsintRagUi',
        fileName: (format) => `rag-ui.${format}.js`,
      },
      rollupOptions: {
        external: ['react', 'react-dom', 'antd', '@ant-design/icons', '@ant-design/plots', '@ant-design/x'],
        output: {
          globals: {
            react:              'React',
            'react-dom':        'ReactDOM',
            antd:               'antd',
            '@ant-design/icons':'AntdIcons',
            '@ant-design/plots':'AntdPlots',
            '@ant-design/x':    'AntdX',
          },
        },
      },
    },
  }),
}))
