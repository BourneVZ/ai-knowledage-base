import type { Plugin } from "@opencode-ai/plugin";

const ARTICLES_PATTERN = /knowledge[/\\]articles[/\\].+\.json$/;

const server: Plugin = async (input) => {
  return {
    "tool.execute.after": async (event) => {
      const { tool, args } = event;

      if (tool !== "write" && tool !== "edit") return;

      const filePath: string | undefined = args.file_path ?? args.filePath;
      if (!filePath || typeof filePath !== "string") return;
      if (!ARTICLES_PATTERN.test(filePath)) return;

      try {
        await input.$`python hooks/validate_json.py ${filePath}`.nothrow();
      } catch {
        // 静默失败，不阻塞 Agent 主流程
      }
    },
  };
};

export default server;
