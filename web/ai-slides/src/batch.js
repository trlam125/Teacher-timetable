import { driveGeneration } from './generation.js';

// Only deck IDs/titles/progress belong in the persisted client queue.
export async function driveBatch(queue, { load, request, persist, onDeck = () => {} }) {
  for (const item of queue.items) {
    try {
      const current = await load(item.id);
      if (current.status === 'ready' && current.manifest?.slides?.length === current.profile.slide_count) {
        item.completed = true; await persist(queue); continue;
      }
      const result = await driveGeneration(current, { mode: 'automatic', request, onDeck });
      onDeck(result.deck);
      item.completed = result.state === 'ready';
      queue.paused = item.completed ? null : result.state;
      await persist(queue);
      if (!item.completed) return { state: result.state, deck: result.deck };
    } catch (error) {
      queue.paused = 'error'; queue.message = error.message;
      await persist(queue);
      throw error;
    }
  }
  queue.paused = null; queue.message = ''; await persist(queue);
  return { state: 'ready' };
}
