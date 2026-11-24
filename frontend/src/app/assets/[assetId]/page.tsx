import { Suspense } from "react";
import { AssetDetail } from "@/components/asset-detail";

type Props = { params: Promise<{ assetId: string }> };

async function AssetContent({ params }: Props) {
  const { assetId } = await params;
  return <AssetDetail key={assetId} assetId={assetId} />;
}

export default function AssetPage({ params }: Props) {
  return (
    <Suspense fallback={<p role="status">Loading asset…</p>}>
      <AssetContent params={params} />
    </Suspense>
  );
}
