import { defineConfig } from 'vite';
import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';

function dependencyNotices() {
  return {
    name: 'studio-dependency-notices',
    async generateBundle() {
      const lock = JSON.parse(await readFile('package-lock.json', 'utf8'));
      const notices = ['Smart TKB AI Studio — third-party dependency notices'];
      for (const [directory, info] of Object.entries(lock.packages)) {
        if (!directory) continue;
        let files;
        try { files = await readdir(directory); }
        catch { continue; }
        notices.push(`\n\n${directory} @ ${info.version}\nLicense: ${info.license || 'See original package'}`);
        for (const file of files.filter(name => /^(licen[cs]e|notice|copying|third_party_notices)/i.test(name))) {
          try { notices.push(await readFile(join(directory, file), 'utf8')); }
          catch { /* Some packages use a directory for license documents. */ }
        }
      }
      this.emitFile({ type: 'asset', fileName: 'THIRD_PARTY_NOTICES.txt', source: notices.join('\n') });
    },
  };
}

export default defineConfig({
  base: '/static/ai-slides/dist/',
  plugins: [dependencyNotices()],
  build: {
    outDir: process.env.STUDIO_BUILD_OUT || '../../app/static/ai-slides/dist',
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: { studio: 'src/app.js' },
      output: { entryFileNames: 'studio.js', assetFileNames: '[name]-[hash][extname]' },
    },
  },
});
