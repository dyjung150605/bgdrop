<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { convertFileSrc } from '@tauri-apps/api/core';
  import { invoke } from '@tauri-apps/api/core';
  import { tick } from 'svelte';
  import { listen } from '@tauri-apps/api/event';
  import { open } from '@tauri-apps/plugin-dialog';
  import DropZone from '$lib/DropZone.svelte';
  import ImagePanel from '$lib/ImagePanel.svelte';
  import AutoPanel from '$lib/AutoPanel.svelte';

  const VALID_EXT = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp']);
  const MODELS = [
    { value: 'isnet-general-use', label: 'ISNet — 고품질 경계' },
    { value: 'u2net',             label: 'U2Net — 범용 빠름' },
    { value: 'u2net_human_seg',   label: 'U2Net Portrait — 인물' },
  ];
  const BG_PRESETS = [
    { color: null,      label: '투명 (Checker)' },
    { color: '#ffffff', label: 'White' },
    { color: '#000000', label: 'Black' },
    { color: '#00ff00', label: 'Chroma Key Green' },
  ];

  // Image state
  let beforeSrc   = $state<string | null>(null);
  let afterBase64 = $state<string | null>(null);
  let imagePath   = $state<string | null>(null);
  let imageStem   = $state('output');
  let processing  = $state(false);
  let status      = $state('이미지를 드롭하거나 클릭해서 불러오세요.');
  let isDragOver  = $state(false);

  // Pipeline
  let modelName       = $state('isnet-general-use');
  let postProcessMask = $state(true);
  let alphaClean      = $state(true);
  let alphaCleanLo    = $state(80);
  let alphaCleanHi    = $state(200);
  let alphaMatting    = $state(false);

  // BG & save
  let bgColor    = $state<string | null>(null);
  let saveFormat = $state<'png' | 'webp'>('png');
  let customColor = $state('#888888');
  let colorInputEl: HTMLInputElement | null = null;

  // Auto selector
  let autoMode       = $state(false);
  let autoCandidates = $state<any[]>([]);
  let autoComplete   = $state(false);
  let autoPanel: AutoPanel | null = null;
  let simGen         = $state(0);
  let unlistenSim: (() => void) | null = null;
  let unlistenDone: (() => void) | null = null;
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

  onDestroy(() => {
    unlisten?.();
    unlistenSim?.();
    unlistenDone?.();
  });

  function ext(p: string)      { return p.split('.').pop()?.toLowerCase() ?? ''; }
  function filename(p: string) { return p.split(/[\\/]/).pop() ?? p; }
  function stem(p: string)     { const f = filename(p); return f.replace(/\.[^.]+$/, ''); }

  function handleFilePath(path: string) {
    if (!VALID_EXT.has(ext(path))) { status = `지원하지 않는 형식: .${ext(path)}`; return; }
    imagePath = path;
    imageStem = stem(path);
    beforeSrc = convertFileSrc(path);
    afterBase64 = null;
    status = filename(path);
    if (autoMode) startAutoFlow();
  }

  async function browse() {
    const file = await open({ multiple: false, filters: [{ name: 'Image', extensions: [...VALID_EXT] }] });
    if (typeof file === 'string') handleFilePath(file);
  }

  async function removeBackground() {
    if (!imagePath || processing) return;
    processing = true;
    status = 'Processing...';
    try {
      const result = await invoke<string>('remove_background', {
        imagePath, modelName, postProcessMask,
        alphaClean, alphaCleanLo, alphaCleanHi, alphaMatting,
      });
      afterBase64 = result;
      status = `완료  —  ${filename(imagePath)}`;
    } catch (e) {
      status = `오류: ${e}`;
    } finally {
      processing = false;
    }
  }

  let reapplyTimer: ReturnType<typeof setTimeout> | null = null;

  async function onAlphaCleanChange() {
    if (!afterBase64) return;
    if (reapplyTimer) clearTimeout(reapplyTimer);
    reapplyTimer = setTimeout(async () => {
      try {
        const result = await invoke<string>('reapply_alpha_clean', {
          alphaClean, alphaCleanLo, alphaCleanHi,
        });
        afterBase64 = result;
      } catch (_) {}
    }, 80); // debounce 80ms
  }

  async function saveResult() {
    if (!afterBase64) return;
    try {
      await invoke('save_result', { base64Png: afterBase64, bgColor, format: saveFormat, suggestedName: `${imageStem}_nobg` });
    } catch (e) { status = `저장 오류: ${e}`; }
  }

  function reset() {
    closeAutoPanel();
    beforeSrc = null; afterBase64 = null; imagePath = null;
    status = '이미지를 드롭하거나 클릭해서 불러오세요.';
  }

  // ── Auto Selector ─────────────────────────────────────────────────────────

  async function startAutoFlow() {
    if (!imagePath) return;
    closeAutoPanel(false);
    autoCandidates = [];
    autoComplete = false;
    status = '이미지 분석 중…';
    try {
      const candidates = await invoke<any[]>('analyze_image', { imagePath });
      autoCandidates = candidates;

      unlistenSim?.();
      unlistenDone?.();
      unlistenSim = await listen<any>('sim-result', (event) => {
        const { gen, key, base64Png, error } = event.payload;
        if (gen !== simGen) return;
        autoPanel?.onSimResult(key, base64Png ?? null, error ?? null);
      });
      unlistenDone = await listen<number>('sim-complete', (event) => {
        if (event.payload !== simGen) return;
        autoComplete = true;
        status = '후보를 선택하세요.';
      });

      const gen = await invoke<number>('start_simulations', { imagePath, candidates });
      simGen = gen;
      status = `시뮬레이션 중… (${candidates.length}개 후보)`;
    } catch (e) {
      status = `Auto 오류: ${e}`;
      closeAutoPanel();
    }
  }

  function onAutoToggle() {
    if (autoMode && imagePath) startAutoFlow();
    else if (!autoMode) closeAutoPanel();
  }

  function closeAutoPanel(cancel = true) {
    if (cancel) invoke('cancel_simulations').catch(() => {});
    unlistenSim?.(); unlistenSim = null;
    unlistenDone?.(); unlistenDone = null;
    autoCandidates = [];
    autoComplete = false;
  }

  async function onAutoPick(combo: any, thumbBase64: string | null) {
    // Show thumb immediately, then await DOM update before starting full-res
    if (thumbBase64) afterBase64 = thumbBase64;
    modelName       = combo.model;
    postProcessMask = combo.postProcess;
    alphaClean      = combo.alphaClean;
    alphaMatting    = combo.alphaMatting;
    await tick(); // ensure thumb renders before spinner overlay appears
    removeBackground();
  }

  function onAutoClose() {
    autoMode = false;
    closeAutoPanel();
    status = imagePath ? `완료  —  ${filename(imagePath!)}` : '이미지를 드롭하거나 클릭해서 불러오세요.';
  }

  let afterSrc = $derived(afterBase64);
</script>

{#if isDragOver}
  <div class="drag-overlay"><p>놓아서 열기</p></div>
{/if}

<div class="app">

  <!-- ── TOP: panels ── -->
  <div class="main-area">

    <!-- Header row: Before/After labels + BG picker + Save -->
    {#if beforeSrc}
    <div class="header-row">
      <div class="header-before"><span class="panel-label">Before</span></div>
      <div class="header-divider"></div>
      <div class="header-after">
        <span class="panel-label">After</span>
      <div class="header-right">
        <span class="bg-label">BG</span>
        {#each BG_PRESETS as opt}
          <button class="bg-dot" class:active={bgColor === opt.color}
            style={opt.color === null
              ? 'background-image: repeating-conic-gradient(#555 0% 25%, #2a2a2a 0% 50%); background-size: 10px 10px;'
              : `background: ${opt.color};`}
            onclick={() => bgColor = opt.color} title={opt.label}
          ></button>
        {/each}
        <button class="bg-dot bg-dot-custom"
          class:active={bgColor !== null && !BG_PRESETS.some(o => o.color === bgColor)}
          style="background: {bgColor && !BG_PRESETS.some(o => o.color === bgColor) ? bgColor : 'conic-gradient(red,yellow,lime,cyan,blue,magenta,red)'};"
          onclick={() => colorInputEl?.click()} title="Custom color"
        ></button>
        <input bind:this={colorInputEl} type="color" style="display:none"
          value={customColor}
          oninput={(e) => { customColor = (e.target as HTMLInputElement).value; bgColor = customColor; }}
        />
        {#if afterBase64}
          <span class="pipe-sep">|</span>
          <label class="pipe-check"><input type="radio" bind:group={saveFormat} value="png" /> PNG</label>
          <label class="pipe-check"><input type="radio" bind:group={saveFormat} value="webp" /> WebP</label>
          <button class="btn-save" onclick={saveResult}>Save</button>
        {/if}
      </div>
      </div>
    </div>
    {/if}

    <!-- Image panels -->
    <div class="panels">
      {#if beforeSrc}
        <ImagePanel label="" src={beforeSrc} bgColor={bgColor ?? '#2a2a2a'} />
        <div class="divider"></div>
        <ImagePanel label="" src={afterSrc} loading={processing}
          placeholder="배경 제거 결과가 여기 표시됩니다." {bgColor} />
      {:else}
        <DropZone onBrowse={browse} />
      {/if}
    </div>

    <!-- Auto panel (slides in above pipeline bar) -->
    {#if autoMode && autoCandidates.length > 0}
      <AutoPanel
        bind:this={autoPanel}
        candidates={autoCandidates}
        {bgColor}
        complete={autoComplete}
        onPick={onAutoPick}
        onClose={onAutoClose}
      />
    {/if}
  </div>

  <!-- ── BOTTOM: pipeline bar (like Python version) ── -->
  {#if beforeSrc}
  <div class="pipeline-bar">
    <label class="auto-toggle">
      <input type="checkbox" bind:checked={autoMode} onchange={onAutoToggle} disabled={processing} />
      <span class:active={autoMode}>🪄 Auto</span>
    </label>

    <span class="pipe-sep">│</span>

    <select bind:value={modelName} disabled={processing || autoMode} class="model-select">
      {#each MODELS as m}<option value={m.value}>{m.label}</option>{/each}
    </select>

    <span class="arrow">▶</span>

    <label class="pipe-check" title="마스크 경계 정리 (morphological close+open)">
      <input type="checkbox" bind:checked={postProcessMask} disabled={processing || autoMode} />
      Post Process Mask
    </label>

    <span class="arrow">▶</span>

    <label class="pipe-check" title="반투명 헤일로 제거">
      <input type="checkbox" bind:checked={alphaClean}
        disabled={processing || autoMode}
        onchange={onAlphaCleanChange} />
      Alpha Clean
    </label>
    {#if alphaClean}
      <div class="ac-sliders" title="lo: 이 값 미만은 투명 / hi: 이 값 초과는 불투명">
        <span class="ac-label">lo</span>
        <input type="range" min="0" max="150" bind:value={alphaCleanLo}
          disabled={processing || autoMode}
          oninput={onAlphaCleanChange} class="ac-range" />
        <span class="ac-val">{alphaCleanLo}</span>
        <span class="ac-label">hi</span>
        <input type="range" min="100" max="255" bind:value={alphaCleanHi}
          disabled={processing || autoMode}
          oninput={onAlphaCleanChange} class="ac-range" />
        <span class="ac-val">{alphaCleanHi}</span>
      </div>
    {/if}

    <span class="arrow">▶</span>

    <label class="pipe-check" title="⚠ 2~3배 느림 — coming soon">
      <input type="checkbox" bind:checked={alphaMatting} disabled={true} />
      <span style="color:#555">Alpha Matting</span>
    </label>

    <span class="pipe-sep">│</span>

    <button class="btn-primary" onclick={removeBackground} disabled={processing}>
      {processing ? '처리 중…' : '배경 제거'}
    </button>
  </div>
  {/if}

  <!-- ── Status bar ── -->
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

/* ── Main area (panels + auto panel) ── */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* ── Header row — mirrors panel layout exactly ── */
.header-row {
  display: flex;
  align-items: center;
  padding-bottom: 4px;
}

.header-before {
  flex: 1;
  min-width: 0;
}

.header-divider {
  width: 4px; /* matches .divider */
  flex-shrink: 0;
}

.header-after {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
}

.panel-label {
  font-size: 0.78rem;
  color: #888;
  flex-shrink: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  flex-shrink: 0;
}

.bg-label { color: #666; font-size: 0.78rem; }

.bg-dot {
  width: 16px; height: 16px;
  border-radius: 50%;
  border: 2px solid #555;
  cursor: pointer;
  flex-shrink: 0;
  transition: transform 0.12s, border-color 0.12s;
}
.bg-dot:hover { transform: scale(1.2); border-color: #888; }
.bg-dot.active { border-color: #00d4aa; transform: scale(1.15); }
.bg-dot-custom { background-size: cover; }

.btn-save {
  background: #3a3a3a; color: #00d4aa;
  border: 1px solid #00d4aa; border-radius: 4px;
  padding: 3px 12px; font-size: 0.82rem; font-weight: 700; cursor: pointer;
  transition: background 0.15s;
}
.btn-save:hover { background: #00d4aa; color: #1e1e1e; }

/* ── Panels ── */
.panels { flex: 1; display: flex; min-height: 0; padding-bottom: 4px; }
.divider { width: 4px; background: #1e1e1e; flex-shrink: 0; }

/* ── Pipeline bar (bottom) ── */
.pipeline-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0 4px;
  border-top: 1px solid #2a2a2a;
  flex-shrink: 0;
  overflow-x: auto;
}

.auto-toggle { display: flex; align-items: center; cursor: pointer; font-size: 0.85rem; font-weight: 700; }
.auto-toggle input { display: none; }
.auto-toggle span { color: #666; padding: 3px 8px; border-radius: 4px; border: 1px solid #333; white-space: nowrap; }
.auto-toggle span.active { color: #00d4aa; border-color: #00d4aa; background: rgba(0,212,170,0.08); }

.model-select {
  background: #2a2a2a; color: #e0e0e0;
  border: 1px solid #444; border-radius: 4px;
  padding: 3px 6px; font-size: 0.82rem; cursor: pointer;
}
.model-select:disabled { opacity: 0.5; }

.arrow { color: #444; font-size: 0.7rem; flex-shrink: 0; }
.pipe-sep { color: #333; flex-shrink: 0; }

.pipe-check {
  display: flex; align-items: center; gap: 4px;
  font-size: 0.82rem; color: #ccc; cursor: pointer; white-space: nowrap;
}
.pipe-check input { accent-color: #00d4aa; cursor: pointer; }

.ac-sliders {
  display: flex;
  align-items: center;
  gap: 4px;
}

.ac-label {
  font-size: 0.72rem;
  color: #666;
}

.ac-val {
  font-size: 0.72rem;
  color: #888;
  width: 22px;
  text-align: right;
}

.ac-range {
  width: 60px;
  accent-color: #00d4aa;
  cursor: pointer;
  height: 3px;
}

.ac-range:disabled { opacity: 0.4; cursor: default; }

.btn-primary {
  background: #00d4aa; color: #1e1e1e;
  border: none; border-radius: 5px;
  padding: 5px 16px; font-size: 0.85rem; font-weight: 700;
  cursor: pointer; transition: background 0.15s; white-space: nowrap;
}
.btn-primary:hover:not(:disabled) { background: #00b894; }
.btn-primary:disabled { opacity: 0.5; cursor: default; }

/* ── Status bar ── */
.status-bar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 3px 0 5px;
  border-top: 1px solid #2a2a2a;
  font-size: 0.78rem;
}
.status-text { color: #888; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }

.reset-btn {
  background: none; border: 1px solid #444; border-radius: 4px;
  color: #888; padding: 2px 8px; font-size: 0.75rem;
  transition: border-color 0.15s, color 0.15s;
}
.reset-btn:hover { border-color: #ff6b6b; color: #ff6b6b; }
.version { color: #555; }

.drag-overlay {
  position: fixed; inset: 0;
  background: rgba(0,212,170,0.08);
  border: 2px dashed #00d4aa; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.4rem; font-weight: 700; color: #00d4aa;
  z-index: 100; pointer-events: none;
}
</style>
