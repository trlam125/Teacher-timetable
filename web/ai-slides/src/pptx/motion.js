import {
  getShapeName, getSlideShapes, getSlides, loadPresentation, savePresentation,
  setShapeAnimation, setSlideTransition,
} from '@office-kit/pptx';

export async function addMotion(bytes, objectNames) {
  const presentation = await loadPresentation(bytes);
  for (const [index, slide] of getSlides(presentation).entries()) {
    setSlideTransition(slide, { effect: 'fade', speed: 'med' });
    const shapes = new Map(getSlideShapes(slide).map(shape => [getShapeName(shape), shape]));
    for (const [order, name] of (objectNames[index] || []).entries()) {
      const shape = shapes.get(name);
      if (!shape) throw new Error('Không tìm thấy đối tượng cần hiệu ứng.');
      setShapeAnimation(shape, order % 2 === 0
        ? { effect: 'appear', start: 'click' }
        : { effect: 'fadeIn', start: 'click', durationMs: 450 });
    }
  }
  return savePresentation(presentation);
}
