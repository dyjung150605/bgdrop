<script lang="ts">
  let {
    label,
    src = null,
    placeholder = '',
  }: {
    label: string;
    src?: string | null;
    placeholder?: string;
  } = $props();

  let zoom = $state(1.0);
  let panX = $state(0);
  let panY = $state(0);
  let dragStart: { x: number; y: number; px: number; py: number } | null = null;

  function onWheel(e: WheelEvent) {
    if (!src) return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    zoom = Math.min(Math.max(zoom * factor, 0.2), 10);
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

  function onDblClick() {
    zoom = 1.0;
    panX = 0;
    panY = 0;
  }
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
    style="cursor: {src ? 'grab' : 'default'}"
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
  transition: transform 0.05s ease-out;
}

.placeholder {
  color: #555;
  font-size: 0.85rem;
}
</style>
