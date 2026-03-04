from pathlib import Path


class FileTools:
    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root).resolve()

    def _resolve(self, rel_path: str) -> Path:
        p = (self.root / rel_path).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError("workspace 밖 접근은 금지됩니다")
        return p

    def list_dir(self, rel_path: str = ".") -> str:
        p = self._resolve(rel_path)
        if not p.exists():
            return "not found"
        return "\n".join(sorted([x.name for x in p.iterdir()]))

    def read_file(self, rel_path: str) -> str:
        p = self._resolve(rel_path)
        return p.read_text(encoding="utf-8")

    def write_file(self, rel_path: str, content: str) -> str:
        p = self._resolve(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"written: {rel_path}"

    def edit_replace(self, rel_path: str, old: str, new: str) -> str:
        p = self._resolve(rel_path)
        text = p.read_text(encoding="utf-8")
        if old not in text:
            return "old text not found"
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        return f"edited: {rel_path}"
