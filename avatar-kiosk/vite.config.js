import { defineConfig } from 'vite';
export default defineConfig({
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'vrm', test: /node_modules[\\/]@pixiv[\\/]/, priority: 20, includeDependenciesRecursively: false },
            { name: 'three', test: /node_modules[\\/]three[\\/]/, priority: 10, includeDependenciesRecursively: false },
          ],
        },
      },
    },
  },
});
