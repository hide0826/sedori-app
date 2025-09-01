# -*- coding: utf-8 -*-
# HIRIO Memory MCP (pseudo) — save/get/search/pin + Files API (list/read)
# 127.0.0.1 限定・Bearer必須・UTF-8保存

from fastapi import FastAPI, Header, HTTPException, APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
import os, json, secrets, base64, shutil
from collections import defaultdict

# ========= 設定 =========
MEMORY_ROOT = Path(os.environ.get("MEMORY_ROOT", r"D:\\HIRIO\\repo\\sedori-app\\memory"))
TOKEN = os.environ.get("MEMORY_MCP_TOKEN", "change-me")
INDEX_PATH = MEMORY_ROOT / "index.jsonl"
MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
INDEX_PATH.touch(exist_ok=True)

# ========= モデル =========
class Meta(BaseModel):
    title: str = Field(..., description="1行タイトル")
    project: str = "sedori_app"
    vision: Optional[str] = None
    type: str = "note"  # decision/policy/update/todo/digest/idea/outline/draft/article/snippet
    tags: List[str] = []
    actor: str = "gpt"  # human:Hide/gpt/claude/gemini
    source: str = "manual"
    date: Optional[str] = None  # ISO8601推奨

class SaveReq(BaseModel):
    meta: Meta
    body: str

class SaveRes(BaseModel):
    id: str
    path: str

class SearchReq(BaseModel):
    q: Optional[str] = None
    filters: Dict[str, Any] = {}
    limit: int = 20

class SearchHit(BaseModel):
    id: str
    meta: Meta
    path: str
    snippet: str

class PinReq(BaseModel):
    id: str
    note: Optional[str] = None

# ========= ユーティリティ =========
def _auth(auth_header: Optional[str]):
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth_header.split(" ", 1)[1].strip()
    if token != TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

def _new_id() -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    rand = secrets.token_hex(3)  # 6 hex chars
    return f"{ts}-{rand}"

def _frontmatter(meta: Meta) -> str:
    # タイトル中の二重引用符を単引用符に置換してYAML安全化
    esc_title = (meta.title or "").replace('"', "'")
    lines = [
        "---",
        f'title: \"{esc_title}\"',
        f"project: {meta.project}",
        f"vision: {meta.vision if meta.vision else ''}",
        f"type: {meta.type}",
        "tags: [" + ", ".join(meta.tags) + "]",
        f"actor: {meta.actor}",
        f"source: {meta.source}",
        f"date: {meta.date if meta.date else datetime.now().isoformat(timespec='seconds')}",
        "---",
        "",
    ]
    return "\n".join(lines)


def _append_index(rec: dict):
    with INDEX_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def _iter_index():
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue

def _read_body(path: Path, limit_chars: Optional[int] = None) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    return text[:limit_chars] if limit_chars else text

# ========= アプリ =========
app = FastAPI(title="HIRIO Memory MCP (pseudo)")

@app.get("/health")
def health():
    return {"ok": True, "root": str(MEMORY_ROOT)}

@app.post("/memory/save", response_model=SaveRes)
def save(req: SaveReq, Authorization: Optional[str] = Header(None)):
    _auth(Authorization)
    doc_id = _new_id()
    y = datetime.now().strftime("%Y")
    m = datetime.now().strftime("%m")
    doc_dir = MEMORY_ROOT / y / m
    doc_dir.mkdir(parents=True, exist_ok=True)
    path = doc_dir / f"{doc_id}.md"
    content = f"{_frontmatter(req.meta)}{req.body}\n"
    path.write_text(content, encoding="utf-8")
    rec = {
        "id": doc_id,
        "meta": req.meta.dict(),
        "path": str(path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "pinned": False,
    }
    _append_index(rec)
    return SaveRes(id=doc_id, path=str(path))

@app.get("/memory/get/{doc_id}")
def get(doc_id: str, Authorization: Optional[str] = Header(None)):
    _auth(Authorization)
    for rec in _iter_index():
        if rec.get("id") == doc_id:
            body = _read_body(Path(rec["path"]))
            return {"id": doc_id, "meta": rec["meta"], "path": rec["path"], "body": body}
    raise HTTPException(status_code=404, detail="Not found")

@app.post("/memory/search", response_model=List[SearchHit])
def search(req: SearchReq, Authorization: Optional[str] = Header(None)):
    _auth(Authorization)
    hits: List[SearchHit] = []
    q = (req.q or "").lower()

    def match_filters(meta: dict) -> bool:
        for k, v in req.filters.items():
            if k not in meta:
                return False
            mv = meta[k]
            if isinstance(mv, list):
                if isinstance(v, str):
                    if v not in mv:
                        return False
                elif isinstance(v, list):
                    if not all(x in mv for x in v):
                        return False
            else:
                if str(v).lower() not in str(mv).lower():
                    return False
        return True

    for rec in _iter_index():
        meta = rec.get("meta", {})
        title = str(meta.get("title", ""))
        basic_ok = (q in title.lower()) or any(
            q in str(meta.get(k, "")).lower() for k in ("project", "vision", "type", "actor")
        ) or (q == "")
        if not basic_ok:
            try:
                snippet_src = _read_body(Path(rec["path"]), limit_chars=4096).lower()
                basic_ok = q in snippet_src
            except Exception:
                pass
        if basic_ok and match_filters(meta):
            snippet = _read_body(Path(rec["path"]), limit_chars=200).replace("\r", "")
            hits.append(SearchHit(id=rec["id"], meta=Meta(**meta), path=rec["path"], snippet=snippet))
            if len(hits) >= req.limit:
                break
    return hits

@app.post("/memory/pin")
def pin(req: PinReq, Authorization: Optional[str] = Header(None)):
    _auth(Authorization)
    rows = list(_iter_index())
    found = False
    for r in rows:
        if r.get("id") == req.id:
            r["pinned"] = True
            r["pin_note"] = req.note
            r["pin_date"] = datetime.now().isoformat(timespec="seconds")
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Not found")
    tmp = INDEX_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(INDEX_PATH)
    return {"ok": True, "id": req.id}

# ========= Files API (MVP) =========
files_router = APIRouter(prefix="/files", tags=["files"])

# 許可ルート（; 区切り）。未指定は D:\\HIRIO\\workspace
ALLOWED_ROOTS = [Path(p) for p in os.environ.get("ALLOWED_ROOTS", r"D:\\HIRIO\\workspace").split(";") if p.strip()]
ALLOWED_ROOTS = [p.resolve() for p in ALLOWED_ROOTS]

def _is_in_allowed(p: Path) -> bool:
    try:
        rp = p.resolve(strict=False)
    except Exception:
        rp = p
    for root in ALLOWED_ROOTS:
        try:
            rp.relative_to(root)
            return True
        except ValueError:
            continue
    return False
def _resolve_rel(rel: str) -> Path:
    rel = rel.lstrip("\/\/")
    for root in ALLOWED_ROOTS:
        cand = (root / rel).resolve(strict=False)
        if str(cand).startswith(str(root)):
            return cand
    raise HTTPException(status_code=400, detail="Path is outside allowed roots")

@files_router.get("/list")
def list_files(
    Authorization: Optional[str] = Header(None),
    subpath: str = "",
    exts: str = "",
    recursive: bool = False,
    limit: int = 200,
):
    _auth(Authorization)
    base = _resolve_rel(subpath)
    if not base.exists():
        raise HTTPException(status_code=404, detail="subpath not found")
    suffixes = [s.lower().strip() for s in exts.split(",") if s]
    items = []
    it = base.rglob("*") if recursive else base.glob("*")
    for p in it:
        if not p.is_file():
            continue
        if suffixes and p.suffix.lower() not in suffixes:
            continue
        if not _is_in_allowed(p):
            continue
        st = p.stat()
        try:
            rel = str(p.relative_to(ALLOWED_ROOTS[0]))
        except Exception:
            rel = str(p)
        items.append({
            "rel": rel,
            "name": p.name,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        })
        if len(items) >= limit:
            break
    return {"count": len(items), "base": str(base), "items": items}

@files_router.get("/read")
def read_file(
    Authorization: Optional[str] = Header(None),
    relpath: str = Query(..., description="許可ルートからの相対パス"),
    mode: str = Query("text", description="text|head|bytes"),
    max_bytes: int = 65536,
):
    _auth(Authorization)
    if mode not in ("text", "head", "bytes"):
        raise HTTPException(status_code=422, detail="mode must be one of: text|head|bytes")
    p = _resolve_rel(relpath)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    if not _is_in_allowed(p):
        raise HTTPException(status_code=403, detail="path not allowed")

    data = p.read_bytes()
    meta = {
        "name": p.name,
        "size": len(data),
        "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
        "path": str(p),
    }
    if mode == "text":
        try:
            return {"meta": meta, "text": data.decode("utf-8")}
        except UnicodeDecodeError:
            return {"meta": meta, "text": data.decode("utf-8", "replace")}
    if mode == "head":
        chunk = data[:max_bytes]
        try:
            return {"meta": meta, "text": chunk.decode("utf-8", "replace")}
        except Exception:
            return {"meta": meta, "bytes_b64": base64.b64encode(chunk).decode("ascii")}
    # bytes
    return {"meta": meta, "bytes_b64": base64.b64encode(data[:max_bytes]).decode("ascii")}

# --- /files/write -------------------------------------------------------------
# from pydantic import BaseModel # already imported
import shutil
# import secrets, base64, os # already imported
# from typing import Optional # already imported
# from datetime import datetime # already imported

class FileWriteReq(BaseModel):
    relpath: str
    mode: str = "text"         # "text" | "bytes"
    text: Optional[str] = None
    bytes_b64: Optional[str] = None
    overwrite: bool = True
    backup: bool = True

@files_router.post("/write")
def write_file(req: FileWriteReq, Authorization: Optional[str] = Header(None)):
    _auth(Authorization)

    # パス解決＆検証
    p = _resolve_rel(req.relpath)
    if not _is_in_allowed(p):
        raise HTTPException(status_code=403, detail="path not allowed")
    p.parent.mkdir(parents=True, exist_ok=True)

    # 上書き禁止なら衝突時に409
    if p.exists() and not req.overwrite:
        raise HTTPException(status_code=409, detail="file exists and overwrite=false")

    # データ決定
    if req.mode == "text":
        data = (req.text or "").encode("utf-8")
    elif req.mode == "bytes":
        if not req.bytes_b64:
            raise HTTPException(status_code=422, detail="bytes_b64 required for mode=bytes")
        try:
            data = base64.b64decode(req.bytes_b64)
        except Exception:
            raise HTTPException(status_code=422, detail="invalid base64")
    else:
        raise HTTPException(status_code=422, detail="mode must be 'text' or 'bytes'")

    # 既存バックアップ
    if req.backup and p.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = p.parent / f"{p.name}__{ts}.bak"
        try:
            shutil.copy2(p, bak)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"backup failed: {e}")

    # 同一ディレクトリに一時ファイルを書いて置換（同一ボリュームなら実質アトミック）
    tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}.{secrets.token_hex(2)}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        tmp.replace(p)
    finally:
        try:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        except Exception:
            pass

    st = p.stat()
    return {
        "ok": True,
        "meta": {
            "path": str(p),
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        }
    }

# ルータ登録
app.include_router(files_router)

# === CSV API (MVP) ============================================================
# from fastapi import APIRouter, Header, HTTPException # already imported
# from pydantic import BaseModel, Field # already imported
# from typing import Optional, List, Dict, Any # already imported
# from pathlib import Path # already imported
# from datetime import datetime # already imported
import csv, io, unicodedata, re
# import os, base64 # already imported

# ==== CSV プリセット読み込み ================================================
# memory_mcp.py から見たリポジトリルート（sedori-app）を推定
REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PRESET_DIR = REPO_ROOT / "config" / "csv_presets"
CSV_PRESET_DIR.mkdir(parents=True, exist_ok=True)

def _load_csv_preset(name: str) -> dict:
    """
    config/csv_presets/<name>.json を読む（UTF-8）。
    例のキー:
      {
        "header_map": {"JAN":"jan","商品名":"name",...},
        "order": ["jan","name","price","stock"],
        "required_headers": ["jan","name","price"],
        "encoding_out": "cp932",        # 省略可
        "newline_out": "CRLF",          # "CRLF" | "LF" （省略可）
        "trim_whitespace": true,        # 省略可
        "drop_empty_rows": true         # 省略可
      }
    """
    p = CSV_PRESET_DIR / f"{name}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"preset not found: {name}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"preset load failed: {e}")

# --- atomic write helper -----------------------------------------------------
def _atomic_write_bytes(p: Path, data: bytes, backup: bool = True) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if backup and p.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = p.parent / f"{p.name}__{ts}.bak"
        try:
            shutil.copy2(p, bak)
        except Exception:
            pass
    tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}.{secrets.token_hex(3)}")
    with open(tmp, "wb") as f:
        f.write(data)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass
    os.replace(tmp, p)
    try:
        if tmp.exists():
            tmp.unlink()
    except Exception:
        pass

# === Validation (streaming, no pandas) ========================================
class ValidateRules(BaseModel):
    numeric_columns: List[str] = []
    integer_columns: List[str] = []
    nonnegative_columns: List[str] = []
    unique_columns: List[str] = []
    patterns: Dict[str, str] = {}
    empty_forbidden_columns: List[str] = []

def _is_empty(v: Optional[str]) -> bool:
    return v is None or str(v).strip() == ""

def _to_num(s: str):
    try:
        s2 = str(s).replace(",", "").strip()
        if s2 == "":
            return None
        return float(s2)
    except Exception:
        return None

class RowValidator:
    def __init__(self, headers_out: List[str], rules: ValidateRules):
        self.headers = headers_out
        self.rules = rules or ValidateRules()
        self.unique_seen = {c: defaultdict(list) for c in (self.rules.unique_columns or []) if c in headers_out}
        self.patterns = {}
        for col, pat in (self.rules.patterns or {}).items():
            try:
                self.patterns[col] = re.compile(pat)
            except re.error:
                pass
        self.issues = []

    def feed(self, rowdict: Dict[str, str], rownum: int):
        empty_cols = self.rules.empty_forbidden_columns or []
        for col in empty_cols:
            if col in rowdict and _is_empty(rowdict[col]):
                self.issues.append({"row": rownum, "column": col, "rule": "empty", "value": None, "message": "empty value"})
        for col in (self.rules.numeric_columns or []):
            if col in rowdict and not _is_empty(rowdict[col]):
                v = _to_num(rowdict[col])
                if v is None:
                    self.issues.append({"row": rownum, "column": col, "rule": "numeric", "value": str(rowdict[col]), "message": "not numeric"})
        for col in (self.rules.integer_columns or []):
            if col in rowdict and not _is_empty(rowdict[col]):
                v = _to_num(rowdict[col])
                if v is None or (v % 1) != 0:
                    self.issues.append({"row": rownum, "column": col, "rule": "integer", "value": str(rowdict[col]), "message": "not integer"})
        for col in (self.rules.nonnegative_columns or []):
            if col in rowdict and not _is_empty(rowdict[col]):
                v = _to_num(rowdict[col])
                if v is not None and v < 0:
                    self.issues.append({"row": rownum, "column": col, "rule": "nonnegative", "value": str(rowdict[col]), "message": "negative value"})
        for col, rx in self.patterns.items():
            if col in rowdict and not _is_empty(rowdict[col]):
                if not rx.fullmatch(str(rowdict[col])):
                    self.issues.append({"row": rownum, "column": col, "rule": "pattern", "value": str(rowdict[col]), "message": f"not match: {rx.pattern}"})
        for col, store in self.unique_seen.items():
            if col in rowdict and not _is_empty(rowdict[col]):
                store[str(rowdict[col])].append(rownum)

    def finalize(self):
        for col, store in self.unique_seen.items():
            for val, rows in store.items():
                if len(rows) > 1:
                    for rn in rows:
                        self.issues.append({"row": rn, "column": col, "rule": "unique", "value": val, "message": "duplicate"})
        self.issues.sort(key=lambda x: (x['row'], x['column']))
        return self.issues

def write_report_csv(report_path: Path, issues: List[Dict], newline_out: str = "CRLF"):
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lineterm = "\r\n" if (newline_out or "CRLF").upper() == "CRLF" else "\n"
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=lineterm)
    w.writerow(["row","column","rule","value","message"])
    for it in issues:
        w.writerow([it.get("row"), it.get("column"), it.get("rule"), it.get("value"), it.get("message")])
    data = buf.getvalue().encode("utf-8-sig", errors="replace")
    _atomic_write_bytes(report_path, data, backup=True)
    st = report_path.stat()
    by_rule = defaultdict(int)
    for it in issues:
        by_rule[it.get("rule")] += 1
    return {
        "path": str(report_path),
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "issues": int(len(issues)),
        "by_rule": dict(by_rule),
    }

csv_router = APIRouter(prefix="/csv", tags=["csv"])


# ---- helpers ----
def _csv_detect_encoding(data: bytes) -> str:
    # BOM優先
    if data.startswith(b'\xef\xbb\xbf'):
        return "utf-8-sig"
    # utf-8素で読める?
    try:
        data.decode("utf-8")
        return "utf-8"
    except Exception:
        pass
    # 日本語Windows想定の既定: cp932
    try:
        data.decode("cp932")
        return "cp932"
    except Exception:
        pass
    return "latin-1"

def _csv_detect_newline(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n")
    return "CRLF" if crlf >= lf else "LF"

def _csv_sniff(text: str):
    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample)
        has_header = csv.Sniffer().has_header(sample)
        return dialect, has_header
    except Exception:
        class _D: pass
        d = _D(); d.delimiter = ","; d.quotechar = '"'; d.doublequote = True; d.escapechar = None
        return d, True

_ws = re.compile(r"\s+")
def _csv_norm_header(name: str) -> str:
    if name is None: return ""
    name = name.replace("\ufeff", "")  # BOM
    name = unicodedata.normalize("NFKC", name)
    name = name.strip()
    name = _ws.sub(" ", name)
    return name

def _csv_open_reader_text(p: Path, encoding: str, dialect) -> csv.DictReader:
    text = p.read_text(encoding=encoding, errors="replace")
    return csv.DictReader(io.StringIO(text), dialect=dialect)

def _csv_rel_to_abs(rel: str) -> Path:
    rel = rel.lstrip(":/\\")
    for root in ALLOWED_ROOTS:
        cand = (root / rel).resolve(strict=False)
        if str(cand).startswith(str(root)):
            return cand
    raise HTTPException(status_code=400, detail="Path is outside allowed roots")

# ---- request models ----
class InspectReq(BaseModel):
    relpath: str
    sample_rows: int = 10

class NormalizeReq(BaseModel):
    relpath_in: str
    relpath_out: str
    encoding_in: str = "auto"
    encoding_out: str = "utf-8-sig"
    newline_out: str = "CRLF"
    header_map: Dict[str, str] = {}
    required_headers: List[str] = []
    order: List[str] = []
    trim_whitespace: bool = True
    drop_empty_rows: bool = True
    preset: Optional[str] = None
    report_relpath: Optional[str] = None
    validate: Optional[ValidateRules] = None

class ExportReq(BaseModel):
    relpath_out: str
    rows: List[Dict[str, Any]]
    columns: Optional[List[str]] = None
    encoding_out: str = "utf-8-sig"   # utf-8|utf-8-sig|cp932
    newline_out: str = "CRLF"         # CRLF|LF

# ---- endpoints ----
@csv_router.post("/inspect")
def csv_inspect(req: InspectReq, Authorization: Optional[str] = Header(None)):
    _auth(Authorization)
    p = _csv_rel_to_abs(req.relpath)
    if not p.exists(): raise HTTPException(404, "file not found")
    data = p.read_bytes()
    enc = _csv_detect_encoding(data)
    nl = _csv_detect_newline(data)
    # テキスト取得（BOMは utf-8-sig で吸収）
    text = data.decode(enc, errors="replace")
    dialect, has_header = _csv_sniff(text)
    rdr = csv.reader(io.StringIO(text), delimiter=dialect.delimiter, quotechar=dialect.quotechar)
    rows = []
    for i, row in enumerate(rdr):
        rows.append(row)
        if len(rows) >= max(req.sample_rows, 10): break
    headers = [_csv_norm_header(h) for h in (rows[0] if rows else [])] if has_header else []
    warnings = []
    if headers and len(headers) != len(set(headers)):
        warnings.append("duplicate headers after normalization")
    meta = {
        "path": str(p), "size": len(data),
        "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
    }
    # サンプル行を dict 化（ヘッダありのとき）
    sample = []
    if headers and len(rows) > 1:
        for r in rows[1:]:
            sample.append({headers[i] if i < len(headers) else f"_{i}": (r[i] if i < len(r) else "") for i in range(max(len(headers), len(r)))})
    return {"meta": meta, "encoding": enc, "newline": nl,
            "delimiter": dialect.delimiter, "quotechar": dialect.quotechar,
            "has_header": has_header, "headers": headers, "sample": sample, "warnings": warnings}

@csv_router.post("/normalize")
def csv_normalize(req: NormalizeReq, Authorization: Optional[str] = Header(None)):
    _auth(Authorization)
    
    # === preset の適用（request明示 > preset > デフォルト） ===
    fields_set = getattr(req, "__fields_set__", set())
    preset = {}
    if req.preset:
        preset = _load_csv_preset(req.preset)

    # header_map（マージ）
    if "header_map" in preset and isinstance(preset["header_map"], dict):
        merged = dict(preset["header_map"])
        merged.update(req.header_map or {})
        req.header_map = merged

    # 単純上書き（未指定フィールドのみ preset 反映）
    def _apply_if_unset(field: str, preset_key: str = None):
        k = preset_key or field
        if k in preset and field not in fields_set:
            setattr(req, field, preset[k])

    for f in ("order", "required_headers", "trim_whitespace", "drop_empty_rows", "encoding_out", "newline_out"):
        _apply_if_unset(f)

    # ==== Validation Rules Setup ====
    rules = req.validate or ValidateRules()
    if not rules.empty_forbidden_columns:
        rules.empty_forbidden_columns = req.required_headers or []

    pin = _csv_rel_to_abs(req.relpath_in)
    pout = _csv_rel_to_abs(req.relpath_out)
    if not pin.exists(): raise HTTPException(404, "file not found")
    data = pin.read_bytes()
    enc_in = _csv_detect_encoding(data) if req.encoding_in == "auto" else req.encoding_in
    text = data.decode(enc_in, errors="replace")
    dialect, has_header = _csv_sniff(text)
    rdr = csv.reader(io.StringIO(text), delimiter=dialect.delimiter, quotechar=dialect.quotechar)

    rows_iter = iter(rdr)
    raw_headers = next(rows_iter, [])
    norm_headers = [_csv_norm_header(h) for h in (raw_headers if has_header else [])] if has_header else [f"c{i}" for i in range(len(raw_headers))]
    
    # マップ適用（キーは正規化前後どちらでもヒットさせる）
    mapped = []
    for h in norm_headers:
        h2 = req.header_map.get(h, None)
        if h2 is None:
            # 正規化前名でも探す（大雑把）
            cand = [k for k in req.header_map.keys() if _csv_norm_header(k) == h]
            h2 = req.header_map[cand[0]] if cand else h
        mapped.append(_csv_norm_header(h2))

    # 必須列チェック（rename 後）
    missing = [h for h in (req.required_headers or []) if h not in mapped]
    if missing:
        raise HTTPException(status_code=422, detail={"missing_required_headers": missing})

    # 出力列順
    out_cols = req.order[:] if req.order else mapped[:]

    # ==== Validator init ====
    validator = RowValidator(out_cols, rules)
    
    # 出力準備
    enc_out = req.encoding_out
    nl = "\r\n" if req.newline_out.upper() == "CRLF" else "\n"
    pout.parent.mkdir(parents=True, exist_ok=True)
    fout = io.open(pout, "w", encoding=enc_out, newline='', errors="replace")
    w = csv.writer(fout, lineterminator=nl)
    w.writerow(out_cols)

    in_count = 0; out_count = 0
    for row in rows_iter:
        in_count += 1
        rec = {mapped[i] if i < len(mapped) else f"c{i}": (row[i] if i < len(row) else "") for i in range(max(len(mapped), len(row)))}
        if req.trim_whitespace:
            rec = {k: (v.strip() if isinstance(v, str) else v) for k, v in rec.items()}
        # 並び替え・欠損は空文字で補完
        out_row = [ rec.get(col, "") for col in out_cols ]
        
        # ==== Validate row ====
        rownum = 2 + in_count # 1-based header, so data starts at 2
        rowdict = { col: out_row[i] if i < len(out_row) else "" for i, col in enumerate(out_cols) }
        validator.feed(rowdict, rownum)

        if req.drop_empty_rows and all((str(x) == "" for x in out_row)):
            continue
        w.writerow(out_row); out_count += 1
    fout.close()

    st = pout.stat()

    # ==== Validation & Report Finalize ====
    report_meta = None
    issues = validator.finalize()
    if req.report_relpath:
        try:
            p_rep = _csv_rel_to_abs(req.report_relpath)
            if not _is_in_allowed(p_rep):
                raise HTTPException(status_code=403, detail="report path not allowed")
            report_meta = write_report_csv(p_rep, issues, newline_out=req.newline_out)
        except Exception as e:
            report_meta = {"error": str(e)}

    report = {
        "io": {
            "in_path": str(pin),
            "out_path": str(pout),
            "in_encoding": enc_in, "out_encoding": enc_out,
            "rows_in": in_count, "rows_out": out_count,
            "out_size": st.st_size,
            "out_mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        },
        "headers": {
            "in_normalized": norm_headers,
            "out": out_cols
        },
        "validation": report_meta
    }
    return {"ok": True, "report": report}

@csv_router.post("/export")
def csv_export(req: ExportReq, Authorization: Optional[str] = Header(None)):
    _auth(Authorization)
    pout = _csv_rel_to_abs(req.relpath_out)
    pout.parent.mkdir(parents=True, exist_ok=True)
    cols = req.columns[:] if req.columns else (list(req.rows[0].keys()) if req.rows else [])
    nl = "\r\n" if req.newline_out.upper() == "CRLF" else "\n"
    enc_out = req.encoding_out
    with io.open(pout, "w", encoding=enc_out, newline='', errors="replace") as f:
        w = csv.writer(f, lineterminator=nl)
        w.writerow(cols)
        for r in req.rows:
            w.writerow([r.get(c, "") for c in cols])
    st = pout.stat()
    return {"ok": True, "meta": {"path": str(pout), "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"), "columns": cols}}



# === CSV Bulk Normalize (MVP) ================================================
from typing import Optional, List, Dict
from fastapi import Header, HTTPException
import os
from pathlib import Path

class BulkNormalizeReq(BaseModel):
    # どのファイルを対象にするか
    subpath: str = ""
    pattern: str = "*.csv"
    recursive: bool = False
    # 出力と命名
    output_dir: str = "out"
    out_suffix: str = "_norm.csv"
    report_dir: Optional[str] = "out"
    # 正規化オプション（NormalizeReq へ委譲）
    preset: Optional[str] = None
    encoding_in: Optional[str] = None
    encoding_out: Optional[str] = None
    newline_out: Optional[str] = None
    header_map: Dict[str, str] = Field(default_factory=dict)
    required_headers: List[str] = Field(default_factory=list)
    order: List[str] = Field(default_factory=list)
    trim_whitespace: Optional[bool] = None
    drop_empty_rows: Optional[bool] = None
    validate: Optional[ValidateRules] = None
    overwrite: bool = True
    backup: bool = True
    # 運用
    dry_run: bool = False
    fail_fast: bool = False

def _allowed_roots() -> List[Path]:
    roots = [r.strip() for r in os.environ.get("ALLOWED_ROOTS","").split(";") if r.strip()]
    return [Path(r).resolve() for r in roots if r]

def _rel_from_root(abs_path: Path, root: Path) -> str:
    try:
        return str(abs_path.resolve().relative_to(root))
    except Exception:
        # ルート外は無視
        raise HTTPException(status_code=403, detail="path out of allowed roots")

@csv_router.post("/bulk_normalize")
def csv_bulk_normalize(req: BulkNormalizeReq, Authorization: Optional[str] = Header(None)):
    _auth(Authorization)

    roots = _allowed_roots()
    if not roots:
        raise HTTPException(status_code=500, detail="ALLOWED_ROOTS not set")

    # 対象ファイルを収集
    matches: List[Dict] = []
    for root in roots:
        base = (root / req.subpath).resolve()
        if not base.exists():
            continue
        it = base.rglob(req.pattern) if req.recursive else base.glob(req.pattern)
        for p in it:
            if p.is_file() and _is_in_allowed(p):
                rel = _rel_from_root(p, root)
                matches.append({"root": str(root), "abs": str(p), "rel": rel})

    if req.dry_run:
        return {"ok": True, "matched": len(matches), "preview": [m["rel"] for m in matches]}

    if not matches:
        return {"ok": True, "matched": 0, "succeeded": 0, "failed": 0, "items": []}

    # Authorization を内部呼び出し用に確保
    auth_val = Authorization
    if not auth_val:
        tok = os.environ.get("MEMORY_MCP_TOKEN")
        auth_val = f"Bearer {tok}" if tok else None

    items = []
    total_issues = 0
    succeeded = 0

    for m in matches:
        in_rel = m["rel"].replace("\\", "/")
        stem = Path(in_rel).stem
        out_rel = str(Path(req.output_dir) / f"{stem}{req.out_suffix}")
        report_rel = (str(Path(req.report_dir) / f"{stem}__report.csv") if req.report_dir else None)

        # NormalizeReq に渡す payload（未指定は鍵ごと渡さない＝デフォルト／preset適用を維持）
        payload: Dict = {
            "relpath_in": in_rel,
            "relpath_out": out_rel,
            "overwrite": req.overwrite,
            "backup": req.backup,
        }
        if req.preset is not None:           payload["preset"] = req.preset
        if req.encoding_in is not None:      payload["encoding_in"] = req.encoding_in
        if req.encoding_out is not None:     payload["encoding_out"] = req.encoding_out
        if req.newline_out is not None:      payload["newline_out"] = req.newline_out
        if req.header_map:                    payload["header_map"] = req.header_map
        if req.required_headers:              payload["required_headers"] = req.required_headers
        if req.order:                         payload["order"] = req.order
        if req.trim_whitespace is not None:  payload["trim_whitespace"] = req.trim_whitespace
        if req.drop_empty_rows is not None:  payload["drop_empty_rows"] = req.drop_empty_rows
        if report_rel:                        payload["report_relpath"] = report_rel
        if req.validate is not None:          payload["validate"] = req.validate.dict()

        try:
            nr = NormalizeReq(**payload)
            res = csv_normalize(nr, Authorization=auth_val)  # 既存の単発処理を再利用
            issues = int(((res or {}).get("report") or {}).get("issues", 0) or 0)
            total_issues += issues
            items.append({
                "ok": True,
                "input": in_rel,
                "output": res.get("output", {}).get("path", ""),
                "issues": issues,
                "report": res.get("report"),
            })
            succeeded += 1
        except HTTPException as he:
            items.append({"ok": False, "input": in_rel, "error": he.detail})
            if req.fail_fast:
                break
        except Exception as e:
            items.append({"ok": False, "input": in_rel, "error": str(e)})
            if req.fail_fast:
                break

    failed = len(items) - succeeded
    return {
        "ok": failed == 0,
        "matched": len(matches),
        "succeeded": succeeded,
        "failed": failed,
        "total_issues": total_issues,
        "items": items,
    }


# ルータ登録（重複回避）
try:
    app.include_router(csv_router)
except Exception:
    pass
