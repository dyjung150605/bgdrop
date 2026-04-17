<script lang="ts">
  let { onBrowse }: { onBrowse: () => void } = $props();
</script>

<div class="dropzone" role="button" tabindex="0"
  onclick={onBrowse}
  onkeydown={(e) => e.key === 'Enter' && onBrowse()}
>
  <div class="icon">⬇</div>
  <p class="title">DROP IMAGE HERE</p>
  <p class="subtitle">or click to browse &nbsp;·&nbsp; JPG / PNG / WEBP / BMP</p>
</div>

<style>
.dropzone {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 2px dashed #555;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.dropzone:hover {
  border-color: #00d4aa;
  background: rgba(0, 212, 170, 0.04);
}

.icon {
  font-size: 2.4rem;
  color: #555;
}

.title {
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #e0e0e0;
}

.subtitle {
  font-size: 0.82rem;
  color: #888;
}
</style>
