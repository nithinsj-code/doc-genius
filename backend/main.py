"""
DocGenius API — FastAPI backend
Combines:
  1. Gemini-powered text generation (originally app.py)
  2. PDF chat / Q&A using OpenAI embeddings + FAISS (originally DocGenius/PDFChat.py)

Deploy this on Render. See ../README_DEPLOY.md for step-by-step instructions.
"""

import os
import uuid
import time
from typing import Dict, List

import numpy as np
import faiss
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from pypdf import PdfReader

import google.generativeai as genai

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API")

# Comma-separated list of allowed frontend origins, e.g.
# "https://your-site.netlify.app,http://localhost:3000"
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

EMBEDDING_MODEL = "models/gemini-embedding-2"
CHAT_MODEL = "gemini-1.5-flash"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
SESSION_TTL_SECONDS = 60 * 60  # 1 hour

# In-memory store of uploaded PDFs -> {chunks, index, created_at, filename}
# NOTE: this resets whenever the server restarts / cold-starts (fine for a demo
# project). For production, swap this for Redis / a database.
SESSIONS: Dict[str, dict] = {}

app = FastAPI(title="DocGenius API", version="1.0.0")

origins = ["*"] if ALLOWED_ORIGINS.strip() == "*" else [
    o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    prompt: str


class GenerateResponse(BaseModel):
    response: str


class AskRequest(BaseModel):
    session_id: str
    question: str


class AskResponse(BaseModel):
    answer: str


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    num_chunks: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Simple sliding-window character splitter (mirrors the original
    langchain CharacterTextSplitter behaviour, split on newlines first)."""
    raw_parts = [p for p in text.split("\n") if p.strip()]
    joined = "\n".join(raw_parts)

    chunks = []
    start = 0
    n = len(joined)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(joined[start:end])
        if end == n:
            break
        start = end - overlap
    return chunks


def embed_texts(texts: List[str]) -> np.ndarray:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API is not configured on the server.")
    
    resp = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=texts
    )
    vectors = resp['embedding']
    return np.array(vectors, dtype="float32")


def cleanup_expired_sessions():
    now = time.time()
    expired = [sid for sid, s in SESSIONS.items() if now - s["created_at"] > SESSION_TTL_SECONDS]
    for sid in expired:
        SESSIONS.pop(sid, None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "gemini_configured": bool(GEMINI_API_KEY),
    }


@app.post("/api/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API is not configured on the server.")
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    model = genai.GenerativeModel("gemini-1.5-flash")
    result = model.generate_content(req.prompt)
    return GenerateResponse(response=result.text)


@app.post("/api/pdf/upload", response_model=UploadResponse)
def upload_pdf(file: UploadFile = File(...)):
    cleanup_expired_sessions()

    if file.content_type not in ("application/pdf", "application/x-pdf") and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    reader = PdfReader(file.file)
    text = ""
    for page in reader.pages:
        extracted = page.extract_text() or ""
        text += extracted

    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract any text from this PDF.")

    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="PDF produced no usable text chunks.")

    vectors = embed_texts(chunks)
    index = faiss.IndexFlatL2(vectors.shape[1])
    index.add(vectors)

    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {
        "chunks": chunks,
        "index": index,
        "filename": file.filename,
        "created_at": time.time(),
    }

    return UploadResponse(session_id=session_id, filename=file.filename, num_chunks=len(chunks))


@app.post("/api/pdf/ask", response_model=AskResponse)
def ask_pdf(req: AskRequest):
    session = SESSIONS.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired. Please re-upload the PDF.")
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API is not configured on the server.")

    query_vector = embed_texts([req.question])
    k = min(4, len(session["chunks"]))
    _, indices = session["index"].search(query_vector, k)
    relevant_chunks = [session["chunks"][i] for i in indices[0] if i != -1]
    context = "\n\n---\n\n".join(relevant_chunks)

    system_prompt = (
        "You are DocGenius, an assistant that answers questions strictly using the "
        "provided PDF excerpts. If the answer is not contained in the excerpts, say "
        "you don't know based on the document. Do not answer unrelated questions."
    )
    user_prompt = f"Document excerpts:\n{context}\n\nQuestion: {req.question}"

    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    model = genai.GenerativeModel(CHAT_MODEL)
    result = model.generate_content(
        full_prompt,
        generation_config=genai.GenerationConfig(temperature=0.2)
    )
    answer = result.text
    return AskResponse(answer=answer)


@app.get("/")
def root():
    return {"message": "DocGenius API is running. See /docs for the interactive API explorer."}
