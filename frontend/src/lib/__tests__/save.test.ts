import { describe, expect, it } from "vitest";
import { uniqueName, type DirHandle } from "../save";

function folder(existing: string[]): DirHandle {
  return {
    name: "Episodes",
    async getFileHandle(name: string) {
      if (!existing.includes(name)) throw Object.assign(new Error("missing"), { name: "NotFoundError" });
      return { createWritable: async () => ({}) as never };
    },
  };
}

describe("uniqueName (never overwrite files in the chosen folder)", () => {
  it("keeps the name when it is free", async () => {
    expect(await uniqueName(folder([]), "Show - E01.mp4")).toBe("Show - E01.mp4");
  });
  it("adds (2), (3)… when taken", async () => {
    expect(await uniqueName(folder(["Show - E01.mp4"]), "Show - E01.mp4")).toBe("Show - E01 (2).mp4");
    expect(await uniqueName(folder(["a.zip", "a (2).zip"]), "a.zip")).toBe("a (3).zip");
  });
  it("propagates permission errors instead of guessing", async () => {
    const denied: DirHandle = {
      name: "x",
      async getFileHandle() {
        throw Object.assign(new Error("denied"), { name: "NotAllowedError" });
      },
    };
    await expect(uniqueName(denied, "a.mp4")).rejects.toThrow("denied");
  });
});
