/* Saving finished files from the browser: a normal download, or into a user-chosen folder. */

// File System Access API (Chromium browsers). Declared locally: not in every TS DOM lib.
interface WritableFile {
  write(data: BufferSource | Blob): Promise<void>;
  close(): Promise<void>;
  abort(): Promise<void>;
}
interface FileHandle {
  createWritable(): Promise<WritableFile & WritableStream>;
}
export interface DirHandle {
  name: string;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FileHandle>;
}
export type PickerWindow = Window & { showDirectoryPicker?: (o?: { mode?: "readwrite" }) => Promise<DirHandle> };

export const folderPickerSupported = typeof window !== "undefined" && "showDirectoryPicker" in window;

/** "Name.mp4", or "Name (2).mp4" … if the folder already has a file with that name (never overwrite). */
export async function uniqueName(dir: DirHandle, filename: string): Promise<string> {
  const dot = filename.lastIndexOf(".");
  const stem = dot > 0 ? filename.slice(0, dot) : filename;
  const ext = dot > 0 ? filename.slice(dot) : "";
  for (let n = 1; n < 1000; n++) {
    const candidate = n === 1 ? filename : `${stem} (${n})${ext}`;
    try {
      await dir.getFileHandle(candidate);
    } catch (err) {
      if ((err as DOMException).name === "NotFoundError") return candidate;
      throw err;
    }
  }
  throw new Error("Too many files with this name in the folder.");
}

export async function saveToFolder(dir: DirHandle, url: string, filename: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok || !response.body) {
    let message = `MediaLab couldn't send the file (HTTP ${response.status}).`;
    try {
      message = (await response.json()).error?.message ?? message;
    } catch {
      /* not JSON */
    }
    throw new Error(message);
  }
  const name = await uniqueName(dir, filename);
  const handle = await dir.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  await response.body.pipeTo(writable); // aborts (and discards) the file if the transfer fails
  return name;
}

export function saveWithBrowser(url: string, filename: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}
