<script lang="ts">
  let {
    label,
    src = null,
    placeholder = '',
    loading = false,
    bgColor = null,
  }: {
    label: string;
    src?: string | null;
    placeholder?: string;
    loading?: boolean;
    bgColor?: string | null;
  } = $props();

  let zoom = $state(1.0);
  let panX = $state(0);
  let panY = $state(0);
  let dragStart: { x: number; y: number; px: number; py: number } | null = null;

  function onWheel(e: WheelEvent) {
    if (!src) return;
    e.preventDefault();
    zoom = Math.min(Math.max(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 0.2), 10);
  }

  function onMouseDown(e: MouseEvent) {
    if (!src) return;
    dragStart = { x: e.clientX, y: e.clientY, px: panX, py: panY };
  }

  function onMouseMove(e: MouseEvent) {
    if (!dragStart) return;
    panX = dragStart.px + (e.clientX - dragStart.x);
    panY = dragStart.py + (e.clientY - dragStart.y);
  }

  function onMouseUp() { dragStart = null; }
  function onDblClick() { zoom = 1; panX = 0; panY = 0; }
</script>

<div class="panel">
  <div class="label">{label}</div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="canvas-area"
    onwheel={onWheel}
    onmousedown={onMouseDown}
    onmousemove={onMouseMove}
    onmouseup={onMouseUp}
    ondblclick={onDblClick}
    style="cursor: {src ? 'grab' : 'default'}; background: {bgColor ?? '#2a2a2a'}; {!bgColor && src ? 'background-image: repeating-conic-gradient(#333 0% 25%, #2a2a2a 0% 50%); background-size: 20px 20px;' : ''}"
  >
    {#if src}
      <img
        {src}
        alt={label}
        style="transform: translate({panX}px, {panY}px) scale({zoom}); transform-origin: center;"
        draggable="false"
      />
    {:else if placeholder}
      <p class="placeholder">{placeholder}</p>
    {/if}

    <!-- Progress bar at bottom (main window only, replaces circular spinner) -->
    {#if loading}
      <div class="progress-bar">
        <div class="progress-fill"></div>
      </div>
    {/if}
  </div>
</div>

<style>
.panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.label {
  font-size: 0.78rem;
  color: #888;
  padding: 0 2px 4px;
}

.canvas-area {
  flex: 1;
  background: #2a2a2a;
  border: 1px solid #444;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
}

img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  pointer-events: none;
}

.placeholder {
  color: #555;
  font-size: 0.85rem;
}

/* Indeterminate progress bar — bottom of panel */
.progress-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: #1a1a1a;
  overflow: hidden;
  border-radius: 0 0 4px 4px;
}

.progress-fill {
  height: 100%;
  width: 40%;
  background: linear-gradient(90deg, transparent, #00d4aa, transparent);
  animation: slide 1.4s ease-in-out infinite;
}

@keyframes slide {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}
</style>
