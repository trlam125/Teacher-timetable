// Client orchestration only. Each successful API step remains the source of truth.
// No inference retry, background resume or download is triggered here.
export async function driveGeneration(initial, {
  request, onDeck = () => {}, onProgress = () => {},
  firstStep = initial.blueprint ? 'author' : 'plan',
  mode = initial.profile.generation_mode || 'outline',
} = {}) {
  let current = initial;
  let next = firstStep;
  const total = initial.profile.slide_count;
  const bound = 1 + Math.ceil(total / 5);
  const stop = state => ({ deck: current, state });
  for (let turn = 0; turn < bound; turn += 1) {
    if (current.source_analysis?.unresolved) return stop('needs_source_review');
    if (!current.profile.consent) return stop('needs_consent');
    if (current.busy) return stop('busy');
    if (next === 'author') {
      if (current.status === 'ready' && current.manifest?.slides?.length === total) return stop('ready');
      if (!current.blueprint || current.blueprint.warnings?.length || current.status === 'needs_review') return stop('needs_review');
      if (current.profile.grounding === 'strict' && current.blueprint.grounding_version !== 'extractive-v1') return stop('needs_replan');
    }
    onProgress(next, current);
    const updated = await request(next, current);
    if (!updated || updated.id !== initial.id || !Number.isInteger(updated.version) || updated.version <= current.version) {
      throw new Error('Chưa nhận được phiên bản mới của bài. Hãy mở lại bài từ thư viện để kiểm tra.');
    }
    if (next === 'plan' && !updated.blueprint) throw new Error('Chưa có dàn ý hợp lệ để soạn tiếp.');
    if (next === 'author') {
      const before = current.manifest?.slides?.length || 0;
      const after = updated.manifest?.slides?.length || 0;
      if (after <= before || after > total || (updated.status === 'ready' && after !== total)) {
        throw new Error('Tiến độ soạn không tăng đúng. Hãy mở lại bài trước khi tiếp tục.');
      }
    }
    current = updated;
    onDeck(current);
    if (current.source_analysis?.unresolved) return stop('needs_source_review');
    if (current.status === 'needs_review' || current.blueprint?.warnings?.length) return stop('needs_review');
    if (next === 'plan' && mode === 'outline') return stop('outline');
    if (current.status === 'ready' && current.manifest?.slides?.length === total) return stop('ready');
    if (next === 'author' && current.status !== 'authoring') throw new Error('Trạng thái soạn chưa rõ. Hãy mở lại bài từ thư viện.');
    next = 'author';
  }
  throw new Error('Đã dừng ở giới hạn bước soạn. Hãy mở lại bài để kiểm tra tiến độ.');
}
