"""실제 문서 파일(.pdf / .md / .txt) 기반 LangChain + ChromaDB 영속형 RAG 서비스."""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
import pymupdf
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import rag_min_score

BASE_DIR = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge_base"
CHROMA_DIR = KNOWLEDGE_BASE_DIR / "chroma_db"


class KoreanMedicalLocalEmbedding(EmbeddingFunction[Documents]):
    """API 키 미설정 환경에서도 동작하는 로컬 한국어 의료 키워드+바이그램 임베딩."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        clean = re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", text.lower())
        tokens = clean.split()
        features: List[str] = []
        for tok in tokens:
            features.append(tok)
            if len(tok) >= 2:
                for i in range(len(tok) - 1):
                    features.append(tok[i : i + 2])
        for feat in features:
            digest = hashlib.md5(feat.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def __call__(self, input: Documents) -> Embeddings:
        return [self._embed_one(doc) for doc in input]


class OpenAIChromaEmbedding(EmbeddingFunction[Documents]):
    """LangChain OpenAIEmbeddings를 ChromaDB EmbeddingFunction으로 래핑한다."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        from langchain_openai import OpenAIEmbeddings

        self._emb = OpenAIEmbeddings(model=model, api_key=api_key)

    def __call__(self, input: Documents) -> Embeddings:
        return self._emb.embed_documents(list(input))


def _infer_category(filename: str, text: str) -> str:
    name = filename.lower()
    if "disease_code" in name or "kcd" in name:
        return "질병정보"
    if "plain_language" in name or "terms" in name:
        return "의학용어"
    if "document_guide" in name:
        return "문서안내"
    combined = f"{filename} {text[:300]}"
    if any(k in combined for k in ("policy", "정책", "지원", "확진검사", "국가건강검진 안내", "제도")):
        return "정부정책"
    return "의학기준"


def _extract_title(filename: str, text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return Path(filename).stem


def load_knowledge_documents() -> List[Document]:
    """knowledge_base 디렉토리 내 모든 .pdf / .md / .txt 파일을 LangChain Document로 로드한다."""
    KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    docs: List[Document] = []

    for file_path in sorted(KNOWLEDGE_BASE_DIR.iterdir()):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            try:
                pdf_doc = pymupdf.open(str(file_path))
                for page_idx, page in enumerate(pdf_doc):
                    text = page.get_text("text").strip()
                    if not text:
                        continue
                    docs.append(
                        Document(
                            page_content=text,
                            metadata={
                                "source_file": file_path.name,
                                "page": page_idx + 1,
                                "title": f"{file_path.stem} (p.{page_idx + 1})",
                                "source": f"{file_path.name} (p.{page_idx + 1})",
                                "category": _infer_category(file_path.name, text),
                            },
                        )
                    )
                pdf_doc.close()
            except Exception:
                continue
        elif ext in (".md", ".txt"):
            text = file_path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue
            title = _extract_title(file_path.name, text)
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "source_file": file_path.name,
                        "page": 1,
                        "title": title,
                        "source": file_path.name,
                        "category": _infer_category(file_path.name, text),
                    },
                )
            )
    return docs


class ProductionMedicalRAG:
    """실제 파일 기반 LangChain TextSplitter + 영속형 ChromaDB RAG 엔진."""

    def __init__(self) -> None:
        KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=700,
            chunk_overlap=120,
            separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
        )
        self._last_signature: str = ""
        self._active_mode: str = "local"

    def _kb_signature(self) -> str:
        parts = []
        for p in sorted(KNOWLEDGE_BASE_DIR.iterdir()):
            if p.is_file() and p.suffix.lower() in (".pdf", ".md", ".txt"):
                stat = p.stat()
                parts.append(f"{p.name}:{stat.st_size}:{int(stat.st_mtime)}")
        return "|".join(parts)

    def _get_collection(self, api_key: str = ""):
        clean_key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
        if clean_key:
            try:
                emb = OpenAIChromaEmbedding(api_key=clean_key)
                col = self.client.get_or_create_collection(name="medihan_kb_openai", embedding_function=emb)
                self._active_mode = "OpenAIEmbeddings (text-embedding-3-small)"
                return col, True
            except Exception:
                pass
        col = self.client.get_or_create_collection(
            name="medihan_kb_local",
            embedding_function=KoreanMedicalLocalEmbedding(),
        )
        self._active_mode = "Local Hybrid Vector (ChromaDB)"
        return col, False

    def ensure_indexed(self, force: bool = False, api_key: str = "") -> int:
        sig = self._kb_signature()
        col, is_openai = self._get_collection(api_key=api_key)

        if not force and col.count() > 0 and sig == self._last_signature:
            return col.count()

        # 파일 변경이 있거나 강제 재인덱싱 시 컬렉션 재생성
        raw_docs = load_knowledge_documents()
        chunks = self.splitter.split_documents(raw_docs)

        col_name = col.name
        if col.count() > 0 and (force or sig != self._last_signature):
            try:
                self.client.delete_collection(col_name)
                col, is_openai = self._get_collection(api_key=api_key)
            except Exception:
                pass

        if chunks and col.count() == 0:
            ids = [f"chunk_{i}_{hashlib.md5(c.page_content.encode('utf-8')).hexdigest()[:8]}" for i, c in enumerate(chunks)]
            texts = [c.page_content for c in chunks]
            metadatas = [
                {
                    "source_file": str(c.metadata.get("source_file", "")),
                    "page": int(c.metadata.get("page", 1)),
                    "title": str(c.metadata.get("title", "")),
                    "source": str(c.metadata.get("source", "")),
                    "category": str(c.metadata.get("category", "의학기준")),
                }
                for c in chunks
            ]
            try:
                col.add(ids=ids, documents=texts, metadatas=metadatas)
            except Exception:
                # OpenAI 임베딩 실패(예: 잘못된 키) 시 로컬 컬렉션으로 자동 폴백
                if is_openai:
                    local_col = self.client.get_or_create_collection(
                        name="medihan_kb_local",
                        embedding_function=KoreanMedicalLocalEmbedding(),
                    )
                    if local_col.count() == 0:
                        local_col.add(ids=ids, documents=texts, metadatas=metadatas)
                    self._active_mode = "Local Hybrid Vector (ChromaDB Fallback)"
                    self._last_signature = sig
                    return local_col.count()

        self._last_signature = sig
        return col.count()

    def search(
        self,
        query: str,
        category: Optional[Any] = None,
        top_k: int = 3,
        api_key: str = "",
    ) -> List[Dict[str, Any]]:
        self.ensure_indexed(force=False, api_key=api_key)
        col, is_openai = self._get_collection(api_key=api_key)
        if col.count() == 0:
            return []

        if isinstance(category, (list, tuple)):
            where_filter = {"category": {"$in": list(category)}}
        else:
            where_filter = {"category": category} if category else None
        n_res = min(max(top_k * 2, 5), col.count())
        try:
            res = col.query(query_texts=[query], n_results=n_res, where=where_filter)
        except Exception:
            if is_openai:
                col = self.client.get_or_create_collection(
                    name="medihan_kb_local",
                    embedding_function=KoreanMedicalLocalEmbedding(),
                )
                if col.count() == 0:
                    self.ensure_indexed(force=True, api_key="")
                res = col.query(query_texts=[query], n_results=min(n_res, col.count()), where=where_filter)
            else:
                return []

        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]

        q_tokens = [t for t in re.split(r"[^0-9a-zA-Z가-힣]+", query.lower()) if len(t) >= 2]
        scored: List[Dict[str, Any]] = []
        for idx, doc_id in enumerate(ids):
            content = docs[idx] if idx < len(docs) else ""
            meta = metas[idx] if idx < len(metas) else {}
            dist = float(dists[idx]) if idx < len(dists) else 1.0
            content_lower = f"{meta.get('title', '')} {content}".lower()
            kw_hits = sum(1 for tok in q_tokens if tok in content_lower)
            score = kw_hits * 1.5 + max(0.0, 2.0 - dist)
            scored.append(
                {
                    "id": doc_id,
                    "category": meta.get("category", "의학기준"),
                    "title": meta.get("title", meta.get("source_file", "문서")),
                    "source": meta.get("source", meta.get("source_file", "")),
                    "source_file": meta.get("source_file", ""),
                    "page": meta.get("page", 1),
                    "content": content,
                    "score": round(score, 3),
                }
            )

        threshold = rag_min_score()
        scored = [d for d in scored if d["score"] >= threshold]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def get_status(self, api_key: str = "") -> Dict[str, Any]:
        chunk_count = self.ensure_indexed(force=False, api_key=api_key)
        files = []
        for p in sorted(KNOWLEDGE_BASE_DIR.iterdir()):
            if p.is_file() and p.suffix.lower() in (".pdf", ".md", ".txt"):
                files.append(
                    {
                        "filename": p.name,
                        "ext": p.suffix.lower(),
                        "size_kb": round(p.stat().st_size / 1024, 1),
                    }
                )
        return {
            "knowledge_base_dir": str(KNOWLEDGE_BASE_DIR),
            "files": files,
            "file_count": len(files),
            "chunk_count": chunk_count,
            "embedding_mode": self._active_mode,
        }


RAG_SERVICE = ProductionMedicalRAG()
