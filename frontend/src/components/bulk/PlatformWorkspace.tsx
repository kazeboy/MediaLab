import { useState, type ComponentProps } from "react";
import type { Platform } from "../../lib/types";
import { Tabs, tabPanelProps } from "../ui";
import { Workspace } from "../Workspace";
import { BulkWorkspace } from "./BulkWorkspace";

type Mode = "single" | "bulk";

/**
 * X and TikTok Videos: Single (one link, unchanged) or Bulk (a list of links). Both stay mounted,
 * so switching never discards an analysis, a pasted list or a running download.
 */
export function PlatformWorkspace(props: ComponentProps<typeof Workspace> & { platform: "x" | "tiktok" }) {
  const [mode, setMode] = useState<Mode>("single");
  const prefix = `${props.platform}-mode`;
  // A link handed over from another tab opens in Single mode, where it is analysed at once.
  const switchTo = (platform: Platform, url: string) => props.onSwitch(platform, url);
  const incomingNonce = props.incoming?.nonce;
  const [lastNonce, setLastNonce] = useState(incomingNonce);
  if (incomingNonce !== lastNonce) {
    setLastNonce(incomingNonce);
    if (mode !== "single") setMode("single");
  }

  return (
    <div className="space-y-5">
      <Tabs<Mode>
        variant="segmented"
        label={`${props.platform === "x" ? "X" : "TikTok"} download mode`}
        idPrefix={prefix}
        value={mode}
        onChange={setMode}
        items={[
          { id: "single", label: "Single" },
          { id: "bulk", label: "Bulk" },
        ]}
      />
      <div {...tabPanelProps(prefix, "single", mode === "single")}>
        <Workspace {...props} />
      </div>
      <div {...tabPanelProps(prefix, "bulk", mode === "bulk")}>
        <BulkWorkspace platform={props.platform} settings={props.settings} onSwitch={switchTo} />
      </div>
    </div>
  );
}
