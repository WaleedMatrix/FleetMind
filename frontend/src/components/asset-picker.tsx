"use client";

import { useState } from "react";
import { assetSearchPath, type Asset } from "@/lib/assets";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";
import { AssetPagination } from "./asset-pagination";

const PAGE_SIZE = 8;

export function AssetPicker({ value, onChange }: { value: Asset | null; onChange: (asset: Asset | null) => void }) {
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const { data, error, pending } = useFleetMindQuery<Asset[]>(
    assetSearchPath(query, "", offset, PAGE_SIZE + 1), { delay: 180, revision },
  );
  const results = data?.slice(0, PAGE_SIZE) ?? [];
  const options = value && !results.some((asset) => asset.asset_id === value.asset_id)
    ? [value, ...results] : results;

  return (
    <div className="asset-picker">
      <label>Search registered assets
        <input type="search" maxLength={120} placeholder="Name, asset ID, or location" value={query}
          onChange={(event) => { setQuery(event.target.value); setOffset(0); }} />
      </label>
      <label>Assign to asset
        <select value={value?.asset_id ?? ""} onChange={(event) => {
          onChange(options.find((asset) => asset.asset_id === event.target.value) ?? null);
        }}>
          <option value="">Unassigned</option>
          {options.map((asset) => <option key={asset.asset_id} value={asset.asset_id}>{asset.display_name} ({asset.asset_id})</option>)}
        </select>
      </label>
      {error ? <div className="asset-query-error" role="alert">
        {error}<button className="refresh-button" type="button" onClick={() => setRevision((count) => count + 1)}>Retry assets</button>
      </div> : pending && !data ? <p className="asset-note" role="status">Loading assets…</p>
        : !results.length ? <p className="asset-note" role="status">No matching assets.</p> : null}
      {(offset > 0 || (data?.length ?? 0) > PAGE_SIZE) &&
        <AssetPagination offset={offset} size={PAGE_SIZE} hasNext={(data?.length ?? 0) > PAGE_SIZE} onChange={setOffset} />}
    </div>
  );
}
