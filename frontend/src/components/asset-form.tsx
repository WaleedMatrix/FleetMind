"use client";

import { useState, type FormEvent } from "react";
import { fleetMindRequest } from "@/lib/api";
import { assetPath, type Asset } from "@/lib/assets";

export function AssetForm({ asset, onSave }: { asset?: Asset; onSave: (asset: Asset) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const fields = {
      display_name: String(data.get("display_name") ?? "").trim(),
      location: String(data.get("location") ?? "").trim() || null,
      description: String(data.get("description") ?? "").trim() || null,
    };
    const payload = asset ? fields : {
      ...fields, asset_id: data.get("asset_id"), machine_type: data.get("machine_type"),
    };
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const result = await fleetMindRequest<Asset>(asset ? assetPath(asset.asset_id) : "assets", {
        method: asset ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!asset) form.reset();
      onSave(result);
      setSaved(true);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Unable to save asset.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="asset-form" onSubmit={submit}>
      {!asset && (
        <>
          <label>Asset ID
            <input name="asset_id" required maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9_\-]*"
              title="Start with a letter or number. Use letters, numbers, underscores, or hyphens." />
          </label>
          <label>Machine type
            <select name="machine_type" required defaultValue="">
              <option value="" disabled>Choose a type</option>
              <option value="L">L</option><option value="M">M</option><option value="H">H</option>
            </select>
          </label>
        </>
      )}
      <label>Display name <input name="display_name" required maxLength={120} defaultValue={asset?.display_name} /></label>
      <label>Location <input name="location" maxLength={120} defaultValue={asset?.location ?? ""} /></label>
      <label className="asset-field-wide">Description
        <textarea name="description" rows={3} maxLength={1000} defaultValue={asset?.description ?? ""} />
      </label>
      <div className="asset-form-actions asset-field-wide">
        <button className="submit-btn" type="submit" disabled={saving}>
          {saving ? "Saving…" : asset ? "Save changes" : "Register asset"}
        </button>
        {saved && <span role="status">{asset ? "Changes saved." : "Asset registered."}</span>}
        {error && <span className="asset-error" role="alert">{error}</span>}
      </div>
    </form>
  );
}
