import { vietnamGeometry } from './map-data.js';

export function mapSvg() {
  const polygons = vietnamGeometry.type === 'Polygon' ? [vietnamGeometry.coordinates] : vietnamGeometry.coordinates;
  const paths = polygons.map(polygon => polygon[0].map(([lon, lat], index) =>
    `${index ? 'L' : 'M'}${((lon - 101.5) * 45).toFixed(2)},${((24 - lat) * 32).toFixed(2)}`
  ).join(' ') + ' Z');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="440" height="530" viewBox="0 0 440 530"><rect width="440" height="530" fill="#E7F0F5"/><path d="${paths.join(' ')}" fill="#90BAA0" stroke="#2D6653" stroke-width="2"/></svg>`;
}
