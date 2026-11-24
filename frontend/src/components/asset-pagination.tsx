export function AssetPagination({ offset, size, hasNext, onChange }: {
  offset: number;
  size: number;
  hasNext: boolean;
  onChange: (offset: number) => void;
}) {
  return (
    <nav className="asset-pagination" aria-label="Result pages">
      <button className="refresh-button" type="button" aria-disabled={offset === 0}
        onClick={() => { if (offset > 0) onChange(offset - size); }}>Previous</button>
      <span aria-live="polite">Page {Math.floor(offset / size) + 1}</span>
      <button className="refresh-button" type="button" aria-disabled={!hasNext}
        onClick={() => { if (hasNext) onChange(offset + size); }}>Next</button>
    </nav>
  );
}
