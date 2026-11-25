"use client";

import { useEngineering } from "@/components/auth-shell";

import { useState } from "react";
import Link from "next/link";
import { ChevronRight, Factory, MapPin } from "lucide-react";
import { assetPath, assetSearchPath, type Asset, type MachineType } from "@/lib/assets";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";
import { AssetForm } from "./asset-form";
import { AssetPagination } from "./asset-pagination";

const PAGE_SIZE = 8;

export function AssetRegistry() {
  const canEngineer = useEngineering();
  const [query, setQuery] = useState("");
  const [type, setType] = useState<MachineType | "">("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [registered, setRegistered] = useState<Asset | null>(null);
  const { data, error, pending } = useFleetMindQuery<Asset[]>(
    assetSearchPath(query, type, offset, PAGE_SIZE + 1), { delay: 180, revision },
  );
  const assets = data?.slice(0, PAGE_SIZE) ?? [];

  return (
    <>
      <header className="page-heading">
        <div><h1>Asset <span>intelligence.</span></h1><p>Register equipment and inspect its recorded assessments.</p></div>
      </header>
      <section className={canEngineer ? "asset-registry-grid" : ""} aria-label="Asset registry">
        <div className="panel asset-panel">
          <h2>Asset registry</h2>
          <div className="asset-toolbar">
            <label>Search assets
              <input type="search" placeholder="Name, asset ID, or location" maxLength={120} value={query}
                onChange={(event) => { setQuery(event.target.value); setOffset(0); }} />
            </label>
            <label>Machine type
              <select value={type} onChange={(event) => { setType(event.target.value as MachineType | ""); setOffset(0); }}>
                <option value="">All types</option><option value="L">L</option><option value="M">M</option><option value="H">H</option>
              </select>
            </label>
          </div>
          {error && <div className="asset-query-error" role="alert">
            {error}<button className="refresh-button" onClick={() => setRevision((value) => value + 1)}>Retry</button>
          </div>}
          <div aria-busy={pending}>
            {assets.length > 0 ? (
              <ul className="asset-list">
                {assets.map((asset) => (
                  <li key={asset.asset_id}>
                    <Link href={`/${assetPath(asset.asset_id)}`}>
                      <span className="asset-list-icon"><Factory size={18} aria-hidden="true" /></span>
                      <span className="asset-list-name"><strong>{asset.display_name}</strong><small>{asset.asset_id} · Type {asset.machine_type}</small></span>
                      {asset.location && <span className="asset-location"><MapPin size={14} aria-hidden="true" />{asset.location}</span>}
                      <ChevronRight size={18} aria-hidden="true" />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : !error && (
              <p className="asset-empty" role="status">{pending ? "Loading assets…"
                : offset > 0 ? "No assets on this page."
                : query.trim() || type ? "No assets match these filters." : "No assets registered yet."}</p>
            )}
          </div>
          <AssetPagination offset={offset} size={PAGE_SIZE}
            hasNext={(data?.length ?? 0) > PAGE_SIZE} onChange={setOffset} />
        </div>
        {canEngineer && <div className="panel asset-panel asset-registration">
          <h2>Register an asset</h2>
          <p className="asset-note">Use the equipment’s asset ID and machine type. These fields stay fixed across assessments.</p>
          <AssetForm onSave={(asset) => { setRegistered(asset); setRevision((value) => value + 1); }} />
          {registered && <Link className="asset-inline-link" href={`/${assetPath(registered.asset_id)}`}>Open {registered.display_name} →</Link>}
        </div>}
      </section>
    </>
  );
}
