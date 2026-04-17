<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { convertFileSrc } from '@tauri-apps/api/core';
  import { open } from '@tauri-apps/plugin-dialog';
  import DropZone from '$lib/DropZone.svelte';
  import ImagePanel from '$lib/ImagePanel.svelte';

  const VALID_EXT = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp']);

  let beforeSrc = $state<string | null>(null);
  let status = $state('이미지를 드롭하거나 클릭해서 불러오세요.');
  let isDragOver = $state(false);

  let unlisten: (() => void) | null = null;

  onMount(async () => {
    unlisten = await getCurrentWindow().onDragDropEvent((event) => {
      const t = event.payload.type;
      if (t === 'enter') {
        isDragOver = true;
      } else if (t === 'leave') {
        isDragOver = false;
      } else if (t === 'drop') {
        isDragOver = false;
        const paths = (event.payload as any).paths as string[];
        if (paths?.length) handleFilePath(paths[0]);
      }
    });
  });

  onDestroy(() => { unlisten?.(); });

  function ext(path: string) {
    return path.split('.').pop()?.toLowerCase() ?? '';
  }

  function filename(path: string) {
    return path.split(/[\\/]/).pop() ?? path;
  }

  function handleFilePath(path: string) {
    if (!VALID_EXT.has(ext(path))) {
      status = `지원하지 않는 형식: .${ext(path)}`;
      return;
    }
    beforeSrc = convertFileSrc(path);
    status = filename(path);
  }

  function reset() {
    beforeSrc = null;
    status = '이미지를 드롭하거나 클릭해서 불러오세요.';
  }

  async function browse() {
    const file = await open({
      multiple: false,
      filters: [{ name: 'Image', extensions: [...VALID_EXT] }],
    });
    if (typeof file === 'string') handleFilePath(file);
  }
</script>

<!-- drag-over overlay -->
{#if isDragOver}
  <div class="drag-overlay">
    <p>놓아서 열기</p>
  </div>
{/if}

<div class="app">
  <!-- panels -->
  <div class="panels">
    {#if beforeSrc}
      <ImagePanel label="Before" src={beforeSrc} />
      <div class="divider"></div>
      <ImagePanel label="After" placeholder="처리 결과가 여기 표시됩니다." />
    {:else}
      <DropZone onBrowse={browse} />
    {/if}
  </div>

  <!-- status bar -->
  <div class="status-bar">
    <span class="status-text">{status}</span>
    <div class="status-right">
      {#if beforeSrc}
        <button class="reset-btn" onclick={reset} title="초기화">✕ Reset</button>
      {/if}
      <span class="version">v0.1</span>
    </div>
  </div>
</div>

<style>
.app {
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 12px 16px 0;
}

.panels {
  flex: 1;
  display: flex;
  gap: 0;
  min-height: 0;
  padding-bottom: 8px;
}

.divider {
  width: 4px;
  background: #1e1e1e;
  flex-shrink: 0;
}

.status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0 6px;
  border-top: 1px solid #2a2a2a;
  font-size: 0.78rem;
}

.status-text {
  color: #888;
}

.status-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.reset-btn {
  background: none;
  border: 1px solid #444;
  border-radius: 4px;
  color: #888;
  padding: 2px 8px;
  font-size: 0.75rem;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}

.reset-btn:hover {
  border-color: #ff6b6b;
  color: #ff6b6b;
}

.drag-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 212, 170, 0.08);
  border: 2px dashed #00d4aa;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.4rem;
  font-weight: 700;
  color: #00d4aa;
  z-index: 100;
  pointer-events: none;
}
</style>
