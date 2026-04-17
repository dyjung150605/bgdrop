<script lang="ts">
  import { listen } from '@tauri-apps/api/event';
  import { onDestroy } from 'svelte';

  type Combo = {
    key: string; model: string; postProcess: boolean;
    alphaClean: boolean; alphaMatting: boolean; label: string;
  };

  type Slot = {
    combo: Combo;
    src: string | null;
    error: string | null;
    done: boolean;
  };

  let {
    candidates = [],
    bgColor = null,
    complete = false,
    onPick,
    onClose,
  }: {
    candidates: Combo[];
    bgColor?: string | null;
    complete?: boolean;
    onPick: (combo: Combo, thumbBase64: string | null) => void;
    onClose: () => void;
  } = $props();

  let slots = $state<Slot[]>(
    candidates.map(c => ({ combo: c, src: null, error: null, done: false }))
  );
  let selectedKey = $state<string | null>(null);

  // Listen for sim-result events (set up externally via parent, but we handle display)
  function updateSlot(key: string, src: string | null, error: string | null) {
    slots = slots.map(s =>
      s.combo.key === key ? { ...s, src, error, done: true } : s
    );
  }

  export function onSimResult(key: string, src: string | null, error: string | null) {
    updateSlot(key, src, error);
  }

  function pick(combo: Combo, thumbSrc: string | null) {
    selectedKey = combo.key;
    onPick(combo, thumbSrc);
  }

  const THINKING = [
    'Analyzing…', 'Computing…', 'Simulating…', 'Processing…',
    'Rendering…', 'Calibrating…', 'Thinking…', 'Working…',
  ];

  function randomThinking() {
    return THINKING[Math.floor(Math.random() * THINKING.length)];
  }
</script>

<div class="auto-panel">
  <div class="auto-header">
    <span class="auto-title">🪄 Smart Match</span>
    <span class="auto-subtitle">
      {#if complete}
        완료 — 썸네일을 클릭해 선택하세요.
      {:else}
        시뮬레이션 중… 클릭해서 미리 적용해볼 수 있어요.
      {/if}
    </span>
    <button class="close-btn" onclick={onClose}>✕</button>
  </div>

  <div class="thumb-grid">
    {#each slots as slot}
      {@const isSelected = selectedKey === slot.combo.key}
      <button
        class="thumb-card"
        class:selected={isSelected}
        class:clickable={slot.src !== null}
        onclick={() => slot.src && pick(slot.combo, slot.src)}
        title="{slot.combo.model} | Post:{slot.combo.postProcess} | AC:{slot.combo.alphaClean}"
      >
        <div
          class="thumb-img"
          style={bgColor
            ? `background: ${bgColor};`
            : 'background-image: repeating-conic-gradient(#333 0% 25%, #252525 0% 50%); background-size: 12px 12px;'}
        >
          {#if slot.src}
            <img src={slot.src} alt={slot.combo.label} draggable="false" />
          {:else if slot.error}
            <span class="error-text">오류</span>
          {:else}
            <div class="thumb-spinner"></div>
            <span class="thinking-text">{randomThinking()}</span>
          {/if}
        </div>
        <div class="thumb-label">
          {slot.combo.label}
          {#if isSelected}<span class="check">✓</span>{/if}
        </div>
      </button>
    {/each}
  </div>
</div>

<style>
.auto-panel {
  background: #1a1a1a;
  border-top: 1px solid #333;
  padding: 10px 16px 12px;
  flex-shrink: 0;
}

.auto-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.auto-title {
  font-weight: 700;
  font-size: 0.88rem;
  color: #00d4aa;
  white-space: nowrap;
}

.auto-subtitle {
  font-size: 0.78rem;
  color: #888;
  flex: 1;
}

.close-btn {
  background: none;
  border: none;
  color: #666;
  font-size: 0.9rem;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 3px;
}
.close-btn:hover { color: #ff6b6b; background: #2a2a2a; }

.thumb-grid {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.thumb-card {
  background: #252525;
  border: 2px solid #333;
  border-radius: 6px;
  padding: 6px;
  cursor: default;
  transition: border-color 0.15s;
  text-align: center;
  width: 160px;
}

.thumb-card.clickable { cursor: pointer; }
.thumb-card.clickable:hover { border-color: #00d4aa88; }
.thumb-card.selected { border-color: #00d4aa; }

.thumb-img {
  width: 148px;
  height: 110px;
  border-radius: 3px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
}

.thumb-img img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  pointer-events: none;
}

.thumb-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid #333;
  border-top-color: #00d4aa;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 6px;
}

@keyframes spin { to { transform: rotate(360deg); } }

.thinking-text {
  font-size: 0.88rem;
  color: #d97757;
  font-style: italic;
}

.error-text { font-size: 0.72rem; color: #ff6b6b; }

.thumb-label {
  margin-top: 5px;
  font-size: 0.78rem;
  color: #ccc;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.check { color: #00d4aa; font-weight: 700; }
</style>
