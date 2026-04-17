<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { convertFileSrc } from '@tauri-apps/api/core';
  import { invoke } from '@tauri-apps/api/core';
  import { open } from '@tauri-apps/plugin-dialog';
  import DropZone from '$lib/DropZone.svelte';
  import ImagePanel from '$lib/ImagePanel.svelte';

  const VALID_EXT = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp']);
  const MODELS = [
    { value: 'isnet-general-use', label: 'ISNet  —  고품질 경계' },
    { value: 'u2net',             label: 'U2Net  —  범용 빠름' },
    { value: 'u2net_human_seg',   label: 'U2Net Portrait  —  인물 전용' },
  ];
  // BG presets matching Python version (checker / white / black / chroma green / custom)
  const BG_PRESETS = [
    { color: null,      label: '투명 (Checker)' },
    { color: '#ffffff', label: 'White' },
    { color: '#000000', label: 'Black' },
    { color: '#00ff00', label: 'Chroma Key Green' },
  ];

  let beforeSrc   = $state<string | null>(null);
  let afterBase64 = $state<string | null>(null); // raw base64 result (for save)
  let imagePath   = $state<string | null>(null);
  let imageStem   = $state('output');
  let processing  = $state(false);
  let status      = $state('이미지를 드롭하거나 클릭해서 불러오세요.');
  let isDragOver  = $state(false);

  // Pipeline controls (matching Python version)
  let modelName        = $state('isnet-general-use');
  let postProcessMask  = $state(true);
  let alphaClean       = $state(true);
  let alphaMatting     = $state(false);

  // Custom BG color
  let customColor = $state('#888888');
  let colorInputEl: HTMLInputElement | null = null;

  // BG & save
  let bgColor   = $state<string | null>(null);
  let saveFormat = $state<'png' | 'webp'>('png');

  let unlisten: (() => void) | null = null;

  onMount(async () => {
    unlisten = await getCurrentWindow().onDragDropEvent((event) => {
      const t = event.payload.type;
      if (t === 'enter') isDragOver = true;
      else if (t === 'leave') isDragOver = false;
      else if (t === 'drop') {
        isDragOver = false;
        const paths = (event.payload as any).paths as string[];
        if (paths?.length) handleFilePath(paths[0]);
      }
    });
  });

  onDestroy(() => { unlisten?.(); });

  function ext(path: string) { return path.split('.').pop()?.toLowerCase() ?? ''; }
  function filename(path: string) { return path.split(/[\\/]/).pop() ?? path; }
  function stem(path: string) { const f = filename(path); return f.replace(/\.[^.]+$/, ''); }

  function handleFilePath(path: string) {
    if (!VALID_EXT.has(ext(path))) { status = `지원하지 않는 형식: .${ext(path)}`; return; }
    imagePath = path;
    imageStem = stem(path);
    beforeSrc = convertFileSrc(path);
    afterBase64 = null;
    status = filename(path);
  }

  async function browse() {
    const file = await open({ multiple: false, filters: [{ name: 'Image', extensions: [...VALID_EXT] }] });
    if (typeof file === 'string') handleFilePath(file);
  }

  async function removeBackground() {
    if (!imagePath || processing) return;
    processing = true;
    afterBase64 = null;
    status = 'Processing...';
    try {
      const result = await invoke<string>('remove_background', {
        imagePath, modelName, postProcessMask, alphaClean, alphaMatting,
      });
      afterBase64 = result;
      status = `완료  —  ${filename(imagePath)}`;
    } catch (e) {
      status = `오류: ${e}`;
    } finally {
      processing = false;
    }
  }

  async function saveResult() {
    if (!afterBase64) return;
    try {
      await invoke('save_result', {
        base64Png: afterBase64,
        bgColor,
        format: saveFormat,
        suggestedName: `${imageStem}_nobg`,
      });
    } catch (e) {
      status = `저장 오류: ${e}`;
    }
  }

  function reset() {
    beforeSrc = null; afterBase64 = null; imagePath = null;
    status = '이미지를 드롭하거나 클릭해서 불러오세요.';
  }

  // Compose display src for After panel
  // We just serve the base64 directly; background is handled via CSS on the panel
  let afterSrc = $derived(afterBase64);
</script>

{#if isDragOver}
  <div class="drag-overlay"><p>놓아서 열기</p></div>
{/if}

<div class="app">
  <!-- Pipeline bar -->
  {#if beforeSrc}
  <div class="pipeline-bar">
    <select bind:value={modelName} disabled={processing} class="model-select">
      {#each MODELS as m}
        <option value={m.value}>{m.label}</option>
      {/each}
    </select>

    <span class="arrow">▶</span>

    <label class="pipe-check" title="rembg 내장 모폴로지 연산 — 마스크 경계 정리, 큰 덩어리 노이즈와 구멍 제거">
      <input type="checkbox" bind:checked={postProcessMask} disabled={processing} />
      Post Process Mask
    </label>

    <span class="arrow">▶</span>

    <label class="pipe-check" title="반투명 헤일로(번짐) 제거 — alpha &lt; 80 → 완전 투명, alpha &gt; 200 → 완전 불투명">
      <input type="checkbox" bind:checked={alphaClean} disabled={processing} />
      Alpha Clean
    </label>

    <span class="arrow">▶</span>

    <label class="pipe-check" title="⚠ 2~3배 느림 — 머리카락/털 등 가는 디테일 경계 정밀화 (coming soon)">
      <input type="checkbox" bind:checked={alphaMatting} disabled={true} />
      <span style="color: #666;">Alpha Matting</span>
    </label>

    <span class="pipe-sep">|</span>

    <button class="btn-primary" onclick={removeBackground} disabled={processing}>
      {processing ? '처리 중…' : '배경 제거'}
    </button>

    <!-- BG color picker -->
    <span class="pipe-sep">|</span>
    <span class="bg-label">BG</span>

    {#each BG_PRESETS as opt}
      <button
        class="bg-dot"
        class:active={bgColor === opt.color}
        style={opt.color === null
          ? 'background-image: repeating-conic-gradient(#555 0% 25%, #2a2a2a 0% 50%); background-size: 10px 10px;'
          : `background: ${opt.color};`}
        onclick={() => bgColor = opt.color}
        title={opt.label}
      ></button>
    {/each}

    <!-- Custom color dot + hidden input -->
    <button
      class="bg-dot bg-dot-custom"
      class:active={bgColor !== null && !BG_PRESETS.some(o => o.color === bgColor)}
      style="background: {bgColor && !BG_PRESETS.some(o => o.color === bgColor) ? bgColor : 'conic-gradient(red, yellow, lime, cyan, blue, magenta, red)'};"
      onclick={() => colorInputEl?.click()}
      title="Custom color"
    ></button>
    <input
      bind:this={colorInputEl}
      type="color"
      style="display:none"
      value={customColor}
      oninput={(e) => { customColor = (e.target as HTMLInputElement).value; bgColor = customColor; }}
    />

    {#if afterBase64}
    <span class="pipe-sep">|</span>
    <label class="pipe-check">
      <input type="radio" bind:group={saveFormat} value="png" /> PNG
    </label>
    <label class="pipe-check">
      <input type="radio" bind:group={saveFormat} value="webp" /> WebP
    </label>
    <button class="btn-save" onclick={saveResult}>Save</button>
    {/if}
  </div>
  {/if}

  <!-- panels -->
  <div class="panels">
    {#if beforeSrc}
      <ImagePanel label="Before" src={beforeSrc} bgColor={bgColor ?? '#2a2a2a'} />
      <div class="divider"></div>
      <ImagePanel label="After" src={afterSrc} loading={processing}
        placeholder="배경 제거 결과가 여기 표시됩니다."
        {bgColor} />
    {:else}
      <DropZone onBrowse={browse} />
    {/if}
  </div>

  <!-- status bar -->
  <div class="status-bar">
    <span class="status-text">{status}</span>
    <div class="status-right">
      {#if beforeSrc}
        <button class="reset-btn" onclick={reset}>✕ Reset</button>
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
  padding: 8px 16px 0;
}

/* Pipeline bar */
.pipeline-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
  flex-wrap: wrap;
}

.model-select {
  background: #2a2a2a;
  color: #e0e0e0;
  border: 1px solid #444;
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 0.82rem;
  cursor: pointer;
}

.model-select:disabled { opacity: 0.5; }

.arrow { color: #444; font-size: 0.7rem; }

.pipe-check {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.82rem;
  color: #ccc;
  cursor: pointer;
}

.pipe-check input { accent-color: #00d4aa; cursor: pointer; }

.pipe-sep { color: #333; }

.bg-label { color: #666; font-size: 0.78rem; }

.bg-dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid #555;
  cursor: pointer;
  flex-shrink: 0;
  transition: transform 0.12s, border-color 0.12s;
}

.bg-dot:hover { transform: scale(1.2); border-color: #888; }
.bg-dot.active { border-color: #00d4aa; transform: scale(1.15); }
.bg-dot-custom { background-size: cover; }

.btn-primary {
  background: #00d4aa;
  color: #1e1e1e;
  border: none;
  border-radius: 5px;
  padding: 5px 16px;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
}

.btn-primary:hover:not(:disabled) { background: #00b894; }
.btn-primary:disabled { opacity: 0.5; cursor: default; }

.btn-save {
  background: #3a3a3a;
  color: #00d4aa;
  border: 1px solid #00d4aa;
  border-radius: 5px;
  padding: 4px 14px;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s;
}

.btn-save:hover { background: #00d4aa; color: #1e1e1e; }

/* Panels */
.panels { flex: 1; display: flex; min-height: 0; padding-bottom: 8px; }
.divider { width: 4px; background: #1e1e1e; flex-shrink: 0; }

/* Status bar */
.status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0 6px;
  border-top: 1px solid #2a2a2a;
  font-size: 0.78rem;
}

.status-text { color: #888; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.status-right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }

.reset-btn {
  background: none;
  border: 1px solid #444;
  border-radius: 4px;
  color: #888;
  padding: 2px 8px;
  font-size: 0.75rem;
  transition: border-color 0.15s, color 0.15s;
}

.reset-btn:hover { border-color: #ff6b6b; color: #ff6b6b; }

.version { color: #555; }

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
